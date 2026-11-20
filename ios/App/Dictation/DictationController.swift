import Combine
import EchoCore
import Foundation
import UIKit

/// Owns the dictation session: the warm mic, the keyboard's commands, the
/// engines and the text pipeline. Everything the keyboard sees goes through
/// `publish()`; everything it asks for arrives through `handleCommand()`.
@MainActor
final class DictationController: ObservableObject {
    static let shared = DictationController()

    @Published private(set) var phase: SessionPhase = .off
    @Published private(set) var level: Float = 0
    @Published private(set) var message: String?
    @Published private(set) var sessionEndsAt: Date?
    @Published private(set) var lastResult: DictationResult?
    @Published private(set) var lastEngine: String?
    /// True when the keyboard (not the person) opened the app to start a
    /// session: the app shows the "go back" screen instead of Home.
    @Published var openedFromKeyboard = false

    let audio = AudioCapture()
    let parakeet = ParakeetEngine()
    private let apple = AppleSpeechEngine()
    private let bridge = Bridge.shared
    private let settings = SharedSettings.shared

    private var activeRequestID: UUID?
    private var handledCommandIDs: [UUID] = []
    private var heartbeatTimer: Timer?
    private var levelTimer: Timer?
    private var recordingStartedAt: Date?
    private var transcribeTask: Task<Void, Never>?
    private var started = false

    private init() {}

    /// Called once at launch.
    func activate() {
        guard !started else { return }
        started = true
        // A singleton for the app's lifetime, so these reach it directly
        // rather than capturing self across concurrency domains.
        audio.onLevel = { value in
            Task { @MainActor in DictationController.shared.level = value }
        }
        audio.onInterrupted = { why in
            Task { @MainActor in DictationController.shared.endSession(reason: why) }
        }
        bridge.observe(.command) {
            MainActor.assumeIsolated { DictationController.shared.readCommand() }
        }
        // A previous run may have left "recording" behind if it was killed.
        publish()
        // Pick up a command the keyboard sent while we were launching.
        readCommand()
        warmEngine()
    }

    /// Loads Parakeet ahead of the first dictation so stop-to-text stays fast.
    func warmEngine() {
        guard settings.language.hasPrefix("en"), ParakeetEngine.isDownloaded else { return }
        Task.detached(priority: .utility) { [parakeet] in
            try? await parakeet.prepare()
        }
    }

    // MARK: Session

    /// Opens the mic. Only works in the foreground (an iOS rule).
    @discardableResult
    func startSession() -> Bool {
        do {
            try audio.start()
        } catch {
            fail(error.localizedDescription)
            return false
        }
        if phase == .off || phase == .failed { phase = .ready }
        message = nil
        extendSession()
        startHeartbeat()
        warmEngine()
        publish()
        return true
    }

    /// Turns the mic off. A transcription already under way still finishes
    /// and is delivered: the person's words are never thrown away.
    func endSession(reason: String? = nil) {
        audio.stopEngine()
        activeRequestID = nil
        phase = .off
        level = 0
        sessionEndsAt = nil
        message = reason
        stopTimers()
        publish()
    }

    private func extendSession() {
        let minutes = settings.sessionMinutes
        sessionEndsAt = minutes > 0 ? Date().addingTimeInterval(TimeInterval(minutes * 60)) : nil
    }

    // MARK: Commands from the keyboard

    private func readCommand() {
        guard let command = bridge.readCommand() else { return }
        // Idempotent: a command is handled once, and stale ones are ignored.
        guard !handledCommandIDs.contains(command.id) else { return }
        handledCommandIDs.append(command.id)
        if handledCommandIDs.count > 100 { handledCommandIDs.removeFirst(50) }
        guard Date().timeIntervalSince(command.createdAt) < 30 else { return }
        handleCommand(command)
    }

    func handleCommand(_ command: BridgeCommand) {
        switch command.kind {
        case .start:
            if let style = command.style, style != settings.style { settings.style = style }
            beginRecording(requestID: command.id)
        case .stop:
            guard command.requestID == nil || command.requestID == activeRequestID else { return }
            finishRecording()
        case .cancel:
            guard phase == .recording else { return }
            audio.cancelRecording()
            activeRequestID = nil
            phase = .ready
            extendSession()
            publish()
        case .endSession:
            endSession()
        }
    }

    /// Starts keeping audio. If the mic isn't warm, it can only be opened in
    /// the foreground; the keyboard opens the app for exactly that.
    func beginRecording(requestID: UUID = UUID()) {
        if phase == .recording { return }
        if !audio.isRunning {
            // iOS only refuses to START recording from the background; while
            // the app is opening from the keyboard's link it can still be
            // .inactive, which is fine.
            guard UIApplication.shared.applicationState != .background, startSession() else {
                fail("Open Echo to turn the microphone on.")
                endSession(reason: message)
                return
            }
        }
        // A previous dictation still transcribing keeps going and is
        // delivered when ready; never cancel it.
        audio.beginRecording()
        activeRequestID = requestID
        recordingStartedAt = Date()
        phase = .recording
        message = nil
        startLevelTimer()
        publish()
    }

