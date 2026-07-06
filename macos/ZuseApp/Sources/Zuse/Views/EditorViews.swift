// IDE half of the app: file tree, a real editable code editor (NSTextView +
// Highlightr syntax colors), and the bottom panel with an integrated terminal
// (SwiftTerm) and the live agent log.
import AppKit
import Highlightr
import SwiftTerm
import SwiftUI

// MARK: - file tree

private let skippedNames: Set<String> = [
    ".git", ".venv", ".build", "node_modules", "__pycache__", ".DS_Store",
    "dist", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".idea",
]

struct FileNode: Identifiable {
    let url: URL
    let isDirectory: Bool
    var id: String { url.path }
    var name: String { url.lastPathComponent }
}

func childNodes(of url: URL) -> [FileNode] {
    let contents = (try? FileManager.default.contentsOfDirectory(
        at: url,
        includingPropertiesForKeys: [.isDirectoryKey],
        options: [.skipsHiddenFiles]
    )) ?? []
    return contents
        .filter { !skippedNames.contains($0.lastPathComponent) }
        .map { url in
            let isDir = (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) ?? false
            return FileNode(url: url, isDirectory: isDir)
        }
        .sorted { a, b in
            if a.isDirectory != b.isDirectory { return a.isDirectory }
            return a.name.localizedCaseInsensitiveCompare(b.name) == .orderedAscending
        }
}

struct FileTreeView: View {
    let root: URL

    var body: some View {
        LazyVStack(alignment: .leading, spacing: 1) {
            ForEach(childNodes(of: root)) { node in
                FileTreeRow(node: node, depth: 0)
            }
        }
    }
}

struct FileTreeRow: View {
    let node: FileNode
    let depth: Int
    @State private var expanded = false
    @EnvironmentObject var state: AppState

    var body: some View {
        Button {
            if node.isDirectory {
                withAnimation(.easeOut(duration: 0.12)) { expanded.toggle() }
            } else {
                state.openFile(at: node.url)
            }
        } label: {
            HStack(spacing: 5) {
                if node.isDirectory {
                    Image(systemName: expanded ? "chevron.down" : "chevron.right")
                        .font(.system(size: 8, weight: .semibold))
                        .foregroundStyle(Theme.secondary)
                        .frame(width: 10)
                    Image(systemName: "folder")
                        .font(.system(size: 10))
                        .foregroundStyle(Theme.accent.opacity(0.85))
                } else {
                    Spacer().frame(width: 10)
                    Image(systemName: "doc")
                        .font(.system(size: 10))
                        .foregroundStyle(Theme.secondary)
                }
                Text(node.name)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(Theme.text)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 0)
            }
            .padding(.vertical, 2.5)
            .padding(.leading, CGFloat(depth) * 12 + 4)
            .contentShape(Rectangle())
        }
        .buttonStyle(SidebarButtonStyle())

        if node.isDirectory && expanded {
            ForEach(childNodes(of: node.url)) { child in
                FileTreeRow(node: child, depth: depth + 1)
            }
        }
    }
}

// MARK: - code editor (NSTextView + Highlightr + line numbers)

struct CodeEditorView: NSViewRepresentable {
    @Binding var text: String
    let language: String?
    let editable: Bool

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeNSView(context: Context) -> NSScrollView {
        // IMPORTANT: use the stock AppKit text stack. A hand-rolled TextKit-1
        // stack (NSLayoutManager + custom NSTextStorage) broke rendering of the
        // entire window's sibling views on macOS 26 — highlighting is applied
        // from the outside instead (debounced, in the coordinator).
        let scrollView = NSTextView.scrollableTextView()
        guard let textView = scrollView.documentView as? NSTextView else { return scrollView }
        textView.isEditable = editable
        textView.isRichText = false
        textView.allowsUndo = true
        textView.drawsBackground = true
        textView.backgroundColor = Theme.editorBackground
        textView.insertionPointColor = NSColor.white
        textView.textColor = Theme.editorForeground
        textView.font = NSFont.monospacedSystemFont(ofSize: 12.5, weight: .regular)
        textView.textContainerInset = CGSize(width: 6, height: 8)
        textView.delegate = context.coordinator
        textView.string = text

        scrollView.hasVerticalScroller = true
        scrollView.drawsBackground = true
        scrollView.backgroundColor = Theme.editorBackground

        // NOTE deliberately NO NSRulerView here: any active ruler (sync or
        // async-attached) breaks compositing of ALL sibling SwiftUI views on
        // macOS 26 — the whole explorer/tab bar went blank. Line numbers need
        // a different technique (e.g. floating gutter view) later.
        context.coordinator.attach(textView: textView, language: language)
        context.coordinator.scheduleHighlight(initial: true)
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView else { return }
        // Only push external changes (e.g. tab switch reuse); user edits flow
        // through the delegate and must not be overwritten mid-typing.
        if textView.string != text && !context.coordinator.isEditing {
            textView.string = text
            context.coordinator.scheduleHighlight(initial: true)
        }
    }

