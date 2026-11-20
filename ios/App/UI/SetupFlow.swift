import AVFoundation
import Combine
import EchoCore
import Speech
import SwiftUI

struct SetupFlow: View {
    @EnvironmentObject private var router: Router

    private var steps: [Router.SetupStep] { Router.SetupStep.allCases }

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                content
                    .padding(.horizontal, Theme.gutter)
                    .padding(.top, 24)
                    .padding(.bottom, 32)
                    .frame(maxWidth: 560)
                    .frame(maxWidth: .infinity)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
        .background(Theme.background.ignoresSafeArea())
    }

    private var header: some View {
        HStack(spacing: 12) {
            Button {
                go(-1)
            } label: {
                Image(systemName: "chevron.left")
                    .font(.system(size: 18, weight: .semibold))
                    .frame(width: 44, height: 44)
                    .background(Circle().fill(Theme.surface))
            }
            .opacity(router.setupStep == .welcome ? 0 : 1)
            .disabled(router.setupStep == .welcome)
            .accessibilityLabel("Back")

            HStack(spacing: 6) {
                ForEach(steps, id: \.self) { step in
                    Capsule()
                        .fill(step.rawValue <= router.setupStep.rawValue ? Theme.accent : Theme.border)
                        .frame(height: 4)
                }
            }
            .accessibilityElement()
            .accessibilityLabel("Step \(router.setupStep.rawValue + 1) of \(steps.count)")

            Button("Skip") { go(1) }
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(Theme.subtext)
                .frame(minWidth: 44, minHeight: 44)
                .opacity(canSkip ? 1 : 0)
                .disabled(!canSkip)
        }
        .foregroundStyle(Theme.text)
        .padding(.horizontal, 12)
        .padding(.top, 6)
    }

    private var canSkip: Bool {
        router.setupStep != .welcome && router.setupStep != .account
    }

    @ViewBuilder
    private var content: some View {
        switch router.setupStep {
        case .welcome: WelcomeStep { go(1) }
        case .microphone: MicrophoneStep { go(1) }
        case .keyboard: KeyboardStep { go(1) }
        case .model: ModelStep { go(1) }
        case .tryIt: TryItStep { go(1) }
        case .style: StyleStep { go(1) }
        case .account: AccountStep { router.finishSetup() }
        }
    }

    private func go(_ delta: Int) {
        let next = router.setupStep.rawValue + delta
        if next >= steps.count { router.finishSetup(); return }
        guard let step = Router.SetupStep(rawValue: max(0, next)) else { return }
        withAnimation(.easeInOut(duration: 0.2)) { router.setupStep = step }
    }
}

// MARK: Steps

private struct WelcomeStep: View {
    let next: () -> Void

    var body: some View {
        VStack(spacing: 28) {
            Image("EchoMark")
                .resizable()
                .scaledToFit()
                .frame(maxWidth: 200)
                .padding(.top, 30)
                .accessibilityHidden(true)
            DisplayTitle(lead: "Talk, and it ", accent: "types", trail: ". In any app.")
            Text("Echo turns your voice into clean, punctuated text in Messages, Mail, WhatsApp, Notes and everything else, as fast as you can speak.")
                .font(.system(size: 17))
                .foregroundStyle(Theme.subtext)
                .multilineTextAlignment(.center)
            VStack(alignment: .leading, spacing: 14) {
                Feature(icon: "bolt.fill", text: "Text appears the moment you stop talking")
                Feature(icon: "lock.fill", text: "Speech is turned into text on your iPhone")
                Feature(icon: "wifi.slash", text: "Works offline once set up")
            }
            .padding(.vertical, 8)
            Button("Set up Echo", action: next).buttonStyle(PrimaryButtonStyle())
            Text("Takes about a minute.")
                .font(.footnote)
                .foregroundStyle(Theme.subtext)
        }
    }
}

private struct Feature: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(Theme.accent)
                .frame(width: 34, height: 34)
                .background(Circle().fill(Theme.accentDim))
            Text(text)
                .font(.system(size: 16))
                .foregroundStyle(Theme.text)
            Spacer(minLength: 0)
        }
    }
}

private struct MicrophoneStep: View {
    let next: () -> Void
    @State private var permission = AVAudioApplication.shared.recordPermission

