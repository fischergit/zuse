// Central @MainActor state: backend lifecycle, SSE dispatch, chat + crew models.
import AppKit
import Foundation
import SwiftUI

@MainActor
final class AppState: ObservableObject {
    enum Phase: Equatable {
        case launching          // locating/starting the backend
        case connected          // backend reachable (agent may still be initializing)
        case failed(String)     // fatal startup problem
    }

    // MARK: published state

    @Published var phase: Phase = .launching
    @Published var status = StatusPayload()
    @Published var sseConnected = false
    @Published var messages: [ChatMessage] = []
    @Published var composer = ""
    @Published var activeJobID: String?

    @Published var crewGoal = ""
    @Published var crewAgents: [CrewAgent] = []
    @Published var crewFinished = false
    @Published var showCrewPanel = true   // sub-agents are a first-class citizen

    // Editor: open file tabs + bottom panel (terminal / live agent log).
    @Published var openFiles: [OpenFile] = []
    @Published var selectedFilePath: String?   // nil → welcome view
    @Published var consoleText = ""
    @Published var bottomTab: BottomTab = .terminal
    @Published var showConsole = true {
        didSet { showConsole ? startConsolePolling() : stopConsolePolling() }
    }

    enum BottomTab { case terminal, log }

    var ownsBackend: Bool { backendProcess.ownsProcess }
    var backendPort: Int { backendClient.map { $0.baseURL.port ?? 80 } ?? 0 }
    var workingDirectory: URL { backendProcess.workingDirectory }

    // MARK: internals

    private let backendProcess = BackendProcess()
    private var backendClient: BackendClient?
    private var sseClient: SSEClient?
    private var eventContinuation: AsyncStream<SSEEvent>.Continuation?
    private var pollTask: Task<Void, Never>?
    private var consoleTask: Task<Void, Never>?
    /// Wall-clock start per running crew agent (server timestamps are monotonic).
    private var runningSince: [String: Date] = [:]

    // MARK: - lifecycle

    func start() {
        guard case .launching = phase, backendClient == nil else { return }
        Task {
            guard let url = await backendProcess.ensureBackend() else {
                phase = .failed(backendProcess.failure ?? "Backend nicht erreichbar.")
                return
            }
            let client = BackendClient(baseURL: url)
            backendClient = client
            phase = .connected
            if let s = try? await client.status() {
                status = s
            }
            startEventStream(url: url)
            // didSet doesn't fire for the default value — start the log poller.
            if showConsole { startConsolePolling() }
            // Debug/testing hook: open a file on launch (ZUSE_OPEN_FILE=/path).
            if let debugFile = ProcessInfo.processInfo.environment["ZUSE_OPEN_FILE"],
               !debugFile.isEmpty {
                openFile(at: URL(fileURLWithPath: debugFile))
            }
        }
    }

    nonisolated func shutdown() {
        // applicationWillTerminate is synchronous; BackendProcess.shutdown blocks ≤2s.
        MainActor.assumeIsolated {
            sseClient?.stop()
            backendProcess.shutdown()
        }
    }

    private func startEventStream(url: URL) {
        // Single ordered consumer: SSE callbacks push into an AsyncStream that is
        // drained on the MainActor, so event order is guaranteed by construction.
        let stream = AsyncStream<SSEEvent> { continuation in
            eventContinuation = continuation
        }
        let sse = SSEClient(
            url: url.appendingPathComponent("api/events"),
            onEvent: { [weak self] event in
                self?.eventContinuation?.yield(event)
            },
            onConnectionChange: { [weak self] connected in
                Task { @MainActor in self?.sseConnected = connected }
            }
        )
        sseClient = sse
        sse.start()
        Task { [weak self] in
            for await event in stream {
                self?.apply(event)
            }
        }
    }

    // MARK: - SSE dispatch

