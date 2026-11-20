import EchoCore
import SwiftUI
import UIKit

@MainActor
final class KeyboardModel: ObservableObject {
    enum Page { case letters, numbers, symbols }
    enum Shift { case off, on, locked }

    @Published private(set) var phase: SessionPhase = .off
    @Published private(set) var level: Float = 0
    @Published private(set) var message: String?
    @Published private(set) var hasFullAccess = false
    @Published var page: Page = .letters
    @Published var shift: Shift = .on
    @Published var style: DictationStyle
    @Published var showStyleMenu = false
    @Published private(set) var returnTitle = "return"
    @Published private(set) var needsGlobe = true

    weak var controller: KeyboardViewController?
    private let bridge = Bridge.shared
    private let settings = SharedSettings.shared
    private var token: UUID?
    private var pollTimer: Timer?
    private var pendingRequestID: UUID?
    private var lastSpaceAt: Date?
    private var deleteTimer: Timer?
    private let impact = UIImpactFeedbackGenerator(style: .light)
    private let notify = UINotificationFeedbackGenerator()

    init(controller: KeyboardViewController) {
        self.controller = controller
        style = SharedSettings.shared.style
    }

    var proxy: UITextDocumentProxy? { controller?.textDocumentProxy }

    // MARK: Lifecycle

    func appear() {
        hasFullAccess = controller?.hasFullAccess ?? false
        needsGlobe = controller?.needsInputModeSwitchKey ?? true
        style = settings.style
        if token == nil {
            // Bridge delivers on the main queue.
            token = bridge.observe(.state) { [weak self] in
                MainActor.assumeIsolated { self?.refresh() }
            }
        }
        markKeyboardSeen()
        refresh()
        textContextChanged()
    }

    func disappear() {
        if let token { bridge.stopObserving(token) }
        token = nil
        stopPolling()
        stopDelete()
    }

    /// Lets the app's setup screen know the keyboard is installed and has
    /// Full Access (it can only write to the shared container if it does).
    private func markKeyboardSeen() {
        guard hasFullAccess, let url = bridge.containerURL?.appendingPathComponent("keyboard-seen") else { return }
        try? Data(ISO8601DateFormatter().string(from: Date()).utf8).write(to: url, options: .atomic)
    }

    // MARK: State from the app

    func refresh() {
        let state = bridge.readState()
        let effective = state.effectivePhase()
        phase = effective
        level = state.level
        message = effective == .failed ? state.message : (effective == .off ? nil : state.message)
        if effective == .recording || effective == .transcribing { startPolling() } else { stopPolling() }
        if let result = state.result { maybeInsert(result) }
    }

    private func maybeInsert(_ result: DictationResult) {
        guard hasFullAccess else { return }
        let fresh = Date().timeIntervalSince(result.createdAt) < 45
        let mine = result.requestID == pendingRequestID
        guard mine || fresh else { return }
        guard !bridge.consumedResultIDs().contains(result.requestID) else { return }
        bridge.markConsumed(result.requestID)
        pendingRequestID = nil
        insertDictation(result.text)
        if settings.haptics { notify.notificationOccurred(.success) }
    }

    /// Inserts with a separating space when the cursor sits right after a
    /// word, the way the desktop app joins dictations.
    private func insertDictation(_ text: String) {
        guard let proxy, !text.isEmpty else { return }
        var out = text
        if let before = proxy.documentContextBeforeInput, let last = before.last,
           !last.isWhitespace, let first = out.first, !".,!?;:)".contains(first) {
            out = " " + out
        }
        proxy.insertText(out)
    }