    var body: some View {
        VStack(spacing: 24) {
            StepIcon(name: "mic.fill")
            DisplayTitle(lead: "Let Echo ", accent: "hear you")
            Text("Echo uses the microphone only while you dictate. The orange dot at the top of the screen shows when it's on.")
                .stepBody()
            switch permission {
            case .granted:
                Label("Microphone allowed", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Theme.success)
                    .font(.system(size: 17, weight: .semibold))
                Button("Continue", action: next).buttonStyle(PrimaryButtonStyle())
            case .denied:
                Text("The microphone is turned off for Echo. Turn it on in Settings, then come back.")
                    .stepBody()
                Button("Open Settings") { openAppSettings() }.buttonStyle(PrimaryButtonStyle())
                Button("Continue anyway", action: next).buttonStyle(SecondaryButtonStyle())
            default:
                Button("Allow microphone") {
                    AVAudioApplication.requestRecordPermission { granted in
                        // Apple's recogniser (the fallback engine) may need its
                        // own permission, and iOS can only ask in the foreground.
                        SFSpeechRecognizer.requestAuthorization { _ in
                            Task { @MainActor in
                                permission = granted ? .granted : .denied
                                if granted { next() }
                            }
                        }
                    }
                }
                .buttonStyle(PrimaryButtonStyle())
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)) { _ in
            permission = AVAudioApplication.shared.recordPermission
        }
    }
}

private struct KeyboardStep: View {
    let next: () -> Void
    @EnvironmentObject private var router: Router

    var body: some View {
        VStack(spacing: 22) {
            StepIcon(name: "keyboard.fill")
            DisplayTitle(lead: "Add the ", accent: "Echo keyboard")
            Text("Dictate anywhere you can type. In Settings:")
                .stepBody()
            VStack(alignment: .leading, spacing: 0) {
                Instruction(number: 1, text: "Tap **Keyboards**")
                Divider().overlay(Theme.border)
                Instruction(number: 2, text: "Turn on **Echo**")
                Divider().overlay(Theme.border)
                Instruction(number: 3, text: "Turn on **Allow Full Access**, then tap **Allow**")
                Divider().overlay(Theme.border)
                Instruction(number: 4, text: "Come back to Echo with **◀ Echo** at the top left")
            }
            .background(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous).fill(Theme.surface))

            DisclosureGroup {
                Text("Full Access lets the Echo keyboard pass your words between the keyboard and the Echo app, where speech is turned into text. iOS shows the same warning for every keyboard that asks for it. Echo never records what you type on the keyboard and never sends your keystrokes anywhere.")
                    .font(.system(size: 15))
                    .foregroundStyle(Theme.subtext)
                    .padding(.top, 8)
            } label: {
                Text("Why does Echo need Full Access?")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.text)
            }
            .tint(Theme.subtext)

            if router.keyboardSeen {
                Label("Echo keyboard is on", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Theme.success)
                    .font(.system(size: 17, weight: .semibold))
                Button("Continue", action: next).buttonStyle(PrimaryButtonStyle())
            } else {
                Button("Open Settings") { openAppSettings() }.buttonStyle(PrimaryButtonStyle())
                Button("I've done this", action: next).buttonStyle(SecondaryButtonStyle())
            }
        }
    }
}

private struct ModelStep: View {
    let next: () -> Void
    @EnvironmentObject private var model: ModelStore

    var body: some View {
        VStack(spacing: 24) {
            StepIcon(name: "waveform")
            DisplayTitle(lead: "Download the ", accent: "Echo voice model")
            Text("The same speech model as Echo on your PC: fast, accurate and private, because it runs on your iPhone. It's about 500 MB and downloads once.")
                .stepBody()
            switch model.state {
            case .ready:
                Label("Model ready", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Theme.success)
                    .font(.system(size: 17, weight: .semibold))
                Button("Continue", action: next).buttonStyle(PrimaryButtonStyle())
            case .downloading(let fraction):
                VStack(spacing: 8) {
                    ProgressView(value: fraction)
                        .tint(Theme.accent)
                    Text("\(Int(fraction * 100))%  ·  You can carry on while it downloads")
                        .font(.footnote)
                        .foregroundStyle(Theme.subtext)
                }
                Button("Continue", action: next).buttonStyle(PrimaryButtonStyle())
            case .failed(let why):
                Text(why).foregroundStyle(Theme.error).font(.system(size: 15))
                Button("Try again") { model.download() }.buttonStyle(PrimaryButtonStyle())
                Button("Later", action: next).buttonStyle(SecondaryButtonStyle())
            case .notDownloaded:
                if model.onCellular {
                    Label("You're on mobile data", systemImage: "antenna.radiowaves.left.and.right")
                        .font(.footnote)
                        .foregroundStyle(Theme.subtext)
                }
                Button("Download") { model.download() }.buttonStyle(PrimaryButtonStyle())
                Button("Later", action: next).buttonStyle(SecondaryButtonStyle())
                Text("Until it's downloaded, Echo uses Apple's on-device speech recognition.")
                    .font(.footnote)
                    .foregroundStyle(Theme.subtext)
                    .multilineTextAlignment(.center)
            }
        }
    }
}

