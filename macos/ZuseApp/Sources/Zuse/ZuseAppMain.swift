// Entry point. Deliberately NOT named main.swift — SwiftPM treats main.swift
// as a script entry, which conflicts with the @main attribute.
import AppKit
import SwiftUI

final class AppDelegate: NSObject, NSApplicationDelegate {
    static weak var shared: AppDelegate?
    var appState: AppState?

    func applicationDidFinishLaunching(_ notification: Notification) {
        AppDelegate.shared = self
        // When run as a bare SwiftPM binary (swift run, no bundle) the process
        // starts as a background app; promote it so the window shows and focuses.
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationWillTerminate(_ notification: Notification) {
        appState?.shutdown()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

@main
struct ZuseApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var state = AppState()

    var body: some Scene {
        WindowGroup("Zuse") {
            ContentView()
                .environmentObject(state)
                .preferredColorScheme(.dark)   // always dark — the glass look needs it
                .frame(minWidth: 760, minHeight: 520)
                .onAppear {
                    delegate.appState = state
                    state.start()
                }
        }
        .defaultSize(width: 1080, height: 700)
        .windowStyle(.hiddenTitleBar)   // Claude-style seamless window chrome
        .commands {
            CommandMenu("Zuse") {
                Button("Datei speichern") { state.saveSelectedFile() }
                    .keyboardShortcut("s", modifiers: .command)
                Button("Terminal") { state.showConsole.toggle() }
                    .keyboardShortcut("j", modifiers: .command)
                Divider()
                Button("Verlauf löschen") { state.clearConversation() }
                    .keyboardShortcut("k", modifiers: .command)
                Button("Kosten anzeigen") { state.showCost() }
                    .keyboardShortcut("c", modifiers: [.command, .shift])
                Button("Sitzung speichern") { state.saveSession() }
                Button("Im Browser öffnen") { state.openInBrowser() }
            }
        }
    }
}
