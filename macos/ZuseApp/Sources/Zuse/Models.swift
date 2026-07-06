// Wire payloads of the zuse-web backend (zuse/webui.py) plus app-level models.
import Foundation

// MARK: - SSE

struct SSEEvent {
    let id: Int
    let kind: String
    let data: Data
}

// MARK: - REST payloads

struct StatusPayload: Decodable {
    var ready: Bool = false
    var busy: Bool = false
    var error: String = ""
    var provider: String = ""
    var model: String = ""

    private enum CodingKeys: String, CodingKey { case ready, busy, error, provider, model }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ready = try c.decodeIfPresent(Bool.self, forKey: .ready) ?? false
        busy = try c.decodeIfPresent(Bool.self, forKey: .busy) ?? false
        error = try c.decodeIfPresent(String.self, forKey: .error) ?? ""
        provider = try c.decodeIfPresent(String.self, forKey: .provider) ?? ""
        model = try c.decodeIfPresent(String.self, forKey: .model) ?? ""
    }
}

struct JobPayload: Decodable {
    var id: String
    var status: String            // queued | running | done | error
    var message: String?
    var answer: String?
    var error: String?
}

struct TextDelta: Decodable {
    var text: String
}

struct MessageResponse: Decodable {
    var message: String
}

struct CostResponse: Decodable {
    var summary: String
}

struct LogsResponse: Decodable {
    var logs: String
}

// MARK: - editor tabs

/// A file open in the editor. `content` is the live buffer; `savedContent`
/// mirrors what is on disk, so `isDirty` drives the tab indicator and ⌘S.
struct OpenFile: Identifiable, Equatable {
    let path: String
    let name: String
    var content: String
    var savedContent: String
    let editable: Bool
    let language: String?   // highlight.js language name, from the extension
    var id: String { path }
    var isDirty: Bool { editable && content != savedContent }
}

/// highlight.js language for a file extension (nil → plain text).
func highlightLanguage(forExtension ext: String) -> String? {
    switch ext.lowercased() {
    case "py": return "python"
    case "swift": return "swift"
    case "js", "mjs", "cjs": return "javascript"
    case "ts", "tsx": return "typescript"
    case "sh", "bash", "zsh": return "bash"
    case "json": return "json"
    case "md", "markdown": return "markdown"
    case "html", "htm", "xml", "plist": return "xml"
    case "css": return "css"
    case "yml", "yaml": return "yaml"
    case "toml", "ini", "cfg": return "ini"
    case "rs": return "rust"
    case "go": return "go"
    case "c", "h": return "c"
    case "cpp", "cc", "hpp": return "cpp"
    case "java": return "java"
    case "rb": return "ruby"
    case "php": return "php"
    case "sql": return "sql"
    default: return nil
    }
}

// MARK: - Crew

/// One specialist sub-agent as serialized by `asdict(AgentRun)` (zuse/agentpool.py).
/// NOTE: `fraction`/`percent`/`elapsed` are @property in Python and therefore NOT
/// in the payload — the formula is replicated here and must match agentpool.py.
/// `started`/`ended` are server-side time.monotonic() values: only their
/// difference is meaningful, never render them as dates.
struct CrewAgent: Decodable, Identifiable, Equatable {
    var id: String
    var role: String
    var title: String
    var status: String            // queued | running | done | failed
    var step: Int = 0
    var maxSteps: Int = 0
    var todosDone: Int = 0
    var todosTotal: Int = 0
    var activity: String = ""
    var error: String = ""
    var started: Double = 0
    var ended: Double = 0

    private enum CodingKeys: String, CodingKey {
        case id, role, title, status, step, activity, error, started, ended
        case maxSteps = "max_steps"
        case todosDone = "todos_done"
        case todosTotal = "todos_total"
    }

    /// Mirrors AgentRun.fraction: done → full; todo plan beats step count;
    /// failed reflects how far it got.
    var fraction: Double {
        if status == "done" { return 1.0 }
        if todosTotal > 0 { return min(1.0, Double(todosDone) / Double(todosTotal)) }
        if maxSteps > 0 { return min(1.0, Double(step) / Double(maxSteps)) }
        return 0.0
    }

    var percent: Int { Int((fraction * 100).rounded()) }

    /// Elapsed seconds for *finished* agents (monotonic difference is valid).
    /// For running agents the app tracks wall-clock locally (AppState.runningSince).
    var finishedElapsed: Double? {
        guard started > 0, ended > 0 else { return nil }
        return ended - started
    }
}

struct CrewStartPayload: Decodable {
    var goal: String
    var agents: [CrewAgent]
}

struct CrewUpdatePayload: Decodable {
    var agents: [CrewAgent]
}

// MARK: - Chat transcript

struct ChatMessage: Identifiable, Equatable {
    enum Role { case user, assistant, system }

    let id = UUID()
    var role: Role
    var text: String
    var isStreaming: Bool = false
}
