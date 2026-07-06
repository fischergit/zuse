// Thin async REST wrapper for the zuse-web API.
import Foundation

struct BackendError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct BackendClient {
    let baseURL: URL
    private let session: URLSession

    init(baseURL: URL) {
        self.baseURL = baseURL
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 15
        self.session = URLSession(configuration: config)
    }

    func status() async throws -> StatusPayload {
        try await get("/api/status")
    }

    func chat(message: String) async throws -> JobPayload {
        try await post("/api/chat", body: ["message": message])
    }

    func job(id: String) async throws -> JobPayload {
        try await get("/api/job?id=\(id.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? id)")
    }

    func clear() async throws -> String {
        let r: MessageResponse = try await post("/api/clear", body: [:])
        return r.message
    }

    func save() async throws -> String {
        let r: MessageResponse = try await post("/api/save", body: [:])
        return r.message
    }

    func cost() async throws -> String {
        let r: CostResponse = try await get("/api/cost")
        return r.summary
    }

    func logs() async throws -> String {
        let r: LogsResponse = try await get("/api/logs")
        return r.logs
    }

    // MARK: - plumbing

    private func get<T: Decodable>(_ path: String) async throws -> T {
        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw BackendError(message: "Ungültige URL: \(path)")
        }
        let (data, response) = try await session.data(from: url)
        return try decode(data, response)
    }

    private func post<T: Decodable>(_ path: String, body: [String: String]) async throws -> T {
        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw BackendError(message: "Ungültige URL: \(path)")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await session.data(for: request)
        return try decode(data, response)
    }

    private func decode<T: Decodable>(_ data: Data, _ response: URLResponse) throws -> T {
        let code = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else {
            // Error bodies look like {"error": "..."} — surface that text.
            if let err = try? JSONDecoder().decode([String: String].self, from: data),
               let msg = err["error"] {
                throw BackendError(message: msg)
            }
            throw BackendError(message: "Backend-Fehler (HTTP \(code))")
        }
        return try JSONDecoder().decode(T.self, from: data)
    }
}
