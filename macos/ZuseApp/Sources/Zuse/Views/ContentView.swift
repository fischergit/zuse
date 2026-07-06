import SwiftUI

private enum ContextTab: String, CaseIterable, Identifiable {
    case files = "Files"
    case agents = "Agents"
    case terminal = "Terminal"

    var id: String { rawValue }
}

struct ContentView: View {
    @EnvironmentObject var state: AppState
    @State private var showSidebar = true
    @State private var showContext = false
    @State private var contextTab: ContextTab = .files

    var body: some View {
        ZStack {
            VisualEffectBackground()
                .ignoresSafeArea()
            Theme.windowBackground.opacity(0.985)
                .ignoresSafeArea()

            HStack(spacing: 0) {
                if showSidebar {
                    TaskSidebar(showContext: $showContext, contextTab: $contextTab)
                        .frame(width: 252)
                    DividerLine(axis: .vertical)
                }

                VStack(spacing: 0) {
                    ThreadHeader(showSidebar: $showSidebar, showContext: $showContext)
                    DividerLine(axis: .horizontal)
                    ThreadStage()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)

                if showContext {
                    DividerLine(axis: .vertical)
                    ContextDrawer(selectedTab: $contextTab)
                        .frame(width: 352)
                }
            }
        }
        .tint(Theme.accent)
        .toolbar {
            ToolbarItem(placement: .navigation) {
                Button {
                    withAnimation(.easeOut(duration: 0.16)) { showSidebar.toggle() }
                } label: {
                    Image(systemName: "sidebar.left")
                }
                .help("Sidebar")
            }
            ToolbarItem(placement: .primaryAction) {
                Button {
                    withAnimation(.easeOut(duration: 0.16)) { showContext.toggle() }
                } label: {
                    Image(systemName: "sidebar.trailing")
                }
                .help("Context")
            }
        }
        .toolbarBackground(.hidden, for: .windowToolbar)
    }
}

private struct DividerLine: View {
    enum Axis { case horizontal, vertical }
    let axis: Axis

    var body: some View {
        Theme.border
            .frame(width: axis == .vertical ? 1 : nil, height: axis == .horizontal ? 1 : nil)
    }
}

// MARK: - Sidebar

private struct TaskSidebar: View {
    @EnvironmentObject var state: AppState
    @Binding var showContext: Bool
    @Binding var contextTab: ContextTab

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            brand
                .padding(.top, 28)

            Button {
                state.clearConversation()
            } label: {
                HStack(spacing: 9) {
                    Image(systemName: "plus")
                        .font(.system(size: 13, weight: .semibold))
                    Text("New task")
                        .font(.system(size: 13, weight: .semibold))
                    Spacer()
                }
                .foregroundStyle(Theme.text)
                .padding(.horizontal, 12)
                .padding(.vertical, 10)
                .background(Theme.surfaceRaised, in: RoundedRectangle(cornerRadius: 9))
                .overlay(RoundedRectangle(cornerRadius: 9).stroke(Theme.borderStrong, lineWidth: 1))
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 6) {
                SectionLabel(title: "Today")
                ActiveTaskRow()
            }

            VStack(alignment: .leading, spacing: 6) {
                SectionLabel(title: "Workspace")
                SidebarCommand(title: "Files", icon: "folder") {
                    showContext = true
                    contextTab = .files
                }
                SidebarCommand(title: "Agents", icon: "person.3") {
                    showContext = true
                    contextTab = .agents
                }
                SidebarCommand(title: "Terminal", icon: "terminal") {
                    state.showConsole = true
                    showContext = true
                    contextTab = .terminal
                }
            }

            if !state.openFiles.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    SectionLabel(title: "Open")
                    ForEach(state.openFiles) { file in
                        OpenFileSidebarRow(file: file) {
                            showContext = true
                            contextTab = .files
                        }
                    }
                }
            }

            Spacer(minLength: 8)
            SidebarFootnote()
        }
        .padding(.horizontal, 10)
        .padding(.bottom, 10)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Theme.sidebar)
    }

    private var brand: some View {
        HStack(spacing: 9) {
            ZStack {
                RoundedRectangle(cornerRadius: 7)
                    .fill(Theme.surfaceRaised)
                    .overlay(RoundedRectangle(cornerRadius: 7).stroke(Theme.borderStrong, lineWidth: 1))
                Text("Z")
                    .font(.system(size: 15, weight: .bold, design: .monospaced))
                    .foregroundStyle(Theme.text)
            }
            .frame(width: 30, height: 30)

            Text("Zuse")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Theme.text)
            Spacer()
            StatusDot(color: state.statusDotColor)
        }
        .padding(.horizontal, 2)
    }
}

