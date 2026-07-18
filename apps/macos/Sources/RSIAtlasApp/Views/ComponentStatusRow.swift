import RSIAtlasCore
import SwiftUI

struct ComponentStatusRow: View {
    let component: ComponentStatus

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: component.state.systemImage)
                .foregroundStyle(component.state.tint)
                .frame(width: 18)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(component.title)
                        .font(.body.weight(.medium))
                    Spacer(minLength: 12)
                    Text(component.state.rawValue.capitalized)
                        .font(.callout.weight(.medium))
                        .foregroundStyle(component.state.tint)
                }

                Text(component.summary)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                if let remediation = component.remediation {
                    Label(remediation, systemImage: "wrench.adjustable")
                        .font(.callout)
                        .foregroundStyle(.orange)
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityIdentifier(
                            "runtime.remediation.\(component.componentID)"
                        )
                }
            }
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("runtime.component.\(component.componentID)")
        .accessibilityLabel(accessibilityLabel)
    }

    private var accessibilityLabel: String {
        [
            component.title,
            component.state.rawValue,
            component.summary,
            component.remediation,
        ]
        .compactMap { $0 }
        .joined(separator: ", ")
    }
}