    private func startPolling() {
        guard pollTimer == nil else { return }
        // Timers on the main run loop fire on the main thread.
        let timer = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        }
        RunLoop.main.add(timer, forMode: .common)
        pollTimer = timer
    }

    private func stopPolling() {
        pollTimer?.invalidate()
        pollTimer = nil
    }

    // MARK: Mic

    func micTapped() {
        if settings.haptics { impact.impactOccurred() }
        guard hasFullAccess else {
            openApp(path: "setup/full-access")
            return
        }
        switch phase {
        case .ready, .failed:
            let command = BridgeCommand(kind: .start, style: style)
            pendingRequestID = command.id
            bridge.send(command)
            phase = .recording  // optimistic; the app confirms within ~100 ms
            startPolling()
        case .recording:
            bridge.send(BridgeCommand(kind: .stop, requestID: pendingRequestID))
            phase = .transcribing
        case .transcribing:
            break
        case .off:
            // The mic can only be opened by the app in the foreground.
            let id = UUID()
            pendingRequestID = id
            openApp(path: "dictate", query: [URLQueryItem(name: "request", value: id.uuidString),
                                             URLQueryItem(name: "style", value: style.rawValue)])
        }
    }

    func cancelTapped() {
        bridge.send(BridgeCommand(kind: .cancel, requestID: pendingRequestID))
        pendingRequestID = nil
        phase = .ready
    }

    func select(_ newStyle: DictationStyle) {
        style = newStyle
        if hasFullAccess { settings.style = newStyle }
        showStyleMenu = false
    }

    private func openApp(path: String, query: [URLQueryItem] = []) {
        var components = URLComponents()
        components.scheme = Brand.urlScheme
        components.host = path.components(separatedBy: "/").first
        let rest = path.components(separatedBy: "/").dropFirst().joined(separator: "/")
        components.path = rest.isEmpty ? "" : "/" + rest
        components.queryItems = query.isEmpty ? nil : query
        if let url = components.url { controller?.openURL(url) }
    }

    var statusText: String {
        if !hasFullAccess { return "Turn on Full Access to dictate" }
        switch phase {
        case .off: return "Tap the mic to start Echo"
        case .ready: return "Tap the mic and speak"
        case .recording: return "Listening…"
        case .transcribing: return "Writing…"
        case .failed: return message ?? "That didn't work. Try again."
        }
    }

    // MARK: Typing

    func type(_ key: String) {
        if settings.haptics { impact.impactOccurred(intensity: 0.5) }
        let text = (page == .letters && shift != .off) ? key.uppercased() : key
        proxy?.insertText(text)
        if shift == .on { shift = .off }
        if page != .letters && (key == "'" || key == "\"") { page = .letters }
        lastSpaceAt = nil
    }

    func space() {
        if settings.haptics { impact.impactOccurred(intensity: 0.5) }
        // Double-space: full stop, like the system keyboard.
        if let last = lastSpaceAt, Date().timeIntervalSince(last) < 0.4,
           let before = proxy?.documentContextBeforeInput, before.hasSuffix(" "),
           let prev = before.dropLast().last, prev.isLetter || prev.isNumber {
            proxy?.deleteBackward()
            proxy?.insertText(". ")
            lastSpaceAt = nil
            shift = .on
            return
        }
        proxy?.insertText(" ")
        lastSpaceAt = Date()
        if page != .letters { page = .letters }
        updateAutoShift()
    }

    func newline() {
        proxy?.insertText("\n")
        updateAutoShift()
    }

    func deleteDown() {
        deleteOnce()
        stopDelete()
        let start = Date()
        let timer = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                let held = Date().timeIntervalSince(start)
                guard held > 0.45 else { return }
                // After a second, delete whole words.
                if held > 1.6 { self.deleteWord() } else { self.deleteOnce() }
            }
        }
        RunLoop.main.add(timer, forMode: .common)
        deleteTimer = timer
    }

    func deleteUp() { stopDelete() }

    private func stopDelete() {
        deleteTimer?.invalidate()
        deleteTimer = nil
    }

    private func deleteOnce() {
        if settings.haptics { impact.impactOccurred(intensity: 0.4) }
        proxy?.deleteBackward()
        updateAutoShift()
    }

    private func deleteWord() {
        guard let before = proxy?.documentContextBeforeInput, !before.isEmpty else { return }
        var count = 0
        var sawWord = false
        for ch in before.reversed() {
            if ch.isWhitespace && sawWord { break }
            if !ch.isWhitespace { sawWord = true }
            count += 1
        }
        for _ in 0..<max(count, 1) { proxy?.deleteBackward() }
    }

    func toggleShift() {
        switch shift {
        case .off: shift = .on
        case .on: shift = .off
        case .locked: shift = .off
        }
    }

    func lockShift() { shift = .locked }

    func textContextChanged() {
        updateAutoShift()
        returnTitle = Self.returnTitle(for: proxy?.returnKeyType)
    }

    private func updateAutoShift() {
        guard shift != .locked, page == .letters else { return }
        guard proxy?.autocapitalizationType != UITextAutocapitalizationType.none else {
            shift = .off
            return
        }
        let before = proxy?.documentContextBeforeInput ?? ""
        let trimmed = before.trimmingCharacters(in: .whitespaces)
        if before.isEmpty || before.hasSuffix("\n") {
            shift = .on
        } else if before.hasSuffix(" "), let last = trimmed.last, ".!?".contains(last) {
            shift = .on
        } else {
            shift = .off
        }
    }

    private static func returnTitle(for type: UIReturnKeyType?) -> String {
        switch type {
        case .go: return "go"
        case .search, .google, .yahoo: return "search"
        case .send: return "send"
        case .done: return "done"
        case .next: return "next"
        case .join: return "join"
        case .route: return "route"
        case .continue: return "continue"
        default: return "return"
        }
    }

    func advanceKeyboard() { controller?.advanceToNextInputMode() }
}