private struct ActiveTaskRow: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        Button {
        } label: {
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 7) {
                    Text(taskTitle)
                        .font(.system(size: 12.5, weight: .medium))
                        .foregroundStyle(Theme.text)
                        .lineLimit(1)
                    Spacer(minLength: 6)
                    if state.activeJobID != nil || state.status.busy {
                        ProgressView()
                            .controlSize(.mini)
                    }
                }
                Text(taskSubtitle)
                    .font(.system(size: 11))
                    .foregroundStyle(Theme.tertiary)
                    .lineLimit(1)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.active, in: RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }

    private var taskTitle: String {
        if let firstUser = state.messages.first(where: { $0.role == .user }) {
            return firstUser.text.replacingOccurrences(of: "\n", with: " ")
        }
        return "Untitled task"
    }

    private var taskSubtitle: String {
        if state.messages.isEmpty { return "No messages yet" }
        return "\(state.messages.count) messages"
    }
}

private struct SidebarCommand: View {
    let title: String
    let icon: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                Image(systemName: icon)
                    .font(.system(size: 13))
                    .frame(width: 16)
                Text(title)
                    .font(.system(size: 12.5))
                Spacer()
            }
            .foregroundStyle(Theme.secondary)
            .padding(.horizontal, 9)
            .padding(.vertical, 7)
        }
        .buttonStyle(HoverButtonStyle())
    }
}

private struct OpenFileSidebarRow: View {
    @EnvironmentObject var state: AppState
    let file: OpenFile
    let revealContext: () -> Void

    var body: some View {
        Button {
            state.selectedFilePath = file.path
            revealContext()
        } label: {
            HStack(spacing: 8) {
                Image(systemName: file.isDirty ? "circle.fill" : "doc.text")
                    .font(.system(size: file.isDirty ? 7 : 12))
                    .foregroundStyle(file.isDirty ? Theme.warning : Theme.tertiary)
                    .frame(width: 16)
                Text(file.name)
                    .font(.system(size: 12))
                    .foregroundStyle(state.selectedFilePath == file.path ? Theme.text : Theme.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 4)
            }
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
        }
        .buttonStyle(HoverButtonStyle())
    }
}

private struct SidebarFootnote: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
                StatusDot(color: state.statusDotColor)
                Text(state.statusLabel)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Theme.secondary)
                    .lineLimit(1)
            }
            if !state.status.model.isEmpty {
                Text("\(state.status.provider) / \(state.status.model)")
                    .font(.system(size: 10.5, design: .monospaced))
                    .foregroundStyle(Theme.tertiary)
                    .lineLimit(1)
            }
            Text(state.workingDirectory.lastPathComponent)
                .font(.system(size: 10.5, design: .monospaced))
                .foregroundStyle(Theme.tertiary)
                .lineLimit(1)
        }
        .padding(10)
        .background(Theme.surfaceInset, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border, lineWidth: 1))
    }
}

// MARK: - Header and Stage

private struct ThreadHeader: View {
    @EnvironmentObject var state: AppState
    @Binding var showSidebar: Bool
    @Binding var showContext: Bool

    var body: some View {
        HStack(spacing: 10) {
            Button {
                withAnimation(.easeOut(duration: 0.16)) { showSidebar.toggle() }
            } label: {
                Image(systemName: "sidebar.left")
            }
            .iconOnlyButton()
            .help("Sidebar")

            VStack(alignment: .leading, spacing: 2) {
                Text(headerTitle)
                    .font(.system(size: 13.5, weight: .semibold))
                    .foregroundStyle(Theme.text)
                    .lineLimit(1)
                Text(state.workingDirectory.path)
                    .font(.system(size: 10.5, design: .monospaced))
                    .foregroundStyle(Theme.tertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }

            Spacer()

            HeaderPill(text: state.statusLabel, color: state.statusDotColor)

            Button {
                state.openInBrowser()
            } label: {
                Image(systemName: "arrow.up.right")
            }
            .iconOnlyButton()
            .help("Open Web")

            Button {
                withAnimation(.easeOut(duration: 0.16)) { showContext.toggle() }
            } label: {
                Image(systemName: "sidebar.trailing")
            }
            .iconOnlyButton()
            .help("Context")
        }
        .padding(.leading, 10)
        .padding(.trailing, 12)
        .padding(.top, 10)
        .padding(.bottom, 9)
        .background(Theme.windowBackground)
    }

    private var headerTitle: String {
        if let firstUser = state.messages.first(where: { $0.role == .user }) {
            return firstUser.text.replacingOccurrences(of: "\n", with: " ")
        }
        return "New task"
    }
}

private struct HeaderPill: View {
    let text: String
    let color: Color

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(color)
                .frame(width: 6, height: 6)
            Text(text)
                .font(.system(size: 11, weight: .medium))
                .lineLimit(1)
        }
        .foregroundStyle(Theme.secondary)
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(Theme.surface, in: Capsule())
        .overlay(Capsule().stroke(Theme.border, lineWidth: 1))
    }
}