    private func apply(_ event: SSEEvent) {
        let decoder = JSONDecoder()
        switch event.kind {
        case "status":
            if let s = try? decoder.decode(StatusPayload.self, from: event.data) {
                status = s
            }
        case "delta":
            // Gate on an active job: the server replays history on reconnect and
            // deltas carry no job id — without the gate we'd render ghost text.
            guard activeJobID != nil,
                  let d = try? decoder.decode(TextDelta.self, from: event.data) else { return }
            appendToLiveBubble(d.text)
        case "job":
            guard let job = try? decoder.decode(JobPayload.self, from: event.data) else { return }
            handleJobEvent(job)
        case "crew_start":
            guard let p = try? decoder.decode(CrewStartPayload.self, from: event.data) else { return }
            crewGoal = p.goal
            crewAgents = p.agents
            crewFinished = false
            runningSince = [:]
            showCrewPanel = true
        case "crew_update":
            guard let p = try? decoder.decode(CrewUpdatePayload.self, from: event.data) else { return }
            adoptCrewAgents(p.agents)
        case "crew_done":
            guard let p = try? decoder.decode(CrewStartPayload.self, from: event.data) else { return }
            adoptCrewAgents(p.agents)
            crewFinished = true
        default:
            break  // thinking / step — unused in v1
        }
    }

    private func adoptCrewAgents(_ agents: [CrewAgent]) {
        for agent in agents where agent.status == "running" && runningSince[agent.id] == nil {
            runningSince[agent.id] = Date()
        }
        crewAgents = agents
        if !agents.isEmpty { showCrewPanel = true }
    }

    /// Elapsed seconds for a crew agent row (wall-clock for running ones).
    func elapsed(for agent: CrewAgent) -> Double {
        if let done = agent.finishedElapsed { return done }
        if agent.status == "running", let since = runningSince[agent.id] {
            return Date().timeIntervalSince(since)
        }
        return 0
    }

    var crewOverallPercent: Int {
        guard !crewAgents.isEmpty else { return 0 }
        let mean = crewAgents.map(\.fraction).reduce(0, +) / Double(crewAgents.count)
        return Int((mean * 100).rounded())
    }

    // MARK: - chat state machine

    func send() {
        let text = composer.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, activeJobID == nil, status.ready, let client = backendClient else { return }
        composer = ""
        messages.append(ChatMessage(role: .user, text: text))
        messages.append(ChatMessage(role: .assistant, text: "", isStreaming: true))
        Task {
            do {
                let job = try await client.chat(message: text)
                activeJobID = job.id
                startJobPolling(id: job.id, client: client)
            } catch {
                dropLiveBubble()
                messages.append(ChatMessage(role: .system, text: "Fehler: \(error.localizedDescription)"))
            }
        }
    }

    private func handleJobEvent(_ job: JobPayload) {
        guard job.id == activeJobID else { return }
        switch job.status {
        case "done":
            finalizeJob(answer: job.answer ?? "", error: nil)
        case "error":
            finalizeJob(answer: "", error: job.error ?? "Unbekannter Fehler")
        default:
            break  // queued/running — nothing to render beyond the busy status
        }
    }

