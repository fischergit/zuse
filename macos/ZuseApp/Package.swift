// swift-tools-version:5.9
// Zuse.app — native macOS client for the local zuse-web backend.
// Built with Swift Package Manager only (no Xcode required): `swift build`,
// then macos/ZuseApp/build-app.sh assembles the .app bundle.
import PackageDescription

let package = Package(
    name: "ZuseApp",
    platforms: [.macOS(.v14)],
    dependencies: [
        // Syntax highlighting (highlight.js via JavaScriptCore) for the editor.
        .package(url: "https://github.com/raspu/Highlightr", from: "2.2.0"),
        // Full terminal emulator with local PTY for the integrated terminal.
        .package(url: "https://github.com/migueldeicaza/SwiftTerm", from: "1.2.0"),
    ],
    targets: [
        .executableTarget(
            name: "Zuse",
            dependencies: [
                "Highlightr",
                .product(name: "SwiftTerm", package: "SwiftTerm"),
            ],
            path: "Sources/Zuse"
        )
    ]
)
