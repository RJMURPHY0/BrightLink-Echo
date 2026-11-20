import FluidAudio
import Foundation
import Network

/// Download state of the Parakeet model, for Setup and Settings. Until it is
/// ready, dictation still works through Apple's on-device engine.
@MainActor
final class ModelStore: ObservableObject {
    static let shared = ModelStore()

    enum State: Equatable {
        case notDownloaded
        case downloading(Double)
        case ready
        case failed(String)
    }

    @Published private(set) var state: State
    @Published private(set) var onCellular = false

    private let monitor = NWPathMonitor()
    private var task: Task<Void, Never>?

    private init() {
        state = ParakeetEngine.isDownloaded ? .ready : .notDownloaded
        monitor.pathUpdateHandler = { path in
            let cellular = path.usesInterfaceType(.cellular) && !path.usesInterfaceType(.wifi)
            Task { @MainActor in ModelStore.shared.onCellular = cellular }
        }
        monitor.start(queue: DispatchQueue(label: "io.brightlink.echo.net"))
    }

    var isReady: Bool { state == .ready }

    func download() {
        guard task == nil, state != .ready else { return }
        state = .downloading(0)
        let engine = DictationController.shared.parakeet
        task = Task { [weak self] in
            do {
                try await engine.prepare(progress: { progress in
                    let fraction = progress.fractionCompleted
                    Task { @MainActor in ModelStore.shared.progressed(fraction) }
                })
                self?.state = .ready
            } catch {
                ErrorLog.record("model_download_failed", detail: String(describing: error))
                self?.state = .failed("The download stopped. Check your connection and try again.")
            }
            self?.task = nil
        }
    }

    private func progressed(_ fraction: Double) {
        guard case .downloading = state else { return }
        state = .downloading(fraction)
    }

    func delete() {
        task?.cancel()
        task = nil
        Task {
            await DictationController.shared.parakeet.unload()
            try? FileManager.default.removeItem(at: ParakeetEngine.modelDirectory)
            state = .notDownloaded
        }
    }
}
