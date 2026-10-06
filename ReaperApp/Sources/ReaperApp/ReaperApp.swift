import SwiftUI
import AppKit

/// A SwiftPM-built GUI app launches as an accessory by default and can't become
/// the key window — so keystrokes never arrive. Force a regular activation policy.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}

@main
struct ReaperApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var engine = EngineClient()

    var body: some Scene {
        WindowGroup("REAPER") {
            ContentView(engine: engine)
        }
        .windowStyle(.hiddenTitleBar)
    }
}
