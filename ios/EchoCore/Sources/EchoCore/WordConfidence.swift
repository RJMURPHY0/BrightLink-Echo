import Foundation

/// The slice of word_confidence.py / phrase_learning.py that the homophone
/// rules need: align a per-word confidence record to the words of a (possibly
/// since-edited) text, keyed by character offset.
///
/// One rule runs through every caller: a word the engine was sure about is
/// never changed, and a word whose confidence cannot be established counts as
/// sure. Unknown fails closed.
///
/// Offsets are UTF-16 offsets (NSString arithmetic), matching `PyMatch.start`.
/// `restrict_to_unsure` (the LLM-fix limiter) is not ported: nothing in
/// EchoCore needs it.
enum WordConfidence {
    /// A word under this is one the engine hesitated over.
    static let unsure: Double = 0.80

    /// How far ahead in the record the aligner will look for a word.
    private static let alignLookahead: Int = 12

    /// text_expansion._WORD_RE
    private static let wordRe = PyRegex(#"[A-Za-z0-9']+"#)
    /// phrase_learning._CONF_WORD_RE
    private static let confWordRe = PyRegex(#"[a-z0-9']+"#)

    /// One recorded word: the normalised spelling and the engine's confidence
    /// (nil when unknown).
    struct Recorded {
        let word: String
        let conf: Double?
    }

    /// A word reduced to what two spellings of the same sound share: lower
    /// case, letters/digits/apostrophe only. Empty when nothing survives.
    static func normaliseWord(_ word: String) -> String {
        return confWordRe.search(word.lowercased())?.group(0) ?? ""
    }

    /// Build the engine-style record from per-whitespace-word confidences:
    /// entry k of `perWord` belongs to the k-th whitespace-separated token of
    /// `text`. Tokens that normalise to nothing (a lone comma) are dropped, as
    /// the engine's own record never holds them.
    static func recorded(from text: String, perWord: [Double?]) -> [Recorded] {
        var out: [Recorded] = []
        let tokens: [String] = text.pySplit
        for (k, token) in tokens.enumerated() {
            let w = normaliseWord(token)
            if w.isEmpty { continue }
            let conf: Double? = k < perWord.count ? perWord[k] : nil
            out.append(Recorded(word: w, conf: conf))
        }
        return out
    }

    /// Confidence per `wordRe` word of `text` (nil where unknown). A forgiving
    /// two-pointer: skip forward in the record to find the next match, and give
    /// up on a word rather than guess.
    static func aligned(_ text: String, _ recorded: [Recorded]) -> [Double?] {
        if text.isEmpty { return [] }
        let words: [String] = wordRe.finditer(text).map { normaliseWord($0.group(0) ?? "") }
        var out: [Double?] = Array(repeating: nil, count: words.count)
        if recorded.isEmpty { return out }
        var j = 0
        for (i, w) in words.enumerated() {
            if w.isEmpty { continue }
            var hit = -1
            var k = j
            let stop = min(recorded.count, j + alignLookahead)
            while k < stop {
                if recorded[k].word == w {
                    hit = k
                    break
                }
                k += 1
            }
            if hit < 0 { continue }       // rewritten or invented: leave unknown
            out[i] = recorded[hit].conf
            j = hit + 1
        }
        return out
    }

    /// {start offset of each word in `text`: confidence}; words whose
    /// confidence is unknown are absent.
    static func byOffset(_ text: String, _ recorded: [Recorded]) -> [Int: Double] {
        let confs = aligned(text, recorded)
        var out: [Int: Double] = [:]
        for (i, m) in wordRe.finditer(text).enumerated() {
            if i < confs.count, let c = confs[i] {
                out[m.start] = c
            }
        }
        return out
    }
}
