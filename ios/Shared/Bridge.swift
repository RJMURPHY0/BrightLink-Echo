import Foundation

/// The channel between the keyboard extension and the app.
///
/// iOS keyboards cannot use the microphone, so the app records in the
/// background and the keyboard drives it. Data travels as small JSON files in
/// the App Group container (written atomically, so a reader never sees half a
/// file); Darwin notifications are only the doorbell that says "re-read".
/// Darwin notifications carry no payload and are delivered while the
/// receiving process is running, which both sides are whenever this matters.
///
/// The keyboard can only write to the container with Full Access turned on;
/// the keyboard checks `hasFullAccess` and explains that before using this.
final class Bridge: @unchecked Sendable {
    enum Signal: String, CaseIterable {
        /// keyboard -> app: a new command file is waiting.
        case command
        /// app -> keyboard: state.json changed.
        case state
    }

    static let shared = Bridge()

    let containerURL: URL?
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private var observers: [Signal: [UUID: () -> Void]] = [:]
    private let lock = NSLock()

    init(appGroup: String = Brand.appGroup) {
        containerURL = FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: appGroup)?
            .appendingPathComponent("bridge", isDirectory: true)
        encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .millisecondsSince1970
        decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .millisecondsSince1970
        if let containerURL {
            try? FileManager.default.createDirectory(at: containerURL, withIntermediateDirectories: true)
        }
    }

    var isAvailable: Bool { containerURL != nil }

    // MARK: Files

    private func url(_ name: String) -> URL? {
        containerURL?.appendingPathComponent(name)
    }

    func readState() -> BridgeState {
        read(BridgeState.self, from: "state.json") ?? BridgeState()
    }

    @discardableResult
    func writeState(_ state: BridgeState, notify: Bool = true) -> Bool {
        let ok = write(state, to: "state.json")
        if ok && notify { post(.state) }
        return ok
    }

    func readCommand() -> BridgeCommand? {
        read(BridgeCommand.self, from: "command.json")
    }

    @discardableResult
    func send(_ command: BridgeCommand) -> Bool {
        let ok = write(command, to: "command.json")
        if ok { post(.command) }
        return ok
    }

    /// Result IDs the keyboard has already inserted, newest last. Stops a
    /// result being typed twice when the keyboard is recreated.
    func consumedResultIDs() -> [UUID] {
        read([UUID].self, from: "consumed.json") ?? []
    }

    func markConsumed(_ id: UUID) {
        var ids = consumedResultIDs().filter { $0 != id }
        ids.append(id)
        write(Array(ids.suffix(50)), to: "consumed.json")
    }

    private func read<T: Decodable>(_ type: T.Type, from name: String) -> T? {
        guard let url = url(name), let data = try? Data(contentsOf: url) else { return nil }
        return try? decoder.decode(T.self, from: data)
    }

    @discardableResult
    private func write<T: Encodable>(_ value: T, to name: String) -> Bool {
        guard let url = url(name), let data = try? encoder.encode(value) else { return false }
        do {
            try data.write(to: url, options: [.atomic])
            return true
        } catch {
            return false
        }
    }

    // MARK: Darwin notifications

    func post(_ signal: Signal) {
        let center = CFNotificationCenterGetDarwinNotifyCenter()
        let name = CFNotificationName(Brand.notificationName(signal.rawValue) as CFString)
        CFNotificationCenterPostNotification(center, name, nil, nil, true)
    }

    /// Calls `handler` on the main queue each time `signal` is posted by any
    /// process. Returns a token for `stopObserving`.
    @discardableResult
    func observe(_ signal: Signal, handler: @escaping () -> Void) -> UUID {
        let token = UUID()
        lock.lock()
        let isFirst = observers[signal, default: [:]].isEmpty
        observers[signal, default: [:]][token] = handler
        lock.unlock()
        if isFirst { register(signal) }
        return token
    }

    func stopObserving(_ token: UUID) {
        lock.lock()
        for key in observers.keys { observers[key]?[token] = nil }
        lock.unlock()
    }

    private func register(_ signal: Signal) {
        let center = CFNotificationCenterGetDarwinNotifyCenter()
        let observer = Unmanaged.passUnretained(self).toOpaque()
        CFNotificationCenterAddObserver(
            center,
            observer,
            { _, observer, name, _, _ in
                guard let observer, let name else { return }
                let bridge = Unmanaged<Bridge>.fromOpaque(observer).takeUnretainedValue()
                bridge.deliver(name.rawValue as String)
            },
            Brand.notificationName(signal.rawValue) as CFString,
            nil,
            .deliverImmediately
        )
    }

    private func deliver(_ rawName: String) {
        guard let signal = Signal.allCases.first(where: { Brand.notificationName($0.rawValue) == rawName }) else {
            return
        }
        lock.lock()
        let handlers = Array(observers[signal, default: [:]].values)
        lock.unlock()
        DispatchQueue.main.async {
            handlers.forEach { $0() }
        }
    }
}
