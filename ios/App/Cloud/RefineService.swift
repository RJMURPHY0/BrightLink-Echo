import Foundation

/// AI refine through the BrightLink relay (ai_refiner._relay_chat): the
/// server holds the model keys and picks the model; the phone sends only the
/// signed-in user's token. No API key ever ships in the app.
enum RefineMode: String, CaseIterable, Identifiable {
    case punctuation, email, formal, casual, concise

    var id: String { rawValue }

    var title: String {
        switch self {
        case .punctuation: return "Fix all"
        case .email: return "Email"
        case .formal: return "Formal"
        case .casual: return "Casual"
        case .concise: return "Short"
        }
    }
}

enum RefineService {
    static let relayPath = "/api/whisper/ai"

    static func refine(_ text: String, mode: RefineMode, customAsk: String? = nil) async throws -> String {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return text }
        guard let token = await AccountStore.shared.validToken() else {
            throw ServiceError(message: "Sign in to use AI")
        }
        var prompt = customAsk ?? (RefinePrompts.modes[mode.rawValue] ?? RefinePrompts.modes["punctuation"]!)
        if customAsk != nil { prompt += RefinePrompts.customAskSuffix }
        if text.unicodeScalars.contains(where: { $0.properties.isEmojiPresentation }) {
            prompt += RefinePrompts.keepEmoji
        }
        let system = (mode == .punctuation && customAsk == nil) ? RefinePrompts.editorSystem : RefinePrompts.styleSystem
        let safe = text
            .replacingOccurrences(of: RefinePrompts.dataClose, with: "< /text_to_edit>")
            .replacingOccurrences(of: RefinePrompts.dataOpen, with: "< text_to_edit>")
        let user = "\(prompt)\n\n\(RefinePrompts.dataNote)\n\n\(RefinePrompts.dataOpen)\n\(safe)\n\(RefinePrompts.dataClose)"
        let words = text.split(whereSeparator: { $0.isWhitespace }).count
        let body: [String: Any] = ["system": system, "user": user,
                                   "max_tokens": min(8192, max(1024, words * 4)), "temperature": 0.0]

        var request = URLRequest(url: SupabaseConfig.appURL.appendingPathComponent(relayPath))
        request.httpMethod = "POST"
        request.timeoutInterval = 25
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request)
        } catch {
            throw ServiceError(message: "Could not reach BrightLink. Check your connection and try again")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        switch status {
        case 200..<300: break
        case 401: throw ServiceError(message: "Your sign-in has expired. Sign in again to use AI", status: status)
        case 403: throw ServiceError(message: "AI is switched off for your organisation", status: status)
        case 429: throw ServiceError(message: "Too many AI requests just now. Try again in a few minutes", status: status)
        default: throw ServiceError(message: "AI is unavailable right now. Try again shortly", status: status)
        }
        let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        var out = ((obj?["text"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        out = out.replacingOccurrences(of: RefinePrompts.dataOpen, with: "")
            .replacingOccurrences(of: RefinePrompts.dataClose, with: "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !out.isEmpty else { throw ServiceError(message: "AI is unavailable right now. Try again shortly") }
        // Never add dashes the speaker didn't say (ai_refiner.drop_new_dashes).
        if !text.contains("—") { out = out.replacingOccurrences(of: " — ", with: ", ").replacingOccurrences(of: "—", with: ", ") }
        if !text.contains("–") { out = out.replacingOccurrences(of: " – ", with: ", ") }
        return out
    }
}
