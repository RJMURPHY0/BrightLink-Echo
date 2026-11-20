import EchoCore
import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var dictation: DictationController
    @EnvironmentObject private var history: HistoryStore
    @EnvironmentObject private var account: AccountStore
    @EnvironmentObject private var model: ModelStore
    @EnvironmentObject private var router: Router
    @State private var showSettings = false
    @State private var style = SharedSettings.shared.style

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if let problem = account.restoreProblem {
                        Banner(icon: "exclamationmark.triangle.fill", text: problem)
                    }
                    if !router.keyboardSeen {
                        Button {
                            router.setupStep = .keyboard
                            router.showingSetup = true
                        } label: {
                            Banner(icon: "keyboard", text: "Finish adding the Echo keyboard to dictate in other apps.", chevron: true)
                        }
                    }
                    SessionCard()
                    ImpactGrid(impact: history.impact())
                    StyleRow(style: $style)
                    RecentList()
                }
                .padding(.horizontal, Theme.gutter)
                .padding(.vertical, 12)
            }
            .background(Theme.background.ignoresSafeArea())
            .navigationTitle("Echo")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showSettings = true
                    } label: {
                        Image(systemName: "gearshape")
                    }
                    .accessibilityLabel("Settings")
                }
            }
            .sheet(isPresented: $showSettings) { SettingsView() }
            .navigationDestination(for: HistoryEntry.self) { HistoryDetailView(entry: $0) }
        }
        .onAppear { style = SharedSettings.shared.style }
    }
}

struct Banner: View {
    let icon: String
    let text: String
    var chevron = false

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon).foregroundStyle(Theme.accent)
            Text(text)
                .font(.system(size: 15))
                .foregroundStyle(Theme.text)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            if chevron { Image(systemName: "chevron.right").foregroundStyle(Theme.subtext) }
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Theme.accentDim))
    }
}

private struct SessionCard: View {
    @EnvironmentObject private var dictation: DictationController

    var body: some View {
        Card {
            HStack(spacing: 10) {
                Circle()
                    .fill(dotColor)
                    .frame(width: 10, height: 10)
                Text(statusTitle)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Theme.text)
                Spacer()
                if let ends = dictation.sessionEndsAt, dictation.phase != .off {
                    Text(timerInterval: Date()...max(ends, Date()), countsDown: true)
                        .font(.system(size: 15).monospacedDigit())
                        .foregroundStyle(Theme.subtext)
                        .accessibilityLabel("Mic stays ready until \(ends.formatted(date: .omitted, time: .shortened))")
                }
            }
            Text(statusDetail)
                .font(.system(size: 15))
                .foregroundStyle(Theme.subtext)
                .fixedSize(horizontal: false, vertical: true)
            if dictation.phase == .off {
                Button("Turn on Echo") { dictation.startSession() }
                    .buttonStyle(PrimaryButtonStyle())
            } else {
                HStack(spacing: 10) {
                    if dictation.phase == .recording {
                        Button("Stop") { dictation.finishRecording() }
                            .buttonStyle(PrimaryButtonStyle())
                    } else {
                        Button("Dictate here") { dictation.beginRecording() }
                            .buttonStyle(PrimaryButtonStyle(enabled: dictation.phase == .ready))
                            .disabled(dictation.phase != .ready)
                    }
                    Button("Turn off") { dictation.endSession() }
                        .buttonStyle(SecondaryButtonStyle())
                }
            }
            if let last = dictation.lastResult, dictation.phase != .recording {
                Text(last.text)
                    .font(.system(size: 15))
                    .foregroundStyle(Theme.text)
                    .lineLimit(3)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Theme.surfaceRaised))
                    .textSelection(.enabled)
            }
        }
    }

    private var dotColor: Color {
        switch dictation.phase {
        case .off: return Theme.subtext
        case .recording: return Theme.accent
        case .failed: return Theme.error
        default: return Theme.success
        }
    }

    private var statusTitle: String {
        switch dictation.phase {
        case .off: return "Echo is off"
        case .ready: return "Mic ready"
        case .recording: return "Listening…"
        case .transcribing: return "Writing…"
        case .failed: return "Something went wrong"
        }
    }

    private var statusDetail: String {
        switch dictation.phase {
        case .off:
            return dictation.message ?? "Tap the mic on the Echo keyboard in any app, or turn Echo on here. While it's on, dictation starts instantly."
        case .ready, .transcribing:
            return "Use the Echo keyboard in any app. The orange dot shows the mic is ready; Echo only keeps audio while you dictate."
        case .recording:
            return "Talk naturally. Echo adds the punctuation."
        case .failed:
            return dictation.message ?? "Try again."
        }
    }
}

private struct ImpactGrid: View {
    let impact: HistoryStore.Impact

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Your impact")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Theme.text)
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                Stat(value: impact.words.formatted(), label: "Words dictated")
                Stat(value: Self.time(impact.minutesSaved), label: "Time saved")
                Stat(value: "\(impact.wpm)", label: "Words per minute")
                Stat(value: "\(impact.streakDays)", label: impact.streakDays == 1 ? "Day streak" : "Day streak")
            }
        }
    }

    static func time(_ minutes: Double) -> String {
        if minutes < 1 { return "\(Int((minutes * 60).rounded()))s" }
        if minutes < 60 { return "\(Int(minutes.rounded()))m" }
        let h = Int(minutes) / 60
        let m = Int(minutes) % 60
        return m == 0 ? "\(h)h" : "\(h)h \(m)m"
    }
}

