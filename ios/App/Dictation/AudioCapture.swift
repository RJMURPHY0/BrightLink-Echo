import AVFoundation
import Foundation

/// The warm microphone. Mirrors the desktop's warm-mic design (recorder.py):
/// the input stays open for the whole session so pressing the mic starts
/// capture instantly, and a short pre-roll keeps the first syllable.
///
/// iOS rule this is built around: recording can only START while the app is
/// in the foreground. So the engine starts when the keyboard opens the app,
/// keeps running in the background (UIBackgroundModes: audio, orange dot on),
/// and "recording" just decides whether buffers are kept or dropped.
final class AudioCapture: @unchecked Sendable {
    static let sampleRate: Double = 16_000

    /// 0...1 level, updated per buffer.
    var onLevel: ((Float) -> Void)?
    /// Called on the main queue when the system takes the mic away
    /// (a phone call, Siri) or the route changes so the engine stopped.
    var onInterrupted: ((String) -> Void)?

    private let engine = AVAudioEngine()
    private let queue = DispatchQueue(label: "io.brightlink.echo.audio")
    private var converter: AVAudioConverter?
    private let targetFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: AudioCapture.sampleRate,
                                             channels: 1, interleaved: false)!

    // Guarded by `queue`.
    private var isRecording = false
    private var recorded: [Float] = []
    private var preRoll: [Float] = []
    private let preRollSamples = Int(AudioCapture.sampleRate * 0.4)
    /// Hard cap so a forgotten recording can't exhaust memory (~38 MB).
    private let maxSamples = Int(AudioCapture.sampleRate * 600)

    private var observers: [NSObjectProtocol] = []

    var isRunning: Bool { engine.isRunning }

    init() {
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] note in
            self?.handleInterruption(note)
        })
        observers.append(center.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            self?.handleConfigurationChange()
        })
        observers.append(center.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: .main) { [weak self] _ in
            self?.stopEngine()
            self?.onInterrupted?("Audio restarted. Tap the mic in Echo to start again.")
        })
    }

    deinit {
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
    }

    /// Opens the mic. Must be called while the app is in the foreground.
    func start() throws {
        if engine.isRunning { return }
        let session = AVAudioSession.sharedInstance()
        // mixWithOthers: music and podcasts keep playing while the mic is warm.
        try session.setCategory(.playAndRecord, mode: .default, options: [.mixWithOthers, .defaultToSpeaker])
        try session.setPreferredIOBufferDuration(0.02)
        try session.setActive(true)

        let input = engine.inputNode
        let inputFormat = input.outputFormat(forBus: 0)
        guard inputFormat.sampleRate > 0, inputFormat.channelCount > 0 else {
            throw CaptureError.noMicrophone
        }
        converter = AVAudioConverter(from: inputFormat, to: targetFormat)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { [weak self] buffer, _ in
            self?.process(buffer)
        }
        engine.prepare()
        try engine.start()
    }

    func stopEngine() {
        engine.inputNode.removeTap(onBus: 0)
        if engine.isRunning { engine.stop() }
        queue.sync {
            isRecording = false
            recorded.removeAll()
            preRoll.removeAll()
        }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    func beginRecording() {
        queue.sync {
            recorded = preRoll
            preRoll.removeAll(keepingCapacity: true)
            isRecording = true
        }
    }

    /// Stops keeping audio and returns what was recorded.
    func endRecording() -> [Float] {
        queue.sync {
            isRecording = false
            let out = recorded
            recorded.removeAll()
            return out
        }
    }

    func cancelRecording() {
        queue.sync {
            isRecording = false
            recorded.removeAll()
        }
    }

    private func process(_ buffer: AVAudioPCMBuffer) {
        guard let converter else { return }
        let ratio = targetFormat.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio + 64)
        guard let out = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: capacity) else { return }
        var supplied = false
        var error: NSError?
        let status = converter.convert(to: out, error: &error) { _, inputStatus in
            if supplied {
                inputStatus.pointee = .noDataNow
                return nil
            }
            supplied = true
            inputStatus.pointee = .haveData
            return buffer
        }
        guard status != .error, let channel = out.floatChannelData?[0] else { return }
        let count = Int(out.frameLength)
        let samples = Array(UnsafeBufferPointer(start: channel, count: count))

        var sum: Float = 0
        for s in samples { sum += s * s }
        let rms = count > 0 ? sqrt(sum / Float(count)) : 0
        // -50 dB .. -10 dB mapped to 0...1: speech sits in the middle.
        let db = 20 * log10(max(rms, 0.000_01))
        let level = min(max((db + 50) / 40, 0), 1)
        onLevel?(level)

        queue.async { [self] in
            if isRecording {
                if recorded.count < maxSamples { recorded.append(contentsOf: samples) }
            } else {
                preRoll.append(contentsOf: samples)
                if preRoll.count > preRollSamples { preRoll.removeFirst(preRoll.count - preRollSamples) }
            }
        }
    }

    private func handleInterruption(_ note: Notification) {
        guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
              let type = AVAudioSession.InterruptionType(rawValue: raw) else { return }
        if type == .began {
            stopEngine()
            onInterrupted?("Another app took the microphone. Tap the mic to start Echo again.")
        }
    }

    private func handleConfigurationChange() {
        // A route change (headphones in or out) stops the engine. The audio
        // session is still active, so try to rebuild the tap for the new input
        // format; if iOS refuses (we may be in the background), say so.
        guard !engine.isRunning else { return }
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0 else {
            stopEngine()
            onInterrupted?("The microphone changed. Tap the mic to start Echo again.")
            return
        }
        converter = AVAudioConverter(from: format, to: targetFormat)
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.process(buffer)
        }
        do {
            engine.prepare()
            try engine.start()
        } catch {
            stopEngine()
            onInterrupted?("The microphone changed. Tap the mic to start Echo again.")
        }
    }

    enum CaptureError: LocalizedError {
        case noMicrophone
        var errorDescription: String? { "No microphone is available." }
    }
}
