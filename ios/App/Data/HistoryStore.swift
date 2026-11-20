import EchoCore
import Foundation

struct HistoryEntry: Codable, Identifiable, Hashable {
    var id = UUID()
    var date: Date
    var text: String
    var raw: String
    var engine: String
    var audioSeconds: Double
    var style: DictationStyle
    var words: Int { text.split(whereSeparator: { $0.isWhitespace }).count }
}

/// Dictation history and "Your impact", kept on this phone only. Like the
/// desktop, history text never leaves the device unless Cloud Sync is on
/// (off by default, and not offered on iPhone yet).
@MainActor
final class HistoryStore: ObservableObject {
    static let shared = HistoryStore()

    @Published private(set) var entries: [HistoryEntry] = []

    /// stats.py constants.
    static let dictationWPM = 160.0
    static let typingWPM = 40.0
    /// Keep the newest entries; older ones still count in the totals.
    private let keep = 2_000

    private struct FileModel: Codable {
        var entries: [HistoryEntry]
        var carriedWords: Int
        var carriedSeconds: Double
    }

    private var carriedWords = 0
    private var carriedSeconds = 0.0

    private let fileURL: URL = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("history.json")
    }()

    private init() { load() }

    func add(text: String, raw: String, engine: String, audioSeconds: Double, style: DictationStyle) {
        entries.insert(HistoryEntry(date: Date(), text: text, raw: raw, engine: engine,
                                    audioSeconds: audioSeconds, style: style), at: 0)
        if entries.count > keep {
            for old in entries[keep...] {
                carriedWords += old.words
                carriedSeconds += old.audioSeconds
            }
            entries.removeLast(entries.count - keep)
        }
        save()
    }

    func delete(_ entry: HistoryEntry) {
        entries.removeAll { $0.id == entry.id }
        save()
    }

    func deleteAll() {
        entries.removeAll()
        carriedWords = 0
        carriedSeconds = 0
        save()
    }

    func replaceText(of entry: HistoryEntry, with text: String) {
        guard let i = entries.firstIndex(where: { $0.id == entry.id }) else { return }
        entries[i].text = text
        save()
    }

    // MARK: Impact (stats.py)

    struct Impact {
        var words: Int
        var minutesSaved: Double
        var wpm: Int
        var dictations: Int
        var streakDays: Int
        var todayWords: Int
    }

    func impact(since start: Date? = nil) -> Impact {
        let scoped = start.map { s in entries.filter { $0.date >= s } } ?? entries
        let words = scoped.reduce(0) { $0 + $1.words } + (start == nil ? carriedWords : 0)
        let seconds = scoped.reduce(0.0) { $0 + $1.audioSeconds } + (start == nil ? carriedSeconds : 0)
        // Speaking rate only counts once it is meaningful, and only plausible
        // per-dictation rates (20-350 wpm), as stats.py does.
        let plausible = scoped.filter { e in
            guard e.audioSeconds > 0 else { return false }
            let rate = Double(e.words) / (e.audioSeconds / 60)
            return rate >= 20 && rate <= 350
        }
        let vWords = plausible.reduce(0) { $0 + $1.words }
        let vSeconds = plausible.reduce(0.0) { $0 + $1.audioSeconds }
        let wpm = (vWords >= 50 && vSeconds >= 30) ? Double(vWords) / (vSeconds / 60) : Self.dictationWPM
        let saved = max(0, Double(words) / Self.typingWPM - Double(words) / max(wpm, 1))
        let today = Calendar.current.startOfDay(for: Date())
        let todayWords = entries.filter { $0.date >= today }.reduce(0) { $0 + $1.words }
        _ = seconds
        return Impact(words: words, minutesSaved: saved, wpm: Int(wpm.rounded()),
                      dictations: scoped.count, streakDays: streak(), todayWords: todayWords)
    }

    /// Consecutive days with a dictation, where weekends bridge a gap (stats.py).
    private func streak() -> Int {
        let cal = Calendar.current
        let days = Set(entries.map { cal.startOfDay(for: $0.date) })
        guard !days.isEmpty else { return 0 }
        var day = cal.startOfDay(for: Date())
        if !days.contains(day) {
            // Today not dictated yet: the streak can still be alive from yesterday.
            guard let y = cal.date(byAdding: .day, value: -1, to: day) else { return 0 }
            day = y
        }
        var count = 0
        var guardRail = 0
        while guardRail < 3_000 {
            guardRail += 1
            if days.contains(day) {
                count += 1
            } else if !cal.isDateInWeekend(day) {
                break
            }
            guard let prev = cal.date(byAdding: .day, value: -1, to: day) else { break }
            day = prev
        }
        return count
    }

    // MARK: Disk

    private func load() {
        guard let data = try? Data(contentsOf: fileURL),
              let model = try? JSONDecoder().decode(FileModel.self, from: data) else { return }
        entries = model.entries
        carriedWords = model.carriedWords
        carriedSeconds = model.carriedSeconds
    }

    private func save() {
        let model = FileModel(entries: entries, carriedWords: carriedWords, carriedSeconds: carriedSeconds)
        if let data = try? JSONEncoder().encode(model) {
            try? data.write(to: fileURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        }
    }
}
