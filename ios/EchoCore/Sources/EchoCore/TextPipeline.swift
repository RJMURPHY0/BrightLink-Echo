import Foundation

/// The style a person picks for their dictations. Applied after the desktop
/// pipeline, deterministically and offline, so it costs no latency.
public enum DictationStyle: String, Codable, CaseIterable, Identifiable, Sendable {
    case formal
    case casual
    case veryCasual
    case excited

    public var id: String { rawValue }

    /// Each title is written in its own style, so the menu previews itself.
    public var title: String {
        switch self {
        case .formal: return "Formal."
        case .casual: return "Casual"
        case .veryCasual: return "very casual"
        case .excited: return "Excited!"
        }
    }

    public var subtitle: String {
        switch self {
        case .formal: return "Capitals and full punctuation"
        case .casual: return "Capitals, lighter punctuation"
        case .veryCasual: return "no capitals, no punctuation"
        case .excited: return "Capitals and upbeat punctuation"
        }
    }

    public var example: String {
        StyleTransform.apply(
            "Hey, are you free for lunch tomorrow? Let's do 12 if that works for you.",
            style: self
        )
    }
}

public enum StyleTransform {
    private static let sentencePunctuation = PyRegex(#"[.,;:!?]+(?=\s|$)"#)
    private static let acronym = PyRegex(#"^[A-Z0-9]{2,}s?$"#)

    public static func apply(_ text: String, style: DictationStyle) -> String {
        guard !text.isEmpty else { return text }
        // Lists, emails and anything multi-line keep their layout untouched:
        // restyling a numbered list or a sign-off would break it.
        if text.contains("\n") { return text }
        switch style {
        case .formal:
            return text
        case .casual:
            return dropFinalFullStop(text)
        case .veryCasual:
            return veryCasual(text)
        case .excited:
            return excited(text)
        }
    }

    /// "…works for you." -> "…works for you". Keeps "?", "!" and "...".
    static func dropFinalFullStop(_ text: String) -> String {
        guard text.hasSuffix("."), !text.hasSuffix("..") else { return text }
        return String(text.dropLast())
    }

    /// Lower-case words and drop sentence punctuation, but leave acronyms
    /// ("API", "NHS"), numbers ("3.5", "12:30"), contractions and addresses
    /// ("a.b@c.com") alone: punctuation only goes when a space or the end
    /// follows it.
    static func veryCasual(_ text: String) -> String {
        let stripped = sentencePunctuation.sub(text, "")
        let words = stripped.split(separator: " ", omittingEmptySubsequences: false).map { word -> String in
            let w = String(word)
            if acronym.fullMatch(w) != nil { return w }
            return w.lowercased()
        }
        return words.joined(separator: " ").pyStrip
    }

    /// The last sentence ends with "!" instead of "." (or gains one).
    static func excited(_ text: String) -> String {
        var t = text
        if t.hasSuffix("?") || t.hasSuffix("!") { return t }
        if t.hasSuffix("..") { return t }
        if t.hasSuffix(".") { t.removeLast() }
        return t + "!"
    }
}

/// Feature switches for the pipeline. Defaults match the desktop app's
/// config defaults (config.py), so the phone writes like the PC.
public struct PipelineOptions: Codable, Equatable, Sendable {
    public var autoPunctuate: Bool = true
    public var endPunctuation: EndPunctuation = .smart
    public var homophoneFix: Bool = true
    public var spokenPunctuation: Bool = true
    public var autoLists: Bool = true
    public var emailFormat: Bool = true
    public var vocabFuzzy: Bool = true
    public var style: DictationStyle = .casual
    public var senderName: String = ""

    public init() {}
}

/// The desktop app's post-recognition pipeline, in the desktop's order
/// (asr_engine._post_process -> polish -> app.py's assembled passes).
public struct TextPipeline: Sendable {
    public var options: PipelineOptions
    public var vocabulary: [VocabularyEntry]
    public var snippets: [Snippet]

    public init(options: PipelineOptions = PipelineOptions(),
                vocabulary: [VocabularyEntry] = [],
                snippets: [Snippet] = []) {
        self.options = options
        self.vocabulary = vocabulary
        self.snippets = snippets
    }

    /// `wordConfidence`: per-word confidence when the engine reports it (none
    /// does yet). Word positions shift once words are dropped, so it is only
    /// passed to a stage while that stage's own word count still matches.
    public func process(_ raw: String, wordConfidence: [Double?]? = nil) -> String {
        // 1. Per-result clean-up: filler-only suppression, loop guard,
        //    de-stutter, filler words, vocabulary casing.
        var text = Polish.postProcess(raw, hotwords: TextExpansion.hotwords(vocabulary))
        if text.isEmpty { return "" }

        // 2. Whole-utterance polish: pause punctuation, capital, final stop.
        let endMode: EndPunctuation = options.style == .formal ? .always : options.endPunctuation
        text = Polish.polish(text, autoPunctuate: options.autoPunctuate, endPunctuation: endMode)

        // 3. Assembled passes (app.py order).
        text = Disfluency.destutter(text)
        if options.homophoneFix {
            // Homophones takes one value per whitespace-separated word.
            let conf = wordConfidence.flatMap { $0.count == text.pySplit.count ? $0 : nil }
            text = Homophones.fix(text, wordConfidence: conf)
        }
        if options.spokenPunctuation {
            text = SpokenCommands.apply(text)
        }
        if options.autoLists {
            text = ListFormat.format(text)
        }
        if options.emailFormat {
            text = EmailFormat.formatSignoff(text, senderName: options.senderName)
        }

        // 4. The person's own libraries.
        if !vocabulary.isEmpty {
            text = TextExpansion.applyVocabulary(text, entries: vocabulary)
            if options.vocabFuzzy {
                // The fuzzy pass takes one value per [A-Za-z0-9']+ word.
                let conf = wordConfidence.flatMap { $0.count == Self.letterWords.findall(text).count ? $0 : nil }
                text = TextExpansion.applyVocabularyFuzzy(text, entries: vocabulary, wordConfidence: conf)
            }
        }
        if !snippets.isEmpty {
            text = TextExpansion.applySnippets(text, snippets: snippets)
        }

        // 5. Style last, so it sees the finished sentence.
        text = StyleTransform.apply(text, style: options.style)
        return text.pyStrip
    }

    private static let letterWords = PyRegex(#"[A-Za-z0-9']+"#)
}
