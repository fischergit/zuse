import SwiftUI

struct ChatView: View {
    @EnvironmentObject var state: AppState
    @FocusState private var composerFocused: Bool

    var body: some View {
        VStack(spacing: 0) {
            transcript
            ComposerView(composerFocused: $composerFocused)
        }
        .onAppear { composerFocused = true }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 24) {
                    if state.messages.isEmpty {
                        EmptyThreadView()
                            .padding(.top, 150)
                    }

                    ForEach(state.messages) { message in
                        MessageRow(message: message)
                            .id(message.id)
                    }
                }
                .padding(.horizontal, 26)
                .padding(.top, 28)
                .padding(.bottom, 18)
            }
            .onChange(of: state.messages.count) {
                scrollToBottom(proxy)
            }
            .onChange(of: state.messages.last?.text ?? "") {
                scrollToBottom(proxy)
            }
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        if let last = state.messages.last {
            proxy.scrollTo(last.id, anchor: .bottom)
        }
    }
}

private struct EmptyThreadView: View {
    @EnvironmentObject var state: AppState

    var body: some View {
        VStack(spacing: 12) {
            Text("What are we working on?")
                .font(.system(size: 24, weight: .semibold))
                .foregroundStyle(Theme.text)
            Text(statusText)
                .font(.system(size: 12))
                .foregroundStyle(Theme.tertiary)
        }
        .frame(maxWidth: .infinity)
    }

    private var statusText: String {
        if !state.status.error.isEmpty { return state.status.error }
        if state.status.ready { return "Zuse is ready" }
        return "Zuse is loading"
    }
}

private struct ComposerView: View {
    @EnvironmentObject var state: AppState
    var composerFocused: FocusState<Bool>.Binding

    var body: some View {
        VStack(spacing: 8) {
            VStack(spacing: 0) {
                TextField("Ask Zuse to code, inspect, or run something", text: $state.composer, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.system(size: 14))
                    .foregroundStyle(Theme.text)
                    .lineLimit(1...8)
                    .focused(composerFocused)
                    .onSubmit(state.send)
                    .padding(.horizontal, 14)
                    .padding(.top, 12)
                    .padding(.bottom, 10)

                HStack(spacing: 8) {
                    ComposerChip(icon: "plus", text: "Add")
                    ComposerChip(icon: "folder", text: state.workingDirectory.lastPathComponent)
                    if !state.status.model.isEmpty {
                        ComposerChip(icon: "cpu", text: state.status.model)
                    }

                    Spacer()

                    Button(action: state.send) {
                        Image(systemName: "arrow.up")
                            .font(.system(size: 13, weight: .bold))
                            .foregroundStyle(canSend ? Theme.windowBackground : Theme.tertiary)
                            .frame(width: 30, height: 30)
                            .background(Circle().fill(canSend ? Theme.accent : Theme.surfaceRaised))
                    }
                    .buttonStyle(.plain)
                    .disabled(!canSend)
                    .help("Send")
                }
                .padding(.leading, 10)
                .padding(.trailing, 8)
                .padding(.bottom, 8)
            }
            .background(Theme.composer, in: RoundedRectangle(cornerRadius: 14))
            .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.borderStrong, lineWidth: 1))
            .shadow(color: .black.opacity(0.22), radius: 18, y: 8)

            HStack {
                if state.activeJobID != nil || state.status.busy {
                    Text("Working")
                        .foregroundStyle(Theme.warning)
                } else {
                    Text(state.status.ready ? "Ready" : "Loading")
                }
                Spacer()
            }
            .font(.system(size: 11, design: .monospaced))
            .foregroundStyle(Theme.tertiary)
        }
        .padding(.horizontal, 26)
        .padding(.top, 10)
        .padding(.bottom, 20)
        .background(Theme.windowBackground)
    }

    private var canSend: Bool {
        state.status.ready
            && state.activeJobID == nil
            && !state.composer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

private struct ComposerChip: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: icon)
                .font(.system(size: 10.5, weight: .medium))
            Text(text)
                .font(.system(size: 11.5, weight: .medium))
                .lineLimit(1)
        }
        .foregroundStyle(Theme.secondary)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .background(Theme.surface, in: Capsule())
        .overlay(Capsule().stroke(Theme.border, lineWidth: 1))
    }
}

private struct MessageRow: View {
    let message: ChatMessage

    var body: some View {
        switch message.role {
        case .user:
            VStack(alignment: .trailing, spacing: 6) {
                Text("You")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Theme.tertiary)
                Text(message.text)
                    .font(.system(size: 14))
                    .foregroundStyle(Theme.text)
                    .textSelection(.enabled)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .background(Theme.userBubble, in: RoundedRectangle(cornerRadius: 12))
                    .overlay(RoundedRectangle(cornerRadius: 12).stroke(Theme.border, lineWidth: 1))
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.leading, 90)

        case .assistant:
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 7) {
                    ZuseGlyph()
                    Text("Zuse")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(Theme.tertiary)
                    if message.isStreaming {
                        ProgressView()
                            .controlSize(.mini)
                    }
                }

                if message.text.isEmpty && message.isStreaming {
                    Text("Working")
                        .font(.system(size: 14))
                        .foregroundStyle(Theme.secondary)
                } else {
                    AssistantText(text: message.text)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

        case .system:
            HStack {
                Spacer(minLength: 30)
                Text(message.text)
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.tertiary)
                    .textSelection(.enabled)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .background(Theme.surfaceInset, in: RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border, lineWidth: 1))
                Spacer(minLength: 30)
            }
        }
    }
}

private struct ZuseGlyph: View {
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 4)
                .fill(Theme.surfaceRaised)
            Text("Z")
                .font(.system(size: 9.5, weight: .bold, design: .monospaced))
                .foregroundStyle(Theme.text)
        }
        .frame(width: 18, height: 18)
        .overlay(RoundedRectangle(cornerRadius: 4).stroke(Theme.border, lineWidth: 1))
    }
}

struct AssistantText: View {
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 11) {
            ForEach(Array(segments.enumerated()), id: \.offset) { _, segment in
                if segment.isCode {
                    Text(segment.text)
                        .font(.system(size: 12.5, design: .monospaced))
                        .foregroundStyle(Theme.text)
                        .textSelection(.enabled)
                        .padding(11)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Theme.codeBlock, in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border, lineWidth: 1))
                } else {
                    Text(inlineMarkdown(segment.text))
                        .font(.system(size: 14))
                        .foregroundStyle(Theme.text)
                        .lineSpacing(3.5)
                        .textSelection(.enabled)
                }
            }
        }
    }

    private struct Segment {
        let text: String
        let isCode: Bool
    }

    private var segments: [Segment] {
        var out: [Segment] = []
        var isCode = false
        var current = ""

        for line in text.components(separatedBy: "\n") {
            if line.trimmingCharacters(in: .whitespaces).hasPrefix("```") {
                let trimmed = current.trimmingCharacters(in: .newlines)
                if !trimmed.isEmpty {
                    out.append(Segment(text: trimmed, isCode: isCode))
                }
                current = ""
                isCode.toggle()
                continue
            }
            current += line + "\n"
        }

        let trimmed = current.trimmingCharacters(in: .newlines)
        if !trimmed.isEmpty {
            out.append(Segment(text: trimmed, isCode: isCode))
        }
        return out
    }

    private func inlineMarkdown(_ string: String) -> AttributedString {
        (try? AttributedString(
            markdown: string,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        )) ?? AttributedString(string)
    }
}