private struct TryItStep: View {
    let next: () -> Void
    @EnvironmentObject private var router: Router
    @EnvironmentObject private var history: HistoryStore
    @State private var text = ""
    @FocusState private var focused: Bool
    @State private var startCount = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            DisplayTitle(lead: "Say anything, and watch it ", accent: "appear")
                .frame(maxWidth: .infinity)
            VStack(alignment: .leading, spacing: 12) {
                Instruction(number: 1, text: "Tap the box below")
                Instruction(number: 2, text: "Hold \(Image(systemName: "globe")) and choose **Echo**")
                Instruction(number: 3, text: "Tap the mic, talk, then tap ✓")
            }
            TextField("Say something!", text: $text, axis: .vertical)
                .focused($focused)
                .lineLimit(4...8)
                .font(.system(size: 18))
                .padding(16)
                .background(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous).fill(Theme.surface))
                .overlay(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    .stroke(focused ? Theme.accent : Theme.border, lineWidth: 1.5))
            if history.entries.count > startCount {
                Label("That's it. Echo works in every app the same way.", systemImage: "sparkles")
                    .foregroundStyle(Theme.success)
                    .font(.system(size: 16, weight: .semibold))
            }
            Button(history.entries.count > startCount ? "Continue" : "Skip for now", action: next)
                .buttonStyle(PrimaryButtonStyle())
        }
        .onAppear {
            startCount = history.entries.count
            focused = true
        }
    }
}

private struct StyleStep: View {
    let next: () -> Void
    @State private var selected = SharedSettings.shared.style

    var body: some View {
        VStack(spacing: 18) {
            DisplayTitle(lead: "Pick your ", accent: "default style")
            Text("Echo writes every dictation this way. You can change it any time from the ☰ button on the keyboard.")
                .stepBody()
            ForEach(DictationStyle.allCases) { style in
                Button {
                    selected = style
                    SharedSettings.shared.style = style
                } label: {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(style.title).font(.system(size: 20, weight: .semibold))
                        Text(style.subtitle).font(.system(size: 15)).foregroundStyle(Theme.subtext)
                        if style == selected {
                            Text(style.example)
                                .font(.system(size: 15))
                                .padding(12)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(RoundedRectangle(cornerRadius: 10).fill(Theme.surfaceRaised))
                                .padding(.top, 4)
                        }
                    }
                    .foregroundStyle(Theme.text)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(18)
                    .background(
                        RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                            .fill(style == selected ? Theme.accentDim : Theme.surface)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                            .stroke(style == selected ? Theme.accent : Theme.border, lineWidth: style == selected ? 2 : 1)
                    )
                }
                .accessibilityAddTraits(style == selected ? .isSelected : [])
            }
            Button("Next", action: next).buttonStyle(PrimaryButtonStyle()).padding(.top, 8)
        }
        .animation(.easeOut(duration: 0.15), value: selected)
    }
}

private struct AccountStep: View {
    let finish: () -> Void
    @EnvironmentObject private var account: AccountStore
    @State private var showSignIn = false

    var body: some View {
        VStack(spacing: 24) {
            StepIcon(name: "person.crop.circle.fill")
            DisplayTitle(lead: "Use your ", accent: "BrightLink account")
            Text("Optional. Signing in brings your vocabulary and snippets from Echo on your PC, the sign-off name for emails, and AI refine.")
                .stepBody()
            if account.isSignedIn {
                Label("Signed in as \(account.email ?? "you")", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Theme.success)
                    .font(.system(size: 16, weight: .semibold))
                Button("Start using Echo", action: finish).buttonStyle(PrimaryButtonStyle())
            } else {
                Button("Sign in") { showSignIn = true }.buttonStyle(PrimaryButtonStyle())
                Button("Not now", action: finish).buttonStyle(SecondaryButtonStyle())
            }
        }
        .sheet(isPresented: $showSignIn) { SignInView() }
    }
}

// MARK: Pieces

private struct StepIcon: View {
    let name: String

    var body: some View {
        Image(systemName: name)
            .font(.system(size: 34, weight: .semibold))
            .foregroundStyle(Theme.accent)
            .frame(width: 84, height: 84)
            .background(Circle().fill(Theme.accentDim))
            .padding(.top, 12)
            .accessibilityHidden(true)
    }
}

struct Instruction: View {
    let number: Int
    let text: LocalizedStringKey

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 14) {
            Text("\(number)")
                .font(.system(size: 14, weight: .bold))
                .foregroundStyle(.black)
                .frame(width: 26, height: 26)
                .background(Circle().fill(Theme.accent))
            Text(text)
                .font(.system(size: 17))
                .foregroundStyle(Theme.text)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.vertical, 12)
        .padding(.horizontal, 14)
    }
}

private extension Text {
    func stepBody() -> some View {
        font(.system(size: 17))
            .foregroundStyle(Theme.subtext)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
    }
}

@MainActor
func openAppSettings() {
    if let url = URL(string: UIApplication.openSettingsURLString) {
        UIApplication.shared.open(url)
    }
}
