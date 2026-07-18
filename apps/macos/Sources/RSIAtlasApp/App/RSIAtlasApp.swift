import AppKit
import SwiftUI

@main
struct RSIAtlasApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("RSI Atlas") {
            ContentView()
                .frame(minWidth: 860, minHeight: 600)
        }
        .defaultSize(width: 1120, height: 760)
        .windowResizability(.contentMinSize)
    }
}
private final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}
