// Minimal Server-Sent-Events client for the zuse-web /api/events endpoint.
//
// The server frames events as `id: <int>\nevent: <kind>\ndata: <json>\n\n` and
// sends `: keepalive` comment lines every ~15s. IMPORTANT: the server ignores
// Last-Event-ID and replays its whole buffer (last 500 events) on every
// (re)connect — client-side dedupe by event id is mandatory here.
import Foundation

final class SSEClient: @unchecked Sendable {
    private let url: URL
    private let onEvent: (SSEEvent) -> Void
    private let onConnectionChange: (Bool) -> Void

    private var task: Task<Void, Never>?
    private var lastEventID = 0
    private let session: URLSession

    init(url: URL,
         onEvent: @escaping (SSEEvent) -> Void,
         onConnectionChange: @escaping (Bool) -> Void) {
        self.url = url
        self.onEvent = onEvent
        self.onConnectionChange = onConnectionChange
        let config = URLSessionConfiguration.ephemeral
        // Idle timeout: keepalives arrive every 15s, so 60s means "stream stalled".
        config.timeoutIntervalForRequest = 60
        config.timeoutIntervalForResource = .infinity
        self.session = URLSession(configuration: config)
    }

    func start() {
        guard task == nil else { return }
        task = Task { [weak self] in
            await self?.connectLoop()
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    private func connectLoop() async {
        while !Task.isCancelled {
            do {
                var request = URLRequest(url: url)
                request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
                // Spec-correct even though this server ignores it.
                request.setValue(String(lastEventID), forHTTPHeaderField: "Last-Event-ID")

                let (bytes, response) = try await session.bytes(for: request)
                guard (response as? HTTPURLResponse)?.statusCode == 200 else {
                    throw URLError(.badServerResponse)
                }
                onConnectionChange(true)
                try await parse(bytes)
            } catch {
                // fall through to reconnect
            }
            onConnectionChange(false)
            if Task.isCancelled { break }
            try? await Task.sleep(nanoseconds: 1_000_000_000)
        }
    }

    /// Byte-exact SSE framing: split on 0x0A ourselves — the empty line IS the
    /// event delimiter, so we must not rely on higher-level line iterators.
    private func parse(_ bytes: URLSession.AsyncBytes) async throws {
        var lineBuf: [UInt8] = []
        var pendingID: Int?
        var pendingKind = "message"
        var dataLines: [String] = []

        func dispatch() {
            defer { pendingID = nil; pendingKind = "message"; dataLines = [] }
            guard !dataLines.isEmpty, let id = pendingID else { return }
            guard id > lastEventID else { return }  // replayed on reconnect — drop
            lastEventID = id
            let data = Data(dataLines.joined(separator: "\n").utf8)
            onEvent(SSEEvent(id: id, kind: pendingKind, data: data))
        }

        for try await byte in bytes {
            if Task.isCancelled { return }
            if byte != 0x0A {
                lineBuf.append(byte)
                continue
            }
            if lineBuf.last == 0x0D { lineBuf.removeLast() }
            let line = String(decoding: lineBuf, as: UTF8.self)
            lineBuf.removeAll(keepingCapacity: true)

            if line.isEmpty {
                dispatch()
                continue
            }
            if line.hasPrefix(":") { continue }  // keepalive comment

            let field: Substring
            var value: Substring
            if let colon = line.firstIndex(of: ":") {
                field = line[line.startIndex..<colon]
                value = line[line.index(after: colon)...]
                if value.first == " " { value = value.dropFirst() }
            } else {
                field = line[...]
                value = ""
            }
            switch field {
            case "id": pendingID = Int(value)
            case "event": pendingKind = String(value)
            case "data": dataLines.append(String(value))
            default: break
            }
        }
    }
}
