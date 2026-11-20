import AVFoundation
import Foundation
import Speech

/// What an engine hands back: the words, plus per-word confidence when the
/// engine reports it (the homophone and vocabulary guards use it).
struct Transcript: Sendable {
    var text: String
    var wordConfidence: [Double?]?
    var engine: String
}

protocol SpeechEngine: Sendable {
    var name: String { get }
    /// `samples`: 16 kHz mono Float32.
    func transcribe(_ samples: [Float], language: String) async throws -> Transcript
}

enum SpeechError: LocalizedError {
    case notReady(String)
    case noSpeech
    case permissionDenied
    case unsupportedLanguage(String)

    var errorDescription: String? {
        switch self {
        case .notReady(let why): return why
        case .noSpeech: return "Didn't catch that. Try again a little closer to the mic."
        case .permissionDenied: return "Speech recognition is turned off for Echo in Settings."
        case .unsupportedLanguage(let code): return "Speech recognition isn't available for \(code) on this iPhone."
        }
    }
}

enum AudioFile {
    /// Writes 16 kHz mono float samples to a temporary WAV for the
    /// file-based recognisers. The caller deletes it.
    static func writeTemporaryWAV(_ samples: [Float]) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("echo-\(UUID().uuidString).wav")
        guard let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 16_000, channels: 1, interleaved: false),
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(max(samples.count, 1))) else {
            throw SpeechError.notReady("Couldn't prepare audio.")
        }
        buffer.frameLength = AVAudioFrameCount(samples.count)
        if let channel = buffer.floatChannelData?[0] {
            samples.withUnsafeBufferPointer { src in
                if let base = src.baseAddress { channel.update(from: base, count: samples.count) }
            }
        }
        let file = try AVAudioFile(forWriting: url, settings: format.settings,
                                   commonFormat: .pcmFormatFloat32, interleaved: false)
        try file.write(from: buffer)
        return url
    }
}

/// Apple's on-device recogniser. iOS 26+: SpeechAnalyzer (long-form, fast).
/// Earlier: SFSpeechRecognizer forced on-device, so audio never leaves the phone.
struct AppleSpeechEngine: SpeechEngine {
    let name = "Apple on-device"

    func transcribe(_ samples: [Float], language: String) async throws -> Transcript {
        let url = try AudioFile.writeTemporaryWAV(samples)
        defer { try? FileManager.default.removeItem(at: url) }
        let locale = Locale(identifier: Self.localeIdentifier(for: language))
        if #available(iOS 26.0, *) {
            let text = try await Self.analyze(url: url, locale: locale)
            return Transcript(text: text, wordConfidence: nil, engine: name)
        }
        let text = try await Self.legacyRecognize(url: url, locale: locale)
        return Transcript(text: text, wordConfidence: nil, engine: name)
    }

    static func localeIdentifier(for language: String) -> String {
        if language.contains("-") || language.contains("_") { return language }
        // Prefer the phone's region for the chosen language (en -> en-GB in the UK).
        let region = Locale.current.region?.identifier ?? ""
        return region.isEmpty ? language : "\(language)-\(region)"
    }

    @available(iOS 26.0, *)
    private static func analyze(url: URL, locale: Locale) async throws -> String {
        guard let supported = await SpeechTranscriber.supportedLocale(equivalentTo: locale) else {
            throw SpeechError.unsupportedLanguage(locale.identifier)
        }
        let transcriber = SpeechTranscriber(locale: supported, preset: .transcription)
        if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
            try await request.downloadAndInstall()
        }
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        let collector = Task<String, Error> {
            var text = ""
            for try await result in transcriber.results where result.isFinal {
                text += String(result.text.characters)
            }
            return text
        }
        let file = try AVAudioFile(forReading: url)
        if let end = try await analyzer.analyzeSequence(from: file) {
            try await analyzer.finalizeAndFinish(through: end)
        } else {
            await analyzer.cancelAndFinishNow()
        }
        return try await collector.value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func legacyRecognize(url: URL, locale: Locale) async throws -> String {
        let status = await withCheckedContinuation { (cont: CheckedContinuation<SFSpeechRecognizerAuthorizationStatus, Never>) in
            SFSpeechRecognizer.requestAuthorization { cont.resume(returning: $0) }
        }
        guard status == .authorized else { throw SpeechError.permissionDenied }
        guard let recognizer = SFSpeechRecognizer(locale: locale), recognizer.isAvailable else {
            throw SpeechError.unsupportedLanguage(locale.identifier)
        }
        let request = SFSpeechURLRecognitionRequest(url: url)
        request.shouldReportPartialResults = false
        request.addsPunctuation = true
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        return try await withCheckedThrowingContinuation { (cont: CheckedContinuation<String, Error>) in
            var finished = false
            recognizer.recognitionTask(with: request) { result, error in
                guard !finished else { return }
                if let error {
                    finished = true
                    cont.resume(throwing: error)
                } else if let result, result.isFinal {
                    finished = true
                    cont.resume(returning: result.bestTranscription.formattedString)
                }
            }
        }
    }
}
