import SwiftUI

/// Shown when the keyboard opened Echo to start the mic. iOS gives apps no
/// public way to switch back to the previous app, so this screen points at
/// the system's own "◀ App" link in the top-left corner. Recording has
/// already started; the person keeps talking and taps ✓ on the keyboard.
struct ListeningView: View {
    @EnvironmentObject private var dictation: DictationController
    @State private var nudge = false

    var body: some View {
        ZStack(alignment: .topLeading) {
            Theme.background.ignoresSafeArea()

            BackHint(nudge: nudge)
                .padding(.leading, 10)
                .padding(.top, 2)

            VStack(spacing: 28) {
                Spacer()
                PulsingMic(level: CGFloat(dictation.level), active: dictation.phase == .recording)
                VStack(spacing: 10) {
                    Text(title)
                        .font(.system(size: 28, weight: .bold, design: .rounded))
                        .foregroundStyle(Theme.text)
                    Text(detail)
                        .font(.system(size: 17))
                        .foregroundStyle(Theme.subtext)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, Theme.gutter)
                Spacer()
                VStack(spacing: 12) {
                    if dictation.phase == .recording {
                        Button("Stop here and keep the text in Echo") {
                            dictation.finishRecording()
                        }
                        .buttonStyle(SecondaryButtonStyle())
                    }
                    Button("Done") {
                        dictation.openedFromKeyboard = false
                    }
                    .buttonStyle(PrimaryButtonStyle())
                }
                .padding(.horizontal, Theme.gutter)
                .padding(.bottom, 12)
            }
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) { nudge = true }
        }
    }

    private var title: String {
        switch dictation.phase {
        case .recording: return "Echo is listening"
        case .transcribing: return "Writing it up…"
        case .failed: return "That didn't work"
        default: return "Echo is ready"
        }
    }

    private var detail: String {
        switch dictation.phase {
        case .recording, .ready:
            return "Go back to your app with the ◀ link in the top-left corner and keep talking. Tap ✓ on the Echo keyboard when you're done."
        case .transcribing:
            return "Your text will appear in the app you came from."
        case .failed:
            return dictation.message ?? "Try again from the keyboard."
        case .off:
            return dictation.message ?? "Tap the mic on the Echo keyboard to start."
        }
    }
}

private struct BackHint: View {
    let nudge: Bool

    var body: some View {
        HStack(spacing: 6) {
            Image(systemName: "arrow.up.left")
                .font(.system(size: 20, weight: .bold))
                .offset(x: nudge ? -4 : 2, y: nudge ? -4 : 2)
            Text("Tap here to go back")
                .font(.system(size: 15, weight: .semibold))
        }
        .foregroundStyle(Theme.accent)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Capsule().fill(Theme.accentDim))
        .accessibilityLabel("Go back to your app with the back link in the top-left corner of the screen")
    }
}

struct PulsingMic: View {
    let level: CGFloat
    let active: Bool

    var body: some View {
        ZStack {
            Circle()
                .fill(Theme.accent.opacity(0.18))
                .frame(width: 150 + 60 * (active ? level : 0), height: 150 + 60 * (active ? level : 0))
                .animation(.easeOut(duration: 0.12), value: level)
            Circle()
                .fill(Theme.accent)
                .frame(width: 112, height: 112)
            Image(systemName: "mic.fill")
                .font(.system(size: 44, weight: .semibold))
                .foregroundStyle(.black)
        }
        .frame(height: 220)
        .accessibilityHidden(true)
    }
}
