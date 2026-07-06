// Locates, spawns, and supervises the local zuse-web backend.
//
// Strategy: if a healthy server already answers on the default port 8765
// (e.g. the user's own `zuse-web` in a terminal), reuse it — the conversation,
// session, and cost totals live in that process, and we must not kill it on
// quit. Otherwise spawn our own instance, preferring the fixed port 8766 so an
// instance orphaned by an earlier app crash is rediscovered instead of leaked.
import Darwin
import Foundation

final class BackendProcess {
    static let reusePort = 8765   // default zuse-web port
    static let spawnPort = 8766   // our preferred own port

    private(set) var baseURL: URL?
    private(set) var ownsProcess = false
    private var process: Process?
    private var logRing: [String] = []   // last ~200 backend output lines
    private let logLock = NSLock()

    /// Human-readable startup failure, if any.
    private(set) var failure: String?

    /// The agent's working directory (repo root of the zuse install) — used as
    /// the root of the app's file browser. Falls back to the home directory.
    var workingDirectory: URL {
        if let bin = Self.locateZuseWeb() {
            let root = bin.resolvingSymlinksInPath()
                .deletingLastPathComponent()   // bin
                .deletingLastPathComponent()   // .venv
                .deletingLastPathComponent()   // repo root
            if FileManager.default.fileExists(atPath: root.appendingPathComponent("pyproject.toml").path) {
                return root
            }
        }
        return FileManager.default.homeDirectoryForCurrentUser
    }

    // MARK: - locate

    static func locateZuseWeb() -> URL? {
        var candidates: [String] = []
        if let env = ProcessInfo.processInfo.environment["ZUSE_WEB_BIN"], !env.isEmpty {
            candidates.append(env)
        }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        candidates += [
            "/Users/nik/agent/.venv/bin/zuse-web",
            "\(home)/agent/.venv/bin/zuse-web",
            "\(home)/.zuse/zuse-agent/.venv/bin/zuse-web",
            "\(home)/.local/bin/zuse-web",
            "/usr/local/bin/zuse-web",
            "/opt/homebrew/bin/zuse-web",
        ]
        for path in candidates where FileManager.default.isExecutableFile(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        return nil
    }

    // MARK: - startup

    /// Ensure a backend is reachable; returns its base URL or nil (see `failure`).
    func ensureBackend() async -> URL? {
        // 1. Reuse a healthy server on the default port, or our own fixed spawn
        //    port (self-heals orphans from a previous app crash).
        for port in [Self.reusePort, Self.spawnPort] {
            if let url = await Self.probe(port: port) {
                baseURL = url
                ownsProcess = false
                return url
            }
        }

        // 2. Spawn our own.
        guard let bin = Self.locateZuseWeb() else {
            failure = "zuse-web nicht gefunden. Bitte Installation prüfen (install.sh)."
            return nil
        }
        let port = Self.portIsFree(Self.spawnPort) ? Self.spawnPort : Self.findFreePort()
        guard let port else {
            failure = "Kein freier Port für das Zuse-Backend gefunden."
            return nil
        }

        let proc = Process()
        proc.executableURL = bin
        proc.arguments = ["--no-open", "--port", String(port)]
        let repoRoot = bin.deletingLastPathComponent()   // .venv/bin
            .deletingLastPathComponent()                 // .venv
            .deletingLastPathComponent()                 // repo root
        if FileManager.default.fileExists(atPath: repoRoot.appendingPathComponent("pyproject.toml").path) {
            proc.currentDirectoryURL = repoRoot
        }
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let chunk = handle.availableData
            guard !chunk.isEmpty, let self else { return }
            let text = String(decoding: chunk, as: UTF8.self)
            self.logLock.lock()
            self.logRing.append(contentsOf: text.split(separator: "\n").map(String.init))
            if self.logRing.count > 200 { self.logRing.removeFirst(self.logRing.count - 200) }
            self.logLock.unlock()
        }

        do {
            try proc.run()
        } catch {
            failure = "zuse-web konnte nicht gestartet werden: \(error.localizedDescription)"
            return nil
        }
        process = proc
        ownsProcess = true

        // 3. Health-poll up to 60s — agent init (provider/config) can be slow.
        //    ready:false with empty error just means "still initializing".
        let url = URL(string: "http://127.0.0.1:\(port)")!
        for _ in 0..<120 {
            if !proc.isRunning {
                failure = "Backend sofort beendet (Code \(proc.terminationStatus)).\n"
                    + recentLogs(lines: 6)
                return nil
            }
            if await Self.probe(port: port) != nil {
                baseURL = url
                return url
            }
            try? await Task.sleep(nanoseconds: 500_000_000)
        }
        failure = "Backend antwortet nicht (Timeout nach 60 s)."
        shutdown()
        return nil
    }

    func recentLogs(lines: Int = 40) -> String {
        logLock.lock()
        defer { logLock.unlock() }
        return logRing.suffix(lines).joined(separator: "\n")
    }

    // MARK: - shutdown

    /// Synchronous, bounded teardown — called from applicationWillTerminate.
    func shutdown() {
        guard ownsProcess, let proc = process, proc.isRunning else { return }
        proc.terminate()  // SIGTERM
        let deadline = Date().addingTimeInterval(2)
        while proc.isRunning && Date() < deadline {
            usleep(50_000)
        }
        if proc.isRunning {
            kill(proc.processIdentifier, SIGKILL)
        }
        process = nil
    }

    // MARK: - port helpers

    /// A server counts as healthy if /api/status answers with decodable JSON.
    private static func probe(port: Int) async -> URL? {
        guard let url = URL(string: "http://127.0.0.1:\(port)") else { return nil }
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 1.5
        let session = URLSession(configuration: config)
        do {
            let (data, response) = try await session.data(from: url.appendingPathComponent("api/status"))
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
            _ = try JSONDecoder().decode(StatusPayload.self, from: data)
            return url
        } catch {
            return nil
        }
    }

    private static func portIsFree(_ port: Int) -> Bool {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        var yes: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, socklen_t(MemoryLayout<Int32>.size))
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(port).bigEndian
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let result = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return result == 0
    }

    /// Ask the kernel for an ephemeral free port by binding to port 0.
    private static func findFreePort() -> Int? {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        guard fd >= 0 else { return nil }
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = 0
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        let bound = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        guard bound == 0 else { return nil }
        var out = sockaddr_in()
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        let got = withUnsafeMutablePointer(to: &out) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                getsockname(fd, $0, &len)
            }
        }
        guard got == 0 else { return nil }
        return Int(UInt16(bigEndian: out.sin_port))
    }
}
