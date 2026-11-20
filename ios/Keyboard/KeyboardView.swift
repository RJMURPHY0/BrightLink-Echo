import EchoCore
import SwiftUI
import UIKit

private enum KeyColors {
    static let key = Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(white: 0.42, alpha: 1) : .white })
    static let special = Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(white: 0.26, alpha: 1) : UIColor(red: 0.68, green: 0.70, blue: 0.74, alpha: 1) })
    static let pressed = Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(white: 0.55, alpha: 1) : UIColor(white: 0.82, alpha: 1) })
    static let text = Color(UIColor.label)
    static let shadow = Color.black.opacity(0.28)
    /// Echo orange (desktop palette accent #f39200).
    static let accent = Color(red: 0xF3 / 255, green: 0x92 / 255, blue: 0x00 / 255)
}

struct KeyboardRootView: View {
    @ObservedObject var model: KeyboardModel

    var body: some View {
        VStack(spacing: 0) {
            EchoBar(model: model)
                .frame(height: KeyboardMetrics.barHeight)
            KeysView(model: model)
                .padding(.horizontal, 3)
                .padding(.bottom, 4)
        }
        .overlay(alignment: .topLeading) {
            if model.showStyleMenu {
                StyleMenu(model: model)
                    .padding(.leading, 8)
                    .padding(.top, KeyboardMetrics.barHeight - 4)
                    .transition(.opacity.combined(with: .scale(scale: 0.96, anchor: .topLeading)))
            }
        }
        .animation(.easeOut(duration: 0.15), value: model.showStyleMenu)
    }
}

// MARK: Echo bar

private struct EchoBar: View {
    @ObservedObject var model: KeyboardModel

    var body: some View {
        HStack(spacing: 10) {
            Button {
                model.showStyleMenu.toggle()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "line.3.horizontal")
                        .font(.system(size: 17, weight: .semibold))
                    Text(model.style.title)
                        .font(.system(size: 14, weight: .medium))
                        .lineLimit(1)
                }
                .foregroundStyle(KeyColors.text)
                .padding(.horizontal, 10)
                .frame(height: 36)
                .contentShape(Rectangle())
            }
            .accessibilityLabel("Writing style: \(model.style.title)")

            Spacer(minLength: 4)

            HStack(spacing: 8) {
                if model.phase == .recording {
                    LevelBars(level: model.level)
                } else if model.phase == .transcribing {
                    ProgressView().controlSize(.small)
                }
                Text(model.statusText)
                    .font(.system(size: 14))
                    .foregroundStyle(model.phase == .failed ? Color.red : Color.secondary)
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)
                    .multilineTextAlignment(.trailing)
            }
            .accessibilityElement(children: .combine)

            if model.phase == .recording {
                Button(action: model.cancelTapped) {
                    Image(systemName: "xmark")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(KeyColors.text)
                        .frame(width: 36, height: 36)
                        .background(Circle().fill(KeyColors.special))
                }
                .accessibilityLabel("Cancel dictation")
            }

            MicButton(phase: model.phase, enabled: model.hasFullAccess, action: model.micTapped)
        }
        .padding(.horizontal, 8)
    }
}

private struct MicButton: View {
    let phase: SessionPhase
    let enabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(phase == .recording ? KeyColors.accent : Color(UIColor.label))
                    .frame(width: 46, height: 46)
                    .shadow(color: KeyColors.shadow, radius: 1, y: 1)
                Image(systemName: icon)
                    .font(.system(size: 19, weight: .semibold))
                    .foregroundStyle(phase == .recording ? Color.white : Color(UIColor.systemBackground))
            }
            .opacity(enabled ? 1 : 0.55)
        }
        .disabled(phase == .transcribing)
        .accessibilityLabel(label)
    }

    private var icon: String {
        switch phase {
        case .recording: return "checkmark"
        case .transcribing: return "ellipsis"
        default: return "mic.fill"
        }
    }

    private var label: String {
        switch phase {
        case .recording: return "Stop and insert text"
        case .transcribing: return "Writing"
        default: return "Start dictation"
        }
    }
}

private struct LevelBars: View {
    let level: Float

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<5, id: \.self) { i in
                let weight: [CGFloat] = [0.5, 0.8, 1, 0.8, 0.5]
                Capsule()
                    .fill(KeyColors.accent)
                    .frame(width: 3, height: 6 + 16 * CGFloat(level) * weight[i])
            }
        }
        .frame(height: 22)
        .animation(.linear(duration: 0.1), value: level)
        .accessibilityHidden(true)
    }
}

private struct StyleMenu: View {
    @ObservedObject var model: KeyboardModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(DictationStyle.allCases) { style in
                Button {
                    model.select(style)
                } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "checkmark")
                            .font(.system(size: 14, weight: .semibold))
                            .opacity(style == model.style ? 1 : 0)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(style.title).font(.system(size: 17))
                            Text(style.subtitle).font(.system(size: 12)).foregroundStyle(.secondary)
                        }
                        Spacer()
                    }
                    .foregroundStyle(KeyColors.text)
                    .padding(.horizontal, 14)
                    .frame(height: 50)
                    .contentShape(Rectangle())
                }
                .accessibilityAddTraits(style == model.style ? .isSelected : [])
            }
        }
        .frame(width: 250)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(.regularMaterial)
                .shadow(color: .black.opacity(0.25), radius: 12, y: 4)
        )
    }
}

// MARK: Keys

private struct KeysView: View {
    @ObservedObject var model: KeyboardModel
    @State private var lastShiftTap: Date?

