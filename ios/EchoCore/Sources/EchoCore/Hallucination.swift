import Foundation

/// Degenerate-repetition guard: a faithful port of hallucination.py.
///
/// An RNN-T decoder can lock into a cycle and emit the same token until its
/// frame budget runs out ("no, no, no, ..." for hundreds of words). Two
/// conservative text-level rules:
///
///  * COLLAPSE: a unit of 1-4 words repeated `minRun`+ times in a row is cut
///    back to `keep` occurrences (the last occurrence is kept so the run's
///    terminal punctuation survives).
///  * SUPPRESS: an utterance that is nothing but one repeated unit, repeated
///    `pureRun`+ times, returns empty.
///
/// The desktop's reporter/telemetry hooks are intentionally not ported.
public enum Hallucination {
    private static let minRun: Int = 4
    private static let keep: Int = 3
    private static let pureRun: Int = 6
    private static let maxUnit: Int = 4

    private static let stripChars: String = " \t\"'.,!?;:()[]-—–"

    private static let doubledComma = PyRegex(#",\s*,"#)
    private static let multiSpace = PyRegex(#"\s{2,}"#)

    /// Comparison key for a token: punctuation and case carry no information
    /// about whether the decoder is looping ("no," == "no." == "No").
    private static func norm(_ token: String) -> String {
        return token.pyStrip(stripChars).lowercased()
    }

    private static func unitsEqual(_ norms: [String], _ a: Int, _ b: Int, _ n: Int) -> Bool {
        for k in 0..<n {
            if norms[a + k] != norms[b + k] { return false }
        }
        return true
    }

    /// How many times the n-word unit at `start` repeats consecutively.
    private static func runLength(_ norms: [String], _ start: Int, _ n: Int) -> Int {
        var reps = 1
        var j = start + n
        while j + n <= norms.count && unitsEqual(norms, start, j, n) {
            reps += 1
            j += n
        }
        return reps
    }

    /// True when the whole utterance is one unit repeated `pureRun`+ times and
    /// nothing else: decoder collapse, never dictation.
    public static func isPureLoop(_ text: String) -> Bool {
        let tokens: [String] = text.pySplit
        return isPureLoop(tokens: tokens)
    }

    private static func isPureLoop(tokens: [String]) -> Bool {
        if tokens.count < pureRun { return false }
        let norms: [String] = tokens.map { norm($0) }
        for n in 1...maxUnit {
            if tokens.count < n * pureRun || tokens.count % n != 0 { continue }
            // Ignore a unit that is itself empty after normalisation.
            if !norms[0..<n].contains(where: { !$0.isEmpty }) { continue }
            let reps = runLength(norms, 0, n)
            if reps * n == tokens.count && reps >= pureRun { return true }
        }
        return false
    }

    /// Length in tokens of the periodic region starting at `i` with period `n`.
    /// Extends token-by-token (`t[k] == t[k + n]`), never unit-by-unit.
    private static func periodLength(_ norms: [String], _ i: Int, _ n: Int) -> Int {
        var l = 0
        while i + n + l < norms.count && norms[i + l] == norms[i + n + l] {
            l += 1
        }
        return l > 0 ? n + l : 0
    }

    /// Single left-to-right sweep collapsing every periodic run, trying the
    /// shortest period first. Returns (tokens, longest_run_seen).
    private static func collapse(_ tokens: [String]) -> ([String], Int) {
        let norms: [String] = tokens.map { norm($0) }
        var out: [String] = []
        var worst = 0
        var i = 0
        while i < tokens.count {
            var span = 0
            var period = 0
            var reps = 0
            let windowEnd = min(i + maxUnit, tokens.count)
            if norms[i..<windowEnd].contains(where: { !$0.isEmpty }) {
                for n in 1...maxUnit {
                    if i + n >= tokens.count { break }
                    let length = periodLength(norms, i, n)
                    if length > 0 && length / n >= minRun {
                        span = length
                        period = n
                        reps = length / n
                        break
                    }
                }
            }
            if span == 0 {
                out.append(tokens[i])
                i += 1
                continue
            }
            worst = max(worst, reps)
            let full = period * reps
            // First (keep - 1) units, then the FINAL full unit of the run: the
            // last occurrence carries the sentence-terminal punctuation.
            out.append(contentsOf: tokens[i..<(i + period * (keep - 1))])
            out.append(contentsOf: tokens[(i + full - period)..<(i + full)])
            // A trailing partial unit is emitted verbatim.
            out.append(contentsOf: tokens[(i + full)..<(i + span)])
            i += span
        }
        return (out, worst)
    }

    /// Strip degenerate repetition from an ASR result. Returns "" when the
    /// utterance is nothing but a loop. Text with no qualifying run is
    /// returned unchanged.
    public static func clean(_ text: String) -> String {
        if text.isEmpty { return text }
        let tokens: [String] = text.pySplit
        if tokens.count < minRun { return text }

        if isPureLoop(tokens: tokens) { return "" }

        let (collapsed, worst) = collapse(tokens)
        if worst == 0 { return text }

        var cleaned = collapsed.joined(separator: " ")
        // A collapse can leave doubled separators behind ("no, , and").
        cleaned = doubledComma.sub(cleaned, ",")
        cleaned = multiSpace.sub(cleaned, " ").pyStrip
        return cleaned
    }
}
