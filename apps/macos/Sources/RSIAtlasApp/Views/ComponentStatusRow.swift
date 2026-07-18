import RSIAtlasCore
import SwiftUI

struct ComponentStatusRow: View {
    let component: ComponentStatus

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Image(systemName: component.state.systemImage)
                .foregroundStyle(component.state.tint)
                .frame(width: 18)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 4) {
                Text(component.title)
                    .font(.body.weight(.medium))
                Text(component.summary)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 16)

            Text(component.state.rawValue.capitalized)
                .font(.callout.weight(.medium))
                .foregroundStyle(component.state.tint)
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            "\(component.title), \(component.state.rawValue), \(component.summary)"
        )
    }
}
