import AVFoundation
import EchoCore
import SwiftUI

@main
struct EchoApp: App {
    @StateObject private var dictation = DictationController.shared
    @StateObject private var account = AccountStore.shared
    @StateObject private var history = HistoryStore.shared
    @StateObject private var library = VocabularyLibrary.shared
    @StateObject private var formatting = FormattingSettings.shared
    @StateObject private var model = ModelStore.shared
    @StateObject private var router = Router.shared
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // The keyboard may have sent a command before the UI exists.
        Task { @MainActor in
            DictationController.shared.activate()
            AccountStore.shared.restore()
        }
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(dictation)
                .environmentObject(account)
                .environmentObject(history)
                .environmentObject(library)
                .environmentObject(formatting)
                .environmentObject(model)
                .environmentObject(router)
                .tint(Theme.accent)
                .onOpenURL { router.handle($0) }
        }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active {
                router.appBecameActive()
            } else if phase == .background {
                dictation.openedFromKeyboard = false
            }
        }
    }
}

/// Deep links from the keyboard and app-wide navigation state.
@MainActor
final class Router: ObservableObject {
    static let shared = Router()

    enum SetupStep: Int, CaseIterable {
        case welcome, microphone, keyboard, model, tryIt, style, account
    }

    @Published var showingSetup: Bool
    @Published var setupStep: SetupStep = .welcome
    @Published var keyboardSeen = false

    private init() {
        showingSetup = !SharedSettings.shared.hasOnboarded
        keyboardSeen = Self.readKeyboardSeen()
    }

    /// brightlinkecho://dictate?request=<uuid>&style=<style>
    /// brightlinkecho://setup/full-access
    func handle(_ url: URL) {
        guard url.scheme == Brand.urlScheme else { return }
        switch url.host {
        case "dictate":
            let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let request = items.first { $0.name == "request" }?.value.flatMap(UUID.init(uuidString:)) ?? UUID()
            if let raw = items.first(where: { $0.name == "style" })?.value, let style = DictationStyle(rawValue: raw) {
                SharedSettings.shared.style = style
            }
            let dictation = DictationController.shared
            dictation.openedFromKeyboard = true
            dictation.beginRecording(requestID: request)
        case "setup":
            showingSetup = true
            setupStep = url.path.contains("full-access") ? .keyboard : .welcome
        default:
            break
        }
    }

    func appBecameActive() {
        keyboardSeen = Self.readKeyboardSeen()
        DictationController.shared.warmEngine()
    }

    static func readKeyboardSeen() -> Bool {
        guard let url = Bridge.shared.containerURL?.appendingPathComponent("keyboard-seen") else { return false }
        return FileManager.default.fileExists(atPath: url.path)
    }

    func finishSetup() {
        SharedSettings.shared.hasOnboarded = true
        showingSetup = false
    }
}

struct RootView: View {
    @EnvironmentObject private var router: Router
    @EnvironmentObject private var dictation: DictationController

    var body: some View {
        ZStack {
            Theme.background.ignoresSafeArea()
            if router.showingSetup {
                SetupFlow()
                    .transition(.opacity)
            } else {
                HomeView()
            }
        }
        .fullScreenCover(isPresented: $dictation.openedFromKeyboard) {
            ListeningView()
        }
        .animation(.easeInOut(duration: 0.25), value: router.showingSetup)
    }
}
