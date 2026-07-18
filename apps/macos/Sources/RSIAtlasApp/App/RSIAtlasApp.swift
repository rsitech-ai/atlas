import AppKit
import SwiftUI

@main
struct RSIAtlasApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("RSI Atlas") {
            ContentView()
                .frame(minWidth: 860, minHeight: 600)
                .modifier(QAPresentationModifier(options: .current))
        }
        .defaultSize(width: 1120, height: 760)
        .windowResizability(.contentMinSize)
    }
}
private final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        let qaOptions = QAPresentationOptions.current
        if qaOptions.increaseContrast {
            NSApp.appearance = NSAppearance(
                named: qaOptions.forceLight
                    ? .accessibilityHighContrastAqua
                    : .accessibilityHighContrastDarkAqua
            )
        } else if qaOptions.forceLight {
            NSApp.appearance = NSAppearance(named: .aqua)
        }
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}
