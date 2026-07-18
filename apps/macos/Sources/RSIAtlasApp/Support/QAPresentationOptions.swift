import SwiftUI

struct QAPresentationOptions: Equatable {
    let forceLight: Bool
    let increaseContrast: Bool
    let useLargeText: Bool
    let reduceMotion: Bool
    let compactWindow: Bool

    static func parse(arguments: [String]) -> Self {
        let values = Set(arguments)
        return Self(
            forceLight: values.contains("--qa-light"),
            increaseContrast: values.contains("--qa-increase-contrast"),
            useLargeText: values.contains("--qa-large-text"),
            reduceMotion: values.contains("--qa-reduce-motion"),
            compactWindow: values.contains("--qa-compact-window")
        )
    }

    static var current: Self {
        #if DEBUG
        parse(arguments: ProcessInfo.processInfo.arguments)
        #else
        Self(
            forceLight: false,
            increaseContrast: false,
            useLargeText: false,
            reduceMotion: false,
            compactWindow: false
        )
        #endif
    }
}

struct QAPresentationModifier: ViewModifier {
    let options: QAPresentationOptions

    func body(content: Content) -> some View {
        content
            .transformEnvironment(\.dynamicTypeSize) { value in
                if options.useLargeText {
                    value = .accessibility3
                }
            }
            .transaction { transaction in
                if options.reduceMotion {
                    transaction.animation = nil
                    transaction.disablesAnimations = true
                }
            }
    }
}
