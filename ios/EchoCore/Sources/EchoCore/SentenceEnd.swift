import Foundation

/// Terminal-punctuation modes, mirroring the desktop's "smart" | "always" |
/// "never" Sentence Endings setting.
public enum EndPunctuation: String, Codable, CaseIterable, Sendable {
    case smart, always, never
}

/// Decide whether a finished dictation ends in a full stop: a faithful port of
/// sentence_end.py.
///
/// `smart` ends the dictation with a stop only when the utterance reads as
/// finished, and removes the engine's own stop when it does not. `always` is
/// the pre-1.6.75 behaviour; `never` removes the engine's stop. "?" and "!"
/// are never touched, nor is the dot of an abbreviation.
public enum SentenceEnd {
    private static let terminal: Set<Character> = [".", "!", "?", "…"]
    /// A stop hiding behind a closing quote or bracket still terminates.
    private static let closers: Set<Character> = ["\"", "'", "”", "’", ")", "]", "}", "»"]

    private static let hanging: Set<String> = {
        let raw = """
        a an the and or nor but so because although though while whilst if unless until
        whether since as than which who whom whose when where how
        to of in on at by for with without from into onto upon over under between among
        across during about against toward towards through per via plus versus
        is are was were be been being have has had having
        will would shall should can could may might must
        my your our their his her its every each either neither both
        some any another other such more most less least very rather
        """
        var out = Set<String>()
        for piece in raw.split(whereSeparator: { $0 == " " || $0 == "\n" || $0 == "\t" }) {
            out.insert(String(piece))
        }
        return out
    }()

    /// A token nobody wants a period welded onto: an email, a URL, a filename,
    /// a path.
    private static let addressy = PyRegex(
        #"(?:^|\S)@\S|^\w+://|^www\.|\.[A-Za-z]{2,6}$|[\\/]"#, [.caseInsensitive])

    /// A final "." that belongs to the WORD, not the sentence ("7 p.m.").
    private static let dottedAbbrev = PyRegex(#"^(?:[A-Za-z]\.){2,}$"#)
    private static let abbrevWords: Set<String> = [
        "etc", "vs", "inc", "ltd", "co", "jr", "sr", "approx", "dept",
    ]

    // MARK: public API

    /// True when the text already ends a sentence (closing quotes allowed).
    public static func alreadyTerminated(_ text: String) -> Bool {
        var t = text.pyRStrip()
        while let l = t.last, closers.contains(l) {
            t.removeLast()
        }
        guard let last = t.last else { return false }
        return terminal.contains(last)
    }

    /// (body, closers): trailing closing quotes/brackets peeled off the end.
    private static func splitClosers(_ t: String) -> (String, String) {
        var chars = Array(t)
        var i = chars.count
        while i > 0 && closers.contains(chars[i - 1]) {
            i -= 1
        }
        let body = String(chars[0..<i])
        let tail = String(chars[i...])
        chars.removeAll()
        return (body, tail)
    }

    /// True when the text ends in a single sentence-final full stop. Not an
    /// ellipsis, not "?" or "!", and not the dot of an abbreviation.
    public static func endsWithFullStop(_ text: String) -> Bool {
        let (body, _) = splitClosers(text.pyRStrip())
        if !body.hasSuffix(".") || body.hasSuffix("..") { return false }
        let words: [String] = body.pySplit
        guard let lastWord = words.last else { return false }
        let last: String = lastWord.pyLStrip("\"'“‘([{«")
        if dottedAbbrev.match(last) != nil { return false }
        if abbrevWords.contains(String(last.dropLast()).lowercased()) { return false }
        return true
    }

    /// Remove the sentence-final full stop, keeping any closing quote or
    /// bracket after it. Anything that is not a plain full stop is returned
    /// unchanged (but right-stripped), and so is a text that would be left
    /// empty.
    public static func stripFullStop(_ text: String) -> String {
        let t = text.pyRStrip()
        if !endsWithFullStop(t) { return t }
        let (body, closersPart) = splitClosers(t)
        let bare = String(body.dropLast()).pyRStrip()
        return bare.isEmpty ? t : (bare + closersPart)
    }

    /// True for a function word ("the", "most", "and"): one a sentence almost
    /// never ends on, written lowercase unless it opens a sentence.
    public static func isHangingWord(_ word: String) -> Bool {
        return hanging.contains(word.pyStrip("\"'“‘”’()[]{}«».,!?;:").lowercased())
    }

    /// True when the last word is a hanging word ("is", "the", "where").
    public static func endsOnHangingWord(_ text: String) -> Bool {
        guard let last = text.pySplit.last else { return false }
        return isHangingWord(last)
    }

    /// True when the utterance reads as a complete sentence. Judges the words,
    /// so pass the text WITHOUT its terminal full stop.
    public static func looksFinished(_ text: String) -> Bool {
        let t = text.pyStrip
        guard let lastChar = t.last else { return false }
        if ",;:-–—([{<".contains(lastChar) { return false }   // explicitly still going
        if closers.contains(lastChar) { return true }          // a closed quote ends it
        let words: [String] = t.pySplit
        if words.count < 3 { return false }
        let last = words[words.count - 1]
        if addressy.search(last) != nil { return false }
        let bare = last.pyStrip("\"'”’)]}»").lowercased()
        if hanging.contains(bare) { return false }
        return true
    }

    /// Strip a trailing pause artefact, then settle the terminal full stop.
    ///
    /// A trailing comma/semicolon/colon is always removed and NEVER stacked
    /// with a period. "always" closes the sentence; "never" removes a full stop
    /// the engine wrote; "smart" keeps or adds a stop only when the words read
    /// as finished, and removes the engine's own stop when they do not.
    public static func apply(_ text: String, mode: EndPunctuation = .smart) -> String {
        var t = text.pyStrip
        guard let lastChar = t.last else { return t }
        if ",;:".contains(lastChar) {
            t.removeLast()
            t = t.pyRStrip()
            if t.isEmpty { return t }
            // A comma is the user mid-sentence: strip it, but do not then
            // close the sentence they were still building.
            if mode == .smart { return t }
        }
        if mode == .always {
            return alreadyTerminated(t) ? t : t + "."
        }
        if mode == .never {
            return stripFullStop(t)
        }
        // smart
        if endsWithFullStop(t) {
            let bare = stripFullStop(t)
            return looksFinished(bare) ? t : bare
        }
        if alreadyTerminated(t) {
            return t                        // "?", "!", "…" or an abbreviation dot
        }
        return looksFinished(t) ? t + "." : t
    }

    /// Give `candidate` (a corrected copy of `reference`) the same full-stop
    /// ending as the text that was actually inserted. Only the full stop is
    /// reconciled: a "?" or "!" the correction chose is left alone.
    public static func matchEnding(candidate: String, reference: String) -> String {
        let c = candidate.pyRStrip()
        let r = reference.pyRStrip()
        if c.isEmpty || r.isEmpty { return candidate }
        if endsWithFullStop(c) && !alreadyTerminated(r) {
            return stripFullStop(c)
        }
        if endsWithFullStop(r) && !alreadyTerminated(c), let cl = c.last, !",;:".contains(cl) {
            return c + "."
        }
        return candidate
    }
}
