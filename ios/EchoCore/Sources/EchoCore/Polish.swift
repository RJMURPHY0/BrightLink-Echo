import Foundation

/// The text clean-up that runs after the speech engine: pause punctuation,
/// the engine `_post_process` body, and the final `polish`. A faithful port of
/// `fix_pause_punctuation`, `ParakeetTranscriber._post_process` and
/// `ParakeetTranscriber.polish` from asr_engine.py.
public enum Polish {
    // A full stop followed by a coordinating conjunction is almost always a
    // pause artefact. "Because"/"That"/"Which" legitimately open sentences.
    private static let pauseConjunctions: [String] = ["And", "But", "So", "Or", "Nor", "Yet"]
    private static let conjAfterStop = PyRegex(
        #"\.\s+("# + pauseConjunctions.joined(separator: "|") + #")\b"#)

    // A full stop followed by a lowercase word: no English sentence starts
    // lowercase. Needs >=2 letters (or a number/percentage) before the stop so
    // single-letter abbreviations (i.e., e.g., a.m.) are left alone.
    private static let stopBeforeLower = PyRegex(#"([a-z]{2,}|\d+%?)\.\s+([a-z])"#)

    // A "sentence" that is nothing but a single -ly adverb is a pause artefact:
    // "...is set up 100%. Correctly." The adverb must be the WHOLE sentence.
    private static let loneAdverbSentence = PyRegex(#"\.\s+([A-Z][a-z]+ly)\s*([.!?])"#)

    private static let commaStop = PyRegex(#"\s+,\s*\."#)
    private static let commaStop2 = PyRegex(#",\s*\."#)
    private static let multiBlank = PyRegex(#"[ \t]{2,}"#)

    /// Remove the sentence breaks Parakeet stamps at mid-sentence pauses.
    ///
    /// Only the unambiguous cases are touched, so a real sentence boundary is
    /// never merged. Punctuation is only ever downgraded, never invented, and
    /// no words change.
    public static func fixPausePunctuation(_ text: String) -> String {
        if text.isEmpty { return text }
        var t = text
        // ". Correctly." -> " correctly.": runs FIRST because it needs the
        // adverb's own terminator to identify the shape.
        t = loneAdverbSentence.sub(t) { (m: PyMatch) -> String in
            return " " + (m.group(1) ?? "").lowercased() + (m.group(2) ?? "")
        }
        // ". And" -> ", and": a comma is the correct join for a continuation.
        t = conjAfterStop.sub(t) { (m: PyMatch) -> String in
            return ", " + (m.group(1) ?? "").lowercased()
        }
        // ". inserted" -> " inserted": drop the spurious stop, keep the word.
        t = stopBeforeLower.sub(t, #"\1 \2"#)
        // Tidy any artefacts a drop left behind (", ." / " ,." / doubled spaces).
        t = commaStop.sub(t, ".")
        t = commaStop2.sub(t, ".")
        t = multiBlank.sub(t, " ")
        return t
    }

    // MARK: post-process

    /// An utterance that is NOTHING but hesitation fillers ("Mm-hmm.", "Hmm,
    /// hmm.", "Uh-huh?") is never intentional dictation.
    private static let fillerOnly = PyRegex(
        #"^(?:[\s,.!?\-]|(?:m+-?h+m+|h+m+|m+m+|u+h+(?:-?h+u+h*)?|u+m+|mhm+)\b)+$"#,
        [.caseInsensitive])

    private static let fillerWords = PyRegex(
        #"(,\s*)?\b(?:um+|uh+|mhm+)\b\s*,?\s*"#, [.caseInsensitive])
    private static let doubledComma = PyRegex(#",\s*,"#)
    private static let commaAfterSentenceStart = PyRegex(#"(^|[.!?]\s+)[,;\s]+"#)
    private static let multiSpace = PyRegex(#" {2,}"#)
    private static let spaceBeforePunct = PyRegex(#"\s+([.,!?])"#)

    /// Common words whose casing must never be forced by the custom vocabulary:
    /// the acronym reading ("IT", "US", "AM", "SO"...) is far rarer in dictation
    /// than the plain English word, so re-casing corrupts correct text.
    private static let vocabCasingStoplist: Set<String> = [
        "it", "us", "in", "is", "at", "am", "an", "as", "be", "by", "do", "go",
        "he", "if", "me", "my", "no", "of", "on", "or", "so", "to", "up", "we",
        "was", "hi", "ok", "all", "and", "the", "for", "but", "not", "you",
    ]

    /// Engine post-processing: filler-only suppression, degenerate-repetition
    /// guard, stutter collapse, filler strip + comma tidy, vocabulary casing.
    ///
    /// `hotwords` are the custom-vocabulary terms (the desktop passes them as
    /// one comma-separated string; each element is also split on commas here so
    /// both shapes behave the same).
    public static func postProcess(_ text: String, hotwords: [String] = []) -> String {
        var t = text.pyStrip
        if t.isEmpty { return "" }
        if fillerOnly.match(t) != nil { return "" }

        // Degenerate repetition ("no, no, no, no, ...").
        t = Hallucination.clean(t)
        if t.isEmpty { return "" }

        // False-start stutters ("push all most rec recent" -> "recent").
        t = Disfluency.destutter(t)

        // Pure non-word fillers only, never real words. Swallow one adjacent
        // comma so "So, um, I think" -> "So, I think" (not "So,, I").
        t = fillerWords.sub(t, #"\1"#)
        t = doubledComma.sub(t, ",")
        t = commaAfterSentenceStart.sub(t, #"\1"#)   // no comma after sentence start
        t = multiSpace.sub(t, " ")
        t = spaceBeforePunct.sub(t, #"\1"#)
        t = t.pyStrip.pyLStrip(",;: ")

        // Custom vocabulary: canonical casing for exact whole-word matches.
        let joined: String = hotwords.joined(separator: ",")
        for rawTerm in joined.components(separatedBy: ",") {
            let term = rawTerm.pyStrip
            if term.count >= 2 && !vocabCasingStoplist.contains(term.lowercased()) {
                let rx = PyRegex(#"\b"# + PyRegex.escape(term) + #"\b"#, [.caseInsensitive])
                t = rx.sub(t) { (_: PyMatch) -> String in term }
            }
        }
        return t
    }

    // MARK: polish

    /// Final whole-utterance polish: leading capital + terminal punctuation.
    /// Applied exactly once per dictation, never per streamed chunk.
    public static func polish(_ text: String, autoPunctuate: Bool = true,
                              endPunctuation: EndPunctuation = .smart) -> String {
        var t = text.pyStrip
        if t.isEmpty { return "" }
        if autoPunctuate {
            // Kill the mid-sentence breaks BEFORE fixing the leading capital /
            // terminal stop, so a dropped boundary can't leave a stray capital.
            t = fixPausePunctuation(t)
        }
        if let f = t.first, f.isLowercase {
            t = t.upperFirst
        }
        if autoPunctuate {
            t = SentenceEnd.apply(t, mode: endPunctuation)
        }
        return t
    }
}