    @MainActor
    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: CodeEditorView
        var isEditing = false
        private weak var textView: NSTextView?
        private var language: String?
        private var highlightTask: Task<Void, Never>?
        private lazy var highlightr: Highlightr? = {
            let h = Highlightr()
            h?.setTheme(to: "atom-one-dark")
            h?.theme.setCodeFont(NSFont.monospacedSystemFont(ofSize: 12.5, weight: .regular))
            return h
        }()

        init(_ parent: CodeEditorView) {
            self.parent = parent
        }

        func attach(textView: NSTextView, language: String?) {
            self.textView = textView
            self.language = language
        }

        nonisolated func textDidChange(_ notification: Notification) {
            MainActor.assumeIsolated {
                guard let textView else { return }
                isEditing = true
                parent.text = textView.string
                isEditing = false
                scheduleHighlight(initial: false)
            }
        }

        /// Debounced full-buffer re-highlight. Fast enough for real files; very
        /// large buffers skip highlighting entirely.
        func scheduleHighlight(initial: Bool) {
            guard language != nil else { return }
            highlightTask?.cancel()
            highlightTask = Task { [weak self] in
                if !initial {
                    try? await Task.sleep(nanoseconds: 300_000_000)
                }
                guard !Task.isCancelled else { return }
                self?.applyHighlight()
            }
        }

        private func applyHighlight() {
            guard let textView, let language, let highlightr,
                  let storage = textView.textStorage else { return }
            let code = textView.string
            guard code.count < 150_000 else { return }  // keep typing snappy
            guard let highlighted = highlightr.highlight(code, as: language) else { return }
            // Guard against races: only apply if the buffer hasn't changed.
            guard highlighted.string == textView.string else { return }
            let selection = textView.selectedRange()
            storage.setAttributedString(highlighted)
            textView.typingAttributes = [
                .font: NSFont.monospacedSystemFont(ofSize: 12.5, weight: .regular),
                .foregroundColor: Theme.editorForeground,
            ]
            if selection.location <= (textView.string as NSString).length {
                textView.setSelectedRange(selection)
            }
        }
    }
}

// MARK: - integrated terminal (SwiftTerm)

/// Keeps ONE live shell per app run, so toggling the bottom panel doesn't kill
/// and respawn the terminal session.
@MainActor
final class TerminalHost {
    static let shared = TerminalHost()
    private var view: LocalProcessTerminalView?

    func terminalView(cwd: URL) -> LocalProcessTerminalView {
        if let view { return view }
        let tv = LocalProcessTerminalView(frame: .zero)
        tv.nativeBackgroundColor = Theme.editorBackground
        tv.nativeForegroundColor = Theme.editorForeground
        tv.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        let shell = ProcessInfo.processInfo.environment["SHELL"] ?? "/bin/zsh"
        tv.startProcess(executable: shell, args: ["-l"], environment: nil, execName: nil)
        // startProcess has no cwd parameter — steer the fresh shell instead.
        tv.send(txt: "cd '\(cwd.path)' && clear\n")
        view = tv
        return tv
    }
}

struct TerminalPane: NSViewRepresentable {
    let cwd: URL

    func makeNSView(context: Context) -> LocalProcessTerminalView {
        TerminalHost.shared.terminalView(cwd: cwd)
    }

    func updateNSView(_ nsView: LocalProcessTerminalView, context: Context) {}
}

// MARK: - bottom panel (terminal | agent log)

struct BottomPanelView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 2) {
                panelTab("Terminal", icon: "terminal", tab: .terminal)
                panelTab("Agent-Log", icon: "doc.plaintext", tab: .log)
                Spacer()
                Button {
                    state.showConsole = false
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 9, weight: .bold))
                        .foregroundStyle(Theme.secondary)
                }
                .buttonStyle(.plain)
                .padding(.trailing, 8)
            }
            .padding(.horizontal, 6)
            .padding(.vertical, 4)
            Theme.border.frame(height: 1)

            switch state.bottomTab {
            case .terminal:
                TerminalPane(cwd: state.workingDirectory)
            case .log:
                LogView(text: state.consoleText)
            }
        }
    }

    private func panelTab(_ title: String, icon: String, tab: AppState.BottomTab) -> some View {
        let selected = state.bottomTab == tab
        return Button {
            state.bottomTab = tab
        } label: {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 9))
                Text(title)
                    .font(.system(size: 10.5, design: .monospaced))
            }
            .foregroundStyle(selected ? Theme.text : Theme.secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(
                RoundedRectangle(cornerRadius: 5)
                    .fill(selected ? Theme.hover : .clear)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

struct LogView: View {
    let text: String

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                Text(text.isEmpty ? "(noch keine Ausgabe)" : text)
                    .font(.system(size: 10.5, design: .monospaced))
                    .foregroundStyle(text.isEmpty ? Theme.secondary : Theme.text)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
                    .id("log-end")
            }
            .onChange(of: text) {
                proxy.scrollTo("log-end", anchor: .bottom)
            }
        }
    }
}
