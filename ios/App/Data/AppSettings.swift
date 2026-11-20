import EchoCore
import Foundation

/// Formatting switches (the desktop's config.py defaults). App-only: the
/// keyboard never needs them because the app does all the text work.
@MainActor
final class FormattingSettings: ObservableObject {
    static let shared = FormattingSettings()

    @Published var options: PipelineOptions {
        didSet { save() }
    }

    private let key = "formattingOptions"

    private init() {
        if let data = UserDefaults.standard.data(forKey: key),
           let saved = try? JSONDecoder().decode(PipelineOptions.self, from: data) {
            options = saved
        } else {
            options = PipelineOptions()
        }
    }

    private func save() {
        if let data = try? JSONEncoder().encode(options) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }
}

/// A small local log of failures, shown in Settings > Diagnostics so a
/// problem is never silent. Nothing here is sent anywhere.
enum ErrorLog {
    struct Event: Codable, Identifiable {
        var id = UUID()
        var date: Date
        var type: String
        var detail: String
    }

    private static let key = "errorLog"
    private static let lock = NSLock()

    static func record(_ type: String, detail: String) {
        lock.lock()
        defer { lock.unlock() }
        var events = read()
        events.insert(Event(date: Date(), type: type, detail: String(detail.prefix(500))), at: 0)
        if events.count > 100 { events.removeLast(events.count - 100) }
        if let data = try? JSONEncoder().encode(events) { UserDefaults.standard.set(data, forKey: key) }
    }

    static func read() -> [Event] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let events = try? JSONDecoder().decode([Event].self, from: data) else { return [] }
        return events
    }

    static func clear() { UserDefaults.standard.removeObject(forKey: key) }
}