private struct ThreadStage: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        Group {
            switch state.phase {
            case .launching:
                LoadingView()
            case .failed(let message):
                FailureView(message: message)
            case .connected:
                HStack(spacing: 0) {
                    Spacer(minLength: 24)
                    ChatView()
                        .frame(maxWidth: 820)
                    Spacer(minLength: 24)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.windowBackground)
    }
}

private struct LoadingView: View {
    var body: some View {
        VStack(spacing: 13) {
            ProgressView()
                .controlSize(.small)
            Text("Starting Zuse")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(Theme.text)
            Text("Connecting to the local backend")
                .font(.system(size: 12))
                .foregroundStyle(Theme.tertiary)
        }
    }
}

private struct FailureView: View {
    let message: String

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 30, weight: .medium))
                .foregroundStyle(Theme.danger)
            Text("Zuse could not start")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Theme.text)
            Text(message)
                .font(.system(size: 12, design: .monospaced))
                .foregroundStyle(Theme.secondary)
                .multilineTextAlignment(.center)
                .textSelection(.enabled)
                .frame(maxWidth: 560)
        }
        .padding(24)
    }
}

// MARK: - Context Drawer

private struct ContextDrawer: View {
    @EnvironmentObject var state: AppState
    @Binding var selectedTab: ContextTab

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Text("Context")
                    .font(.system(size: 13.5, weight: .semibold))
                    .foregroundStyle(Theme.text)
                Spacer()
                if state.sseConnected {
                    HeaderPill(text: "live", color: Theme.success)
                }
            }
            .padding(.top, 28)
            .padding(.horizontal, 13)
            .padding(.bottom, 10)

            Picker("", selection: $selectedTab) {
                ForEach(ContextTab.allCases) { tab in
                    Text(tab.rawValue).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 12)
            .padding(.bottom, 10)

            DividerLine(axis: .horizontal)

            switch selectedTab {
            case .files:
                FilesContext()
            case .agents:
                CrewDashboardView()
            case .terminal:
                BottomPanelView()
            }
        }
        .background(Theme.sidebar)
    }
}

private struct FilesContext: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    VStack(alignment: .leading, spacing: 7) {
                        SectionLabel(title: "Root")
                        Text(state.workingDirectory.path)
                            .font(.system(size: 10.5, design: .monospaced))
                            .foregroundStyle(Theme.tertiary)
                            .lineLimit(2)
                            .textSelection(.enabled)
                    }

                    VStack(alignment: .leading, spacing: 7) {
                        SectionLabel(title: "Files")
                        FileTreeView(root: state.workingDirectory)
                    }
                }
                .padding(12)
            }

            if let path = state.selectedFilePath,
               let file = state.openFiles.first(where: { $0.path == path }) {
                DividerLine(axis: .horizontal)
                EditorPreview(file: file)
                    .frame(minHeight: 220, idealHeight: 300, maxHeight: 360)
            }
        }
    }
}

private struct EditorPreview: View {
    @EnvironmentObject var state: AppState
    let file: OpenFile

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Image(systemName: file.isDirty ? "circle.fill" : "doc.text")
                    .font(.system(size: file.isDirty ? 7 : 12))
                    .foregroundStyle(file.isDirty ? Theme.warning : Theme.tertiary)
                    .frame(width: 15)
                Text(file.name)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Theme.text)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer()
                Button {
                    state.saveSelectedFile()
                } label: {
                    Image(systemName: "square.and.arrow.down")
                }
                .iconOnlyButton()
                .disabled(!file.isDirty)
                .opacity(file.isDirty ? 1 : 0.45)
                .help("Save")
                Button {
                    state.closeFile(file.path)
                } label: {
                    Image(systemName: "xmark")
                }
                .iconOnlyButton()
                .help("Close")
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            DividerLine(axis: .horizontal)
            CodeEditorView(
                text: state.contentBinding(for: file.path),
                language: file.language,
                editable: file.editable
            )
            .id(file.path)
        }
        .background(Theme.surfaceInset)
    }
}

// MARK: - Shared State Labels

private extension AppState {
    var statusDotColor: Color {
        switch phase {
        case .failed:
            return Theme.danger
        case .launching:
            return Theme.warning
        case .connected:
            if !status.error.isEmpty { return Theme.danger }
            if status.busy || activeJobID != nil { return Theme.warning }
            return status.ready ? Theme.success : Theme.tertiary
        }
    }

    var statusLabel: String {
        switch phase {
        case .failed:
            return "Error"
        case .launching:
            return "Starting"
        case .connected:
            if !status.error.isEmpty { return "Error" }
            if status.busy || activeJobID != nil { return "Working" }
            return status.ready ? "Ready" : "Loading"
        }
    }
}

struct SidebarButtonStyle: ButtonStyle {
    @State private var hovering = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(
                RoundedRectangle(cornerRadius: 7)
                    .fill(hovering || configuration.isPressed ? Theme.hover : .clear)
            )
            .onHover { hovering = $0 }
    }
}
