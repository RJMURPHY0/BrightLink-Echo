import EchoCore
import Foundation

/// The person's vocabulary and snippets: local first (dictation never waits
/// on the network), backed up to the account whenever signed in, exactly as
/// the desktop app does (supabase_client.push_library / fetch_library).
/// Merge rule: per row ID, the newer `updated_at` wins, tombstones included,
/// so a delete on the PC removes the term on the phone and vice versa.
@MainActor
final class VocabularyLibrary: ObservableObject {
    static let shared = VocabularyLibrary()

    struct Stored<T: Codable & Hashable>: Codable, Hashable {
        var item: T
        var updatedAt: Date
    }

    @Published private(set) var vocabulary: [Stored<VocabularyEntry>] = []
    @Published private(set) var snippets: [Stored<Snippet>] = []
    @Published private(set) var lastSync: Date?
    @Published private(set) var syncProblem: String?

    struct Snapshot: Sendable {
        var vocabulary: [VocabularyEntry]
        var snippets: [Snippet]
    }

    private let service = SupabaseService()
    private let fileURL: URL = {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("library.json")
    }()

    private struct FileModel: Codable {
        var vocabulary: [Stored<VocabularyEntry>]
        var snippets: [Stored<Snippet>]
    }

    private init() { load() }

    var activeVocabulary: [VocabularyEntry] { vocabulary.map(\.item).filter { !$0.deleted } }
    var activeSnippets: [Snippet] { snippets.map(\.item).filter { !$0.deleted } }

    func snapshot() -> Snapshot { Snapshot(vocabulary: activeVocabulary, snippets: activeSnippets) }

    // MARK: Editing

    func saveTerm(_ entry: VocabularyEntry) {
        upsertLocal(&vocabulary, entry, id: entry.id)
        persistAndPush()
    }

    func deleteTerm(_ entry: VocabularyEntry) {
        var tomb = entry
        tomb.deleted = true
        upsertLocal(&vocabulary, tomb, id: entry.id)
        persistAndPush()
    }

    func saveSnippet(_ snippet: Snippet) {
        upsertLocal(&snippets, snippet, id: snippet.id)
        persistAndPush()
    }

    func deleteSnippet(_ snippet: Snippet) {
        var tomb = snippet
        tomb.deleted = true
        upsertLocal(&snippets, tomb, id: snippet.id)
        persistAndPush()
    }

    private func upsertLocal<T>(_ list: inout [Stored<T>], _ item: T, id: UUID)
        where T: Codable & Hashable & Identifiable, T.ID == UUID {
        let stored = Stored(item: item, updatedAt: Date())
        if let i = list.firstIndex(where: { $0.item.id == id }) { list[i] = stored } else { list.append(stored) }
    }

    // MARK: Sync

    func accountChanged() {
        Task { await sync() }
    }

    func sync() async {
        let account = AccountStore.shared
        guard account.isSignedIn, let userID = account.session?.user.id,
              let token = await account.validToken() else { return }
        do {
            let remoteVocab = try await service.select("user_vocabulary", query: "select=*&user_id=eq.\(userID)", token: token)
            let remoteSnips = try await service.select("user_snippets", query: "select=*&user_id=eq.\(userID)", token: token)
            vocabulary = merge(local: vocabulary, remote: remoteVocab.compactMap(Self.vocab))
            snippets = merge(local: snippets, remote: remoteSnips.compactMap(Self.snippet))
            persist()
            try await push(userID: userID, token: token)
            lastSync = Date()
            syncProblem = nil
        } catch {
            // Best effort: the local copy is the source of truth at dictation time.
            syncProblem = "Couldn't sync your vocabulary just now. It will try again."
        }
    }

    private func merge<T>(local: [Stored<T>], remote: [Stored<T>]) -> [Stored<T>]
        where T: Codable & Hashable & Identifiable, T.ID == UUID {
        var byID: [UUID: Stored<T>] = [:]
        var order: [UUID] = []
        for s in local + remote {
            let id = s.item.id
            if let existing = byID[id] {
                if s.updatedAt > existing.updatedAt { byID[id] = s }
            } else {
                byID[id] = s
                order.append(id)
            }
        }
        return order.compactMap { byID[$0] }
    }

    private func push(userID: String, token: String) async throws {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let vocabRows: [[String: Any]] = vocabulary.map {
            ["id": $0.item.id.uuidString.lowercased(), "user_id": userID,
             "updated_at": iso.string(from: $0.updatedAt), "deleted": $0.item.deleted,
             "term": $0.item.term, "sounds_like": $0.item.soundsLike]
        }
        let snippetRows: [[String: Any]] = snippets.map {
            ["id": $0.item.id.uuidString.lowercased(), "user_id": userID,
             "updated_at": iso.string(from: $0.updatedAt), "deleted": $0.item.deleted,
             "name": $0.item.name, "trigger": $0.item.trigger, "body": $0.item.body]
        }
        try await service.upsert("user_vocabulary", rows: vocabRows, token: token)
        try await service.upsert("user_snippets", rows: snippetRows, token: token)
    }

    private static func parseDate(_ value: Any?) -> Date {
        guard let s = value as? String else { return .distantPast }
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = f.date(from: s) { return d }
        f.formatOptions = [.withInternetDateTime]
        return f.date(from: s) ?? .distantPast
    }

    private static func vocab(_ row: [String: Any]) -> Stored<VocabularyEntry>? {
        guard let raw = row["id"] as? String, let id = UUID(uuidString: raw) else { return nil }
        let entry = VocabularyEntry(id: id, term: (row["term"] as? String) ?? "",
                                    soundsLike: (row["sounds_like"] as? [String]) ?? [],
                                    deleted: (row["deleted"] as? Bool) ?? false)
        return Stored(item: entry, updatedAt: parseDate(row["updated_at"]))
    }

    private static func snippet(_ row: [String: Any]) -> Stored<Snippet>? {
        guard let raw = row["id"] as? String, let id = UUID(uuidString: raw) else { return nil }
        let s = Snippet(id: id, name: (row["name"] as? String) ?? "", trigger: (row["trigger"] as? String) ?? "",
                        body: (row["body"] as? String) ?? "", deleted: (row["deleted"] as? Bool) ?? false)
        return Stored(item: s, updatedAt: parseDate(row["updated_at"]))
    }

    // MARK: Disk

    private func load() {
        guard let data = try? Data(contentsOf: fileURL),
              let model = try? JSONDecoder().decode(FileModel.self, from: data) else { return }
        vocabulary = model.vocabulary
        snippets = model.snippets
    }

    private func persist() {
        let model = FileModel(vocabulary: vocabulary, snippets: snippets)
        if let data = try? JSONEncoder().encode(model) { try? data.write(to: fileURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]) }
    }

    private func persistAndPush() {
        persist()
        Task { await sync() }
    }
}

extension VocabularyEntry: Identifiable {}
extension Snippet: Identifiable {}