private struct Stat: View {
    let value: String
    let label: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(value)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundStyle(Theme.text)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
            Text(label)
                .font(.system(size: 13))
                .foregroundStyle(Theme.subtext)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous).fill(Theme.surface))
        .accessibilityElement(children: .combine)
    }
}

private struct StyleRow: View {
    @Binding var style: DictationStyle

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Writing style")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Theme.text)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(DictationStyle.allCases) { s in
                        Button {
                            style = s
                            SharedSettings.shared.style = s
                        } label: {
                            Text(s.title)
                                .font(.system(size: 15, weight: .medium))
                                .foregroundStyle(s == style ? Color.black : Theme.text)
                                .padding(.horizontal, 16)
                                .frame(minHeight: 40)
                                .background(Capsule().fill(s == style ? Theme.accent : Theme.surface))
                        }
                        .accessibilityAddTraits(s == style ? .isSelected : [])
                    }
                }
            }
            Text(style.example)
                .font(.system(size: 14))
                .foregroundStyle(Theme.subtext)
        }
    }
}

private struct RecentList: View {
    @EnvironmentObject private var history: HistoryStore

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Recent")
                .font(.system(size: 20, weight: .bold))
                .foregroundStyle(Theme.text)
            if history.entries.isEmpty {
                Text("Your dictations will appear here. They stay on this iPhone.")
                    .font(.system(size: 15))
                    .foregroundStyle(Theme.subtext)
                    .padding(.vertical, 8)
            } else {
                VStack(spacing: 0) {
                    ForEach(history.entries.prefix(30)) { entry in
                        NavigationLink(value: entry) {
                            VStack(alignment: .leading, spacing: 4) {
                                Text(entry.text)
                                    .font(.system(size: 15))
                                    .foregroundStyle(Theme.text)
                                    .lineLimit(2)
                                    .multilineTextAlignment(.leading)
                                Text(entry.date, format: .relative(presentation: .named))
                                    .font(.system(size: 12))
                                    .foregroundStyle(Theme.subtext)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 12)
                            .padding(.horizontal, 14)
                        }
                        if entry.id != history.entries.prefix(30).last?.id {
                            Divider().overlay(Theme.border).padding(.leading, 14)
                        }
                    }
                }
                .background(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous).fill(Theme.surface))
            }
        }
    }
}

struct HistoryDetailView: View {
    let entry: HistoryEntry
    @EnvironmentObject private var history: HistoryStore
    @EnvironmentObject private var account: AccountStore
    @Environment(\.dismiss) private var dismiss
    @State private var text: String = ""
    @State private var working: RefineMode?
    @State private var problem: String?
    @State private var copied = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(text)
                    .font(.system(size: 18))
                    .foregroundStyle(Theme.text)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(16)
                    .background(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous).fill(Theme.surface))
                Text("\(entry.date.formatted(date: .abbreviated, time: .shortened)) · \(entry.words) words · \(entry.engine)")
                    .font(.footnote)
                    .foregroundStyle(Theme.subtext)
                Button(copied ? "Copied" : "Copy") {
                    UIPasteboard.general.string = text
                    copied = true
                }
                .buttonStyle(PrimaryButtonStyle())

                VStack(alignment: .leading, spacing: 10) {
                    Text("Refine with AI")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(Theme.text)
                    if account.isSignedIn {
                        LazyVGrid(columns: [GridItem(.adaptive(minimum: 100), spacing: 8)], spacing: 8) {
                            ForEach(RefineMode.allCases) { mode in
                                Button {
                                    refine(mode)
                                } label: {
                                    HStack(spacing: 6) {
                                        if working == mode { ProgressView().controlSize(.small) }
                                        Text(mode.title)
                                    }
                                    .font(.system(size: 15, weight: .medium))
                                    .foregroundStyle(Theme.text)
                                    .frame(maxWidth: .infinity, minHeight: 44)
                                    .background(RoundedRectangle(cornerRadius: 10).fill(Theme.surfaceRaised))
                                }
                                .disabled(working != nil)
                            }
                        }
                    } else {
                        Text("Sign in to your BrightLink account in Settings to refine dictations.")
                            .font(.system(size: 15))
                            .foregroundStyle(Theme.subtext)
                    }
                    if let problem {
                        Text(problem).font(.footnote).foregroundStyle(Theme.error)
                    }
                    if text != entry.text {
                        Button("Undo refine") { text = entry.text }
                            .font(.system(size: 15, weight: .medium))
                    }
                }
                Button("Delete", role: .destructive) {
                    history.delete(entry)
                    dismiss()
                }
                .frame(maxWidth: .infinity, minHeight: 44)
            }
            .padding(Theme.gutter)
        }
        .background(Theme.background.ignoresSafeArea())
        .navigationTitle("Dictation")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { text = entry.text }
    }

    private func refine(_ mode: RefineMode) {
        working = mode
        problem = nil
        copied = false
        Task {
            do {
                let out = try await RefineService.refine(text, mode: mode)
                text = out
                history.replaceText(of: entry, with: out)
            } catch {
                problem = error.localizedDescription
            }
            working = nil
        }
    }
}
