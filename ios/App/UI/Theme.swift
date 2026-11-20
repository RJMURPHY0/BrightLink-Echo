import SwiftUI
import UIKit

/// Echo's palette, from the desktop dashboard (app_window.py `C`): near-black
/// surfaces, white text, FTC orange accent. Light mode keeps the same accent
/// on a warm off-white so the app follows the phone's appearance.
enum Theme {
    private static func dynamic(dark: UIColor, light: UIColor) -> Color {
        Color(UIColor { $0.userInterfaceStyle == .dark ? dark : light })
    }

    private static func hex(_ value: UInt32) -> UIColor {
        UIColor(red: CGFloat((value >> 16) & 0xFF) / 255, green: CGFloat((value >> 8) & 0xFF) / 255,
                blue: CGFloat(value & 0xFF) / 255, alpha: 1)
    }

    static let background = dynamic(dark: hex(0x0D0D0D), light: hex(0xF6F5F2))
    static let surface = dynamic(dark: hex(0x1A1A1A), light: hex(0xFFFFFF))
    static let surfaceRaised = dynamic(dark: hex(0x242424), light: hex(0xF0EEE9))
    static let border = dynamic(dark: hex(0x2D2D2D), light: hex(0xE4E1DA))
    static let text = dynamic(dark: hex(0xFFFFFF), light: hex(0x111111))
    /// Desktop subtext #777 fails contrast on near-black at small sizes, so
    /// the phone uses #8C8C8C (the desktop's muted text) in dark mode.
    static let subtext = dynamic(dark: hex(0x8C8C8C), light: hex(0x5F5F5F))
    static let accent = Color(hex(0xF39200))
    static let accentPressed = Color(hex(0xE08200))
    static let accentDim = dynamic(dark: hex(0x3D2600), light: hex(0xFDEBD0))
    static let success = dynamic(dark: hex(0x4ADE80), light: hex(0x15803D))
    static let error = dynamic(dark: hex(0xFF5555), light: hex(0xC62828))

    static let cardRadius: CGFloat = 16
    static let buttonRadius: CGFloat = 14
    static let gutter: CGFloat = 20
}

struct PrimaryButtonStyle: ButtonStyle {
    var enabled = true

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(Color.black)
            .frame(maxWidth: .infinity, minHeight: 54)
            .background(
                RoundedRectangle(cornerRadius: Theme.buttonRadius, style: .continuous)
                    .fill(configuration.isPressed ? Theme.accentPressed : Theme.accent)
            )
            .opacity(enabled ? 1 : 0.4)
            .contentShape(Rectangle())
    }
}

struct SecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(Theme.text)
            .frame(maxWidth: .infinity, minHeight: 54)
            .background(
                RoundedRectangle(cornerRadius: Theme.buttonRadius, style: .continuous)
                    .stroke(Theme.border, lineWidth: 1.5)
                    .background(RoundedRectangle(cornerRadius: Theme.buttonRadius, style: .continuous)
                        .fill(configuration.isPressed ? Theme.surfaceRaised : Theme.surface))
            )
            .contentShape(Rectangle())
    }
}

struct Card<Content: View>: View {
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12, content: content)
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    .fill(Theme.surface)
                    .overlay(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                        .stroke(Theme.border, lineWidth: 1))
            )
    }
}

/// The serif-free display title used on setup screens: large, tight, with an
/// accented phrase.
struct DisplayTitle: View {
    let lead: String
    let accent: String
    var trail: String = ""

    var body: some View {
        (Text(lead).foregroundColor(Theme.text)
         + Text(accent).foregroundColor(Theme.accent)
         + Text(trail).foregroundColor(Theme.text))
            .font(.system(size: 32, weight: .bold, design: .rounded))
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
    }
}