    private let letters: [[String]] = [
        ["q", "w", "e", "r", "t", "y", "u", "i", "o", "p"],
        ["a", "s", "d", "f", "g", "h", "j", "k", "l"],
        ["z", "x", "c", "v", "b", "n", "m"],
    ]
    private let numbers: [[String]] = [
        ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"],
        ["-", "/", ":", ";", "(", ")", "£", "&", "@", "\""],
        [".", ",", "?", "!", "'"],
    ]
    private let symbols: [[String]] = [
        ["[", "]", "{", "}", "#", "%", "^", "*", "+", "="],
        ["_", "\\", "|", "~", "<", ">", "€", "$", "¥", "•"],
        [".", ",", "?", "!", "'"],
    ]

    var body: some View {
        GeometryReader { geo in
            let unit = (geo.size.width - 9 * 6) / 10
            VStack(spacing: KeyboardMetrics.rowSpacing) {
                let rows = model.page == .letters ? letters : (model.page == .numbers ? numbers : symbols)
                row(rows[0], unit: unit)
                row(rows[1], unit: unit)
                    .padding(.horizontal, model.page == .letters ? unit / 2 + 3 : 0)
                HStack(spacing: 6) {
                    leftModifier(unit: unit)
                    Spacer(minLength: 0)
                    HStack(spacing: 6) {
                        ForEach(rows[2], id: \.self) { key in
                            CharacterKey(label: display(key), width: model.page == .letters ? unit : unit * 1.3) {
                                model.type(key)
                            }
                        }
                    }
                    Spacer(minLength: 0)
                    DeleteKey(width: unit * 1.35, model: model)
                }
                bottomRow(unit: unit)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .padding(.top, 2)
        }
    }

    private func display(_ key: String) -> String {
        model.page == .letters && model.shift != .off ? key.uppercased() : key
    }

    private func row(_ keys: [String], unit: CGFloat) -> some View {
        HStack(spacing: 6) {
            ForEach(keys, id: \.self) { key in
                CharacterKey(label: display(key), width: unit) { model.type(key) }
            }
        }
    }

    @ViewBuilder
    private func leftModifier(unit: CGFloat) -> some View {
        switch model.page {
        case .letters:
            SpecialKey(width: unit * 1.35, highlighted: model.shift != .off) {
                Image(systemName: model.shift == .locked ? "capslock.fill" : (model.shift == .on ? "shift.fill" : "shift"))
            } action: {
                if let last = lastShiftTap, Date().timeIntervalSince(last) < 0.3 {
                    model.lockShift()
                    lastShiftTap = nil
                } else {
                    model.toggleShift()
                    lastShiftTap = Date()
                }
            }
            .accessibilityLabel(model.shift == .locked ? "Caps lock on" : "Shift")
        case .numbers:
            SpecialKey(width: unit * 1.35) { Text("#+=").font(.system(size: 15)) } action: { model.page = .symbols }
        case .symbols:
            SpecialKey(width: unit * 1.35) { Text("123").font(.system(size: 15)) } action: { model.page = .numbers }
        }
    }

    private func bottomRow(unit: CGFloat) -> some View {
        HStack(spacing: 6) {
            SpecialKey(width: unit * 1.35) {
                Text(model.page == .letters ? "123" : "ABC").font(.system(size: 15))
            } action: {
                model.page = model.page == .letters ? .numbers : .letters
            }
            if model.needsGlobe, let controller = model.controller {
                GlobeKey(controller: controller)
                    .frame(width: unit * 1.1, height: KeyboardMetrics.keyHeight)
                    .background(RoundedRectangle(cornerRadius: 6).fill(KeyColors.special))
            }
            Button(action: model.space) {
                Text("space")
                    .font(.system(size: 15))
                    .foregroundStyle(KeyColors.text)
                    .frame(maxWidth: .infinity)
                    .frame(height: KeyboardMetrics.keyHeight)
            }
            .buttonStyle(KeyStyle(fill: KeyColors.key))
            .accessibilityLabel("Space")
            SpecialKey(width: unit * 2.1) {
                Text(model.returnTitle).font(.system(size: 15))
            } action: {
                model.newline()
            }
        }
    }
}

private struct KeyStyle: ButtonStyle {
    let fill: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .background(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(configuration.isPressed ? KeyColors.pressed : fill)
                    .shadow(color: KeyColors.shadow, radius: 0, y: 1)
            )
    }
}

private struct CharacterKey: View {
    let label: String
    let width: CGFloat
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 23))
                .foregroundStyle(KeyColors.text)
                .frame(width: width, height: KeyboardMetrics.keyHeight)
        }
        .buttonStyle(KeyStyle(fill: KeyColors.key))
        .accessibilityLabel(label)
    }
}

private struct SpecialKey<Label: View>: View {
    let width: CGFloat
    var highlighted = false
    @ViewBuilder let label: () -> Label
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            label()
                .foregroundStyle(KeyColors.text)
                .frame(width: width, height: KeyboardMetrics.keyHeight)
        }
        .buttonStyle(KeyStyle(fill: highlighted ? KeyColors.key : KeyColors.special))
    }
}

private struct DeleteKey: View {
    let width: CGFloat
    @ObservedObject var model: KeyboardModel
    @State private var pressing = false

    var body: some View {
        Image(systemName: pressing ? "delete.left.fill" : "delete.left")
            .font(.system(size: 19))
            .foregroundStyle(KeyColors.text)
            .frame(width: width, height: KeyboardMetrics.keyHeight)
            .background(
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(pressing ? KeyColors.key : KeyColors.special)
                    .shadow(color: KeyColors.shadow, radius: 0, y: 1)
            )
            .onLongPressGesture(minimumDuration: 30, maximumDistance: 40, perform: {}, onPressingChanged: { down in
                pressing = down
                if down { model.deleteDown() } else { model.deleteUp() }
            })
            .accessibilityLabel("Delete")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { model.deleteDown(); model.deleteUp() }
    }
}
