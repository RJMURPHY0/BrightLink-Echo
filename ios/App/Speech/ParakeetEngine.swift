import CoreML
import FluidAudio
import Foundation

/// NVIDIA Parakeet TDT 0.6b v2: the desktop app's primary English engine,
/// here as Core ML through FluidAudio. Punctuation and capitals are built in.
///
/// Compute placement: FluidAudio pins the preprocessor to the CPU and the rest
/// to CPU + Neural Engine (never the GPU, which iOS forbids in the
/// background). If a background run is refused (iOS 27 gates background
/// Neural Engine use behind an entitlement), the engine reloads CPU-only and
/// retries once; if that fails too, the caller falls back to Apple's engine.
actor ParakeetEngine: SpeechEngine {
    nonisolated let name = "Parakeet"

    static let version: AsrModelVersion = .v2

    private var manager: AsrManager?
    private var cpuOnly = false
    private var loading: Task<Void, Error>?

    static var modelDirectory: URL { AsrModels.defaultCacheDirectory(for: version) }

    static var isDownloaded: Bool { AsrModels.modelsExist(at: modelDirectory, version: version) }

    var isLoaded: Bool { manager != nil }

    /// Downloads (first time) and loads the model. Safe to call repeatedly;
    /// concurrent callers share one load.
    func prepare(progress: ProgressHandler? = nil) async throws {
        if manager != nil { return }
        if let loading { return try await loading.value }
        let useCPU = cpuOnly
        let task = Task<Void, Error> {
            let models: AsrModels
            if useCPU {
                let config = MLModelConfiguration()
                config.computeUnits = .cpuOnly
                models = try await AsrModels.downloadAndLoad(
                    configuration: config, version: Self.version,
                    encoderComputeUnits: .cpuOnly, progressHandler: progress)
            } else {
                models = try await AsrModels.downloadAndLoad(version: Self.version, progressHandler: progress)
            }
            let asr = AsrManager(config: .default)
            try await asr.loadModels(models)
            self.finishLoading(asr)
        }
        loading = task
        do {
            try await task.value
        } catch {
            loading = nil
            throw error
        }
    }

    private func finishLoading(_ asr: AsrManager) {
        manager = asr
        loading = nil
        Self.excludeFromBackup(Self.modelDirectory)
    }

    func unload() async {
        if let manager { await manager.cleanup() }
        manager = nil
        loading = nil
    }

    func transcribe(_ samples: [Float], language: String) async throws -> Transcript {
        guard language.hasPrefix("en") else { throw SpeechError.unsupportedLanguage(language) }
        guard Self.isDownloaded else { throw SpeechError.notReady("The Echo speech model is still downloading.") }
        // Parakeet needs at least ~1 s of audio; pad short clips with silence
        // rather than refuse them ("Yes." is a real dictation).
        var audio = samples
        if audio.count < 16_000 { audio += [Float](repeating: 0, count: 16_000 - audio.count) }
        do {
            return try await run(audio)
        } catch {
            guard !cpuOnly else { throw error }
            // Most likely the Neural Engine was refused in the background.
            cpuOnly = true
            await unload()
            return try await run(audio)
        }
    }

    private func run(_ audio: [Float]) async throws -> Transcript {
        try await prepare()
        guard let manager else { throw SpeechError.notReady("The Echo speech model isn't loaded.") }
        var state = TdtDecoderState.make()
        let result = try await manager.transcribe(audio, decoderState: &state)
        return Transcript(text: result.text, wordConfidence: nil, engine: name)
    }

    private static func excludeFromBackup(_ url: URL) {
        var target = url
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? target.setResourceValues(values)
    }
}
