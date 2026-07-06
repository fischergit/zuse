import AppKit
import SwiftUI

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity
        )
    }
}

extension NSColor {
    convenience init(hex: UInt32) {
        self.init(
            srgbRed: CGFloat((hex >> 16) & 0xFF) / 255,
            green: CGFloat((hex >> 8) & 0xFF) / 255,
            blue: CGFloat(hex & 0xFF) / 255,
            alpha: 1
        )
    }
}

enum Theme {
    static let windowBackground = Color(hex: 0x0D0D0D)
    static let sidebar = Color(hex: 0x171717)
    static let surface = Color(hex: 0x1F1F1F)
    static let surfaceRaised = Color(hex: 0x262626)
    static let surfaceInset = Color(hex: 0x121212)
    static let hover = Color.white.opacity(0.055)
    static let active = Color.white.opacity(0.085)
    static let border = Color.white.opacity(0.085)
    static let borderStrong = Color.white.opacity(0.14)

    static let text = Color(hex: 0xECECEC)
    static let secondary = Color(hex: 0xB4B4B4)
    static let tertiary = Color(hex: 0x7C7C7C)
    static let accent = Color(hex: 0xF2F2F2)
    static let success = Color(hex: 0x34D399)
    static let warning = Color(hex: 0xFBBF24)
    static let danger = Color(hex: 0xF87171)

    static let userBubble = Color(hex: 0x2A2A2A)
    static let codeBlock = Color(hex: 0x151515)
    static let composer = Color(hex: 0x1A1A1A)

    static let editorBackground = NSColor(hex: 0x121212)
    static let editorForeground = NSColor(hex: 0xECECEC)
}

struct CodexSurface: ViewModifier {
    var cornerRadius: CGFloat = 8
    var fill: Color = Theme.surface
    var border: Color = Theme.border

    func body(content: Content) -> some View {
        content
            .background(fill, in: RoundedRectangle(cornerRadius: cornerRadius))
            .overlay(RoundedRectangle(cornerRadius: cornerRadius).stroke(border, lineWidth: 1))
    }
}

struct HoverButtonStyle: ButtonStyle {
    var cornerRadius: CGFloat = 7
    @State private var isHovering = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(
                RoundedRectangle(cornerRadius: cornerRadius)
                    .fill(configuration.isPressed || isHovering ? Theme.hover : .clear)
            )
            .contentShape(RoundedRectangle(cornerRadius: cornerRadius))
            .onHover { isHovering = $0 }
    }
}

struct IconOnlyButtonStyle: ButtonStyle {
    @State private var isHovering = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 13, weight: .medium))
            .foregroundStyle(Theme.secondary)
            .frame(width: 30, height: 30)
            .background(
                RoundedRectangle(cornerRadius: 7)
                    .fill(configuration.isPressed || isHovering ? Theme.hover : .clear)
            )
            .contentShape(RoundedRectangle(cornerRadius: 7))
            .onHover { isHovering = $0 }
    }
}

extension View {
    func codexSurface(
        cornerRadius: CGFloat = 8,
        fill: Color = Theme.surface,
        border: Color = Theme.border
    ) -> some View {
        modifier(CodexSurface(cornerRadius: cornerRadius, fill: fill, border: border))
    }

    func panelCard(cornerRadius: CGFloat = 8) -> some View {
        codexSurface(cornerRadius: cornerRadius)
    }

    func iconOnlyButton() -> some View {
        buttonStyle(IconOnlyButtonStyle())
    }
}

struct SectionLabel: View {
    let title: String

    var body: some View {
        Text(title.uppercased())
            .font(.system(size: 10, weight: .semibold, design: .monospaced))
            .foregroundStyle(Theme.tertiary)
            .tracking(0)
    }
}

struct StatusDot: View {
    let color: Color

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 7, height: 7)
            .overlay(Circle().stroke(color.opacity(0.35), lineWidth: 3))
            .frame(width: 13, height: 13)
    }
}

struct VisualEffectBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .underWindowBackground
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}
