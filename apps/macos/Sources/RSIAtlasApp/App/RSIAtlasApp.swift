import AppKit
import RSIAtlasCore
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
        .defaultSize(
            width: QAPresentationOptions.current.compactWindow ? 860 : 1120,
            height: QAPresentationOptions.current.compactWindow ? 600 : 760
        )
        .windowResizability(.contentMinSize)
    }
}
extension Notification.Name {
    static let rsiAtlasEngineReady = Notification.Name("ai.rsitech.RSIAtlas.engineReady")
}

@MainActor
private final class AppDelegate: NSObject, NSApplicationDelegate {
    private let engineSupervisor = LocalEngineSupervisor()
    private var terminationRequested = false

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
        if qaOptions.compactWindow {
            DispatchQueue.main.async {
                NSApp.keyWindow?.setContentSize(NSSize(width: 860, height: 600))
            }
        }
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        startEmbeddedEngineUnlessDevelopment()
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if developmentEngineIsExternal {
            return .terminateNow
        }
        guard !terminationRequested else {
            return .terminateLater
        }
        terminationRequested = true
        Task {
            await engineSupervisor.stop()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    private var developmentEngineIsExternal: Bool {
        let value = ProcessInfo.processInfo.environment["RSI_ATLAS_ALLOW_LOOPBACK_TCP"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return ["1", "true", "yes", "on"].contains(value)
    }

    private func startEmbeddedEngineUnlessDevelopment() {
        guard !developmentEngineIsExternal else { return }
        Task {
            for attempt in 0 ..< 3 {
                do {
                    try await engineSupervisor.startAndWait()
                    NotificationCenter.default.post(name: .rsiAtlasEngineReady, object: nil)
                    return
                } catch {
                    if attempt < 2 {
                        try? await Task.sleep(for: .seconds(2 * (attempt + 1)))
                    }
                }
            }
        }
    }
}