    /// Belt-and-suspenders against missed SSE events (mirrors the web UI's poll).
    private func startJobPolling(id: String, client: BackendClient) {
        pollTask?.cancel()
        pollTask = Task { [weak self] in
            // Task {} inherits the MainActor context of AppState.
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                guard let self, self.activeJobID == id else { return }
                guard let job = try? await client.job(id: id) else { continue }
                guard self.activeJobID == id else { return }
                if job.status == "done" {
                    self.finalizeJob(answer: job.answer ?? "", error: nil)
                } else if job.status == "error" {
                    self.finalizeJob(answer: "", error: job.error ?? "Unbekannter Fehler")
                }
            }
        }
    }

    /// Idempotent: SSE event and fallback poll may both arrive.
    private func finalizeJob(answer: String, error: String?) {
        guard activeJobID != nil else { return }
        activeJobID = nil
        pollTask?.cancel()
        pollTask = nil

        if let error {
            dropLiveBubble()
            messages.append(ChatMessage(role: .system, text: "Fehler: \(error)"))
            return
        }
        guard let idx = liveBubbleIndex() else { return }
        // Prefer the canonical answer only when it is at least as long as the
        // streamed text: multi-step turns stream intermediate text that the final
        // answer (last message only) drops — users must not see content vanish.
        if answer.count >= messages[idx].text.count {
            messages[idx].text = answer
        }
        messages[idx].isStreaming = false
        if messages[idx].text.isEmpty {
            messages[idx].text = "Fertig."
        }
    }

    private func liveBubbleIndex() -> Int? {
        messages.lastIndex(where: { $0.isStreaming })
    }

    private func appendToLiveBubble(_ text: String) {
        guard let idx = liveBubbleIndex() else { return }
        messages[idx].text += text
    }

    private func dropLiveBubble() {
        if let idx = liveBubbleIndex(), messages[idx].text.isEmpty {
            messages.remove(at: idx)
        } else if let idx = liveBubbleIndex() {
            messages[idx].isStreaming = false
        }
    }

    // MARK: - menu actions

    func clearConversation() {
        guard let client = backendClient else { return }
        Task {
            do {
                let msg = try await client.clear()
                messages = [ChatMessage(role: .system, text: msg)]
                crewAgents = []
                crewGoal = ""
                showCrewPanel = false
            } catch {
                messages.append(ChatMessage(role: .system, text: "Fehler: \(error.localizedDescription)"))
            }
        }
    }

    func showCost() {
        guard let client = backendClient else { return }
        Task {
            do {
                let summary = try await client.cost()
                messages.append(ChatMessage(role: .system, text: summary))
            } catch {
                messages.append(ChatMessage(role: .system, text: "Fehler: \(error.localizedDescription)"))
            }
        }
    }

    func saveSession() {
        guard let client = backendClient else { return }
        Task {
            do {
                let msg = try await client.save()
                messages.append(ChatMessage(role: .system, text: msg))
            } catch {
                messages.append(ChatMessage(role: .system, text: "Fehler: \(error.localizedDescription)"))
            }
        }
    }

    func openInBrowser() {
        guard let url = backendClient?.baseURL else { return }
        NSWorkspace.shared.open(url)
    }

    // MARK: - editor tabs

    func openFile(at url: URL) {
        let path = url.path
        if !openFiles.contains(where: { $0.path == path }) {
            let (content, editable) = Self.loadFile(url)
            openFiles.append(OpenFile(
                path: path,
                name: url.lastPathComponent,
                content: content,
                savedContent: content,
                editable: editable,
                language: highlightLanguage(forExtension: url.pathExtension)
            ))
        }
        selectedFilePath = path
    }

    func closeFile(_ path: String) {
        openFiles.removeAll { $0.path == path }
        if selectedFilePath == path {
            selectedFilePath = openFiles.last?.path
        }
    }

    /// Live buffer binding for the editor.
    func contentBinding(for path: String) -> Binding<String> {
        Binding(
            get: { [weak self] in
                self?.openFiles.first(where: { $0.path == path })?.content ?? ""
            },
            set: { [weak self] newValue in
                guard let self,
                      let idx = self.openFiles.firstIndex(where: { $0.path == path }) else { return }
                self.openFiles[idx].content = newValue
            }
        )
    }

    func saveSelectedFile() {
        guard let path = selectedFilePath,
              let idx = openFiles.firstIndex(where: { $0.path == path }),
              openFiles[idx].editable else { return }
        do {
            try openFiles[idx].content.write(toFile: path, atomically: true, encoding: .utf8)
            openFiles[idx].savedContent = openFiles[idx].content
        } catch {
            messages.append(ChatMessage(
                role: .system, text: "Fehler beim Speichern: \(error.localizedDescription)"
            ))
        }
    }

    private static func loadFile(_ url: URL) -> (String, Bool) {
        guard let data = try? Data(contentsOf: url) else {
            return ("⟨Datei konnte nicht gelesen werden⟩", false)
        }
        if data.count > 400_000 {
            return ("⟨Datei zu groß für den Editor (\(data.count / 1024) KB)⟩", false)
        }
        guard let text = String(data: data, encoding: .utf8) else {
            return ("⟨Binärdatei⟩", false)
        }
        return (text, true)
    }

    // MARK: - IDE console (live agent log)

    private func startConsolePolling() {
        consoleTask?.cancel()
        consoleTask = Task { [weak self] in
            // Task {} inherits the MainActor context of AppState.
            while !Task.isCancelled {
                if let self, let client = self.backendClient,
                   let logs = try? await client.logs() {
                    self.consoleText = logs
                }
                try? await Task.sleep(nanoseconds: 2_500_000_000)
            }
        }
    }

    private func stopConsolePolling() {
        consoleTask?.cancel()
        consoleTask = nil
    }
}