    func finishRecording() {
        guard phase == .recording, let requestID = activeRequestID else { return }
        let samples = audio.endRecording()
        let duration = Date().timeIntervalSince(recordingStartedAt ?? Date())
        stopLevelTimer()
        level = 0
        phase = .transcribing
        publish()

        let language = settings.language
        let options = currentPipelineOptions()
        let library = VocabularyLibrary.shared.snapshot()
        transcribeTask = Task { [weak self] in
            guard let self else { return }
            let outcome = await self.transcribe(samples, language: language)
            guard !Task.isCancelled else { return }
            switch outcome {
            case .success(let transcript):
                let pipeline = TextPipeline(options: options, vocabulary: library.vocabulary, snippets: library.snippets)
                let text = pipeline.process(transcript.text, wordConfidence: transcript.wordConfidence)
                self.deliver(text: text, raw: transcript.text, engine: transcript.engine,
                             requestID: requestID, audioSeconds: duration, samples: samples.count)
            case .failure(let error):
                if self.phase == .transcribing {
                    self.fail(error.localizedDescription)
                } else {
                    ErrorLog.record("transcription_failed", detail: error.localizedDescription)
                }
            }
        }
    }

    private func transcribe(_ samples: [Float], language: String) async -> Result<Transcript, Error> {
        guard Self.hasSpeech(samples) else { return .failure(SpeechError.noSpeech) }
        if language.hasPrefix("en"), ParakeetEngine.isDownloaded {
            do {
                let t = try await parakeet.transcribe(samples, language: language)
                if !t.text.trimmingCharacters(in: .whitespaces).isEmpty { return .success(t) }
            } catch {
                ErrorLog.record("parakeet_failed", detail: String(describing: error))
            }
        }
        do {
            return .success(try await apple.transcribe(samples, language: language))
        } catch {
            ErrorLog.record("apple_speech_failed", detail: String(describing: error))
            return .failure(error)
        }
    }

    /// Silence floor: never run a recogniser on room noise (it invents words).
    static func hasSpeech(_ samples: [Float]) -> Bool {
        guard samples.count >= 4_800 else { return false }  // 0.3 s
        let window = 480  // 30 ms
        var loudWindows = 0
        var i = 0
        while i + window <= samples.count {
            var sum: Float = 0
            for j in i..<(i + window) { sum += samples[j] * samples[j] }
            if sqrt(sum / Float(window)) > 0.006 { loudWindows += 1 }
            if loudWindows >= 4 { return true }  // 120 ms of voice
            i += window
        }
        return false
    }

    private func deliver(text: String, raw: String, engine: String, requestID: UUID,
                         audioSeconds: TimeInterval, samples: Int) {
        lastEngine = engine
        // A newer recording may have started while this one transcribed:
        // leave its state alone and just hand over this result.
        let newerRecording = phase == .recording && activeRequestID != requestID
        if !newerRecording { activeRequestID = nil }
        guard !text.isEmpty else {
            if !newerRecording { fail(SpeechError.noSpeech.localizedDescription) }
            return
        }
        let result = DictationResult(requestID: requestID, text: text, createdAt: Date())
        lastResult = result
        if !newerRecording {
            phase = audio.isRunning ? .ready : .off
            message = nil
        }
        if audio.isRunning { extendSession() }
        publish()
        HistoryStore.shared.add(text: text, raw: raw, engine: engine,
                                audioSeconds: Double(samples) / AudioCapture.sampleRate,
                                style: settings.style)
    }

    private func fail(_ why: String) {
        activeRequestID = nil
        phase = audio.isRunning ? .failed : .off
        message = why
        level = 0
        stopLevelTimer()
        publish()
        // Drop back to ready so the next tap works; the keyboard has shown it.
        if audio.isRunning {
            Task { @MainActor [weak self] in
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                guard let self, self.phase == .failed else { return }
                self.phase = .ready
                self.message = nil
                self.publish()
            }
        }
    }

    private func currentPipelineOptions() -> PipelineOptions {
        var options = FormattingSettings.shared.options
        options.style = settings.style
        options.senderName = AccountStore.shared.senderName ?? ""
        return options
    }

    // MARK: Publishing to the keyboard

    func publish() {
        var state = BridgeState()
        state.phase = phase
        state.heartbeat = Date()
        state.sessionEndsAt = sessionEndsAt
        state.activeRequestID = activeRequestID
        state.level = level
        state.message = message
        state.result = lastResult
        state.engineName = lastEngine
        bridge.writeState(state)
    }

    private func startHeartbeat() {
        heartbeatTimer?.invalidate()
        let timer = Timer(timeInterval: 1, repeats: true) { _ in
            MainActor.assumeIsolated { DictationController.shared.tick() }
        }
        RunLoop.main.add(timer, forMode: .common)
        heartbeatTimer = timer
    }

    private func tick() {
        if let ends = sessionEndsAt, Date() >= ends, phase == .ready {
            endSession()
            return
        }
        if phase == .recording, let started = recordingStartedAt,
           Date().timeIntervalSince(started) > 590 {
            // The capture buffer caps at 10 minutes; finish before it does.
            finishRecording()
            return
        }
        if phase == .off { stopTimers(); return }
        publish()
    }

    private func startLevelTimer() {
        levelTimer?.invalidate()
        let timer = Timer(timeInterval: 0.1, repeats: true) { _ in
            MainActor.assumeIsolated { DictationController.shared.publish() }
        }
        RunLoop.main.add(timer, forMode: .common)
        levelTimer = timer
    }

    private func stopLevelTimer() {
        levelTimer?.invalidate()
        levelTimer = nil
    }

    private func stopTimers() {
        heartbeatTimer?.invalidate()
        heartbeatTimer = nil
        stopLevelTimer()
    }
}
