import Foundation

// Port of text_expansion.py (plus the Double Metaphone encoder from the
// Python `metaphone` 0.6 package, which the fuzzy pass depends on).

/// A custom vocabulary entry. Mirrors the Supabase `user_vocabulary` row
/// (`term`, `sounds_like` text[]) and the desktop dict
/// (`{"term", "sounds_like": [..], "deleted", "managed"}`).
///
/// `managed` is an extra, defaulted field: the desktop marks terms synced from
/// a CRM with `managed: true`, and the phonetic pass applies a much stricter
/// tier to them. Hand-typed entries leave it false.
public struct VocabularyEntry: Codable, Hashable, Sendable {
    public var id: UUID
    public var term: String
    public var soundsLike: [String]
    public var deleted: Bool
    public var managed: Bool

    public init(id: UUID = UUID(), term: String, soundsLike: [String] = [],
                deleted: Bool = false, managed: Bool = false) {
        self.id = id
        self.term = term
        self.soundsLike = soundsLike
        self.deleted = deleted
        self.managed = managed
    }

    private enum CodingKeys: String, CodingKey {
        case id, term, deleted, managed
        case soundsLike = "sounds_like"
    }

    public init(from decoder: Decoder) throws {
        let c: KeyedDecodingContainer<CodingKeys> = try decoder.container(keyedBy: CodingKeys.self)
        self.id = (try? c.decodeIfPresent(UUID.self, forKey: .id)) ?? UUID()
        self.term = (try c.decodeIfPresent(String.self, forKey: .term)) ?? ""
        self.soundsLike = (try? c.decodeIfPresent([String].self, forKey: .soundsLike)) ?? []
        self.deleted = (try? c.decodeIfPresent(Bool.self, forKey: .deleted)) ?? false
        self.managed = (try? c.decodeIfPresent(Bool.self, forKey: .managed)) ?? false
    }

    public func encode(to encoder: Encoder) throws {
        var c: KeyedEncodingContainer<CodingKeys> = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encode(term, forKey: .term)
        try c.encode(soundsLike, forKey: .soundsLike)
        try c.encode(deleted, forKey: .deleted)
        try c.encode(managed, forKey: .managed)
    }
}

/// A snippet: a short spoken trigger that expands into a block of text.
public struct Snippet: Codable, Hashable, Sendable {
    public var id: UUID
    public var name: String
    public var trigger: String
    public var body: String
    public var deleted: Bool

    public init(id: UUID = UUID(), name: String, trigger: String, body: String, deleted: Bool = false) {
        self.id = id
        self.name = name
        self.trigger = trigger
        self.body = body
        self.deleted = deleted
    }

    private enum CodingKeys: String, CodingKey {
        case id, name, trigger, body, deleted
    }

    public init(from decoder: Decoder) throws {
        let c: KeyedDecodingContainer<CodingKeys> = try decoder.container(keyedBy: CodingKeys.self)
        self.id = (try? c.decodeIfPresent(UUID.self, forKey: .id)) ?? UUID()
        self.name = (try? c.decodeIfPresent(String.self, forKey: .name)) ?? ""
        self.trigger = (try? c.decodeIfPresent(String.self, forKey: .trigger)) ?? ""
        self.body = (try? c.decodeIfPresent(String.self, forKey: .body)) ?? ""
        self.deleted = (try? c.decodeIfPresent(Bool.self, forKey: .deleted)) ?? false
    }
}

public enum TextExpansion {

    /// A mishearing shorter than this is refused (MIN_PATTERN_LEN).
    public static let minPatternLength: Int = 3

    private static let reservedTriggers: Set<String> = [
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
        "have", "he", "her", "his", "i", "if", "in", "is", "it", "its", "me",
        "my", "no", "not", "of", "on", "or", "our", "she", "so", "that", "the",
        "their", "them", "then", "there", "they", "this", "to", "up", "was",
        "we", "were", "what", "when", "which", "who", "will", "with", "you",
        "your", "yes", "ok", "okay", "please", "thanks", "thank you",
    ]

    // MARK: Small Python-isms

    private static func isAlphaScalar(_ u: Unicode.Scalar) -> Bool {
        switch u.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter:
            return true
        default:
            return false
        }
    }

    private static func isWordScalar(_ u: Unicode.Scalar) -> Bool {
        if u == "_" { return true }
        if isAlphaScalar(u) { return true }
        switch u.properties.generalCategory {
        case .decimalNumber, .letterNumber, .otherNumber:
            return true
        default:
            return false
        }
    }

    private static func scalarString(_ scalars: [Unicode.Scalar]) -> String {
        var v: String.UnicodeScalarView = String.UnicodeScalarView()
        v.append(contentsOf: scalars)
        return String(v)
    }

    private static func scalarCount(_ s: String) -> Int { s.unicodeScalars.count }

    /// " ".join(s.split())
    private static func normalizeSpaces(_ s: String) -> String { s.pySplit.joined(separator: " ") }

    private static func utf16Slice(_ s: String, _ a: Int, _ b: Int? = nil) -> String {
        let ns: NSString = NSString(string: s)
        let n: Int = ns.length
        let lo: Int = max(0, min(a, n))
        let hi: Int = max(0, min(b ?? n, n))
        if lo >= hi { return "" }
        return ns.substring(with: NSRange(location: lo, length: hi - lo))
    }

    // MARK: Single-pass substitution

    private static func patternFor(_ phrase: String) -> String {
        let words: [String] = phrase.pySplit
        let core: String = words.map { PyRegex.escape($0) }.joined(separator: #"\s+"#)
        var lead: String = ""
        var trail: String = ""
        if !words.isEmpty, let f = phrase.unicodeScalars.first, isWordScalar(f) { lead = #"(?<!\w)"# }
        if !words.isEmpty, let l = phrase.unicodeScalars.last, isWordScalar(l) { trail = #"(?!\w)"# }
        return lead + core + trail
    }

    /// True when the match at `pos` opens the text or follows . ! ? or a newline.
    private static func startsSentence(_ units: [UInt16], _ pos: Int) -> Bool {
        var i: Int = pos - 1
        while i >= 0 && (units[i] == 0x20 || units[i] == 0x09) { i -= 1 }
        if i < 0 { return true }
        let c: UInt16 = units[i]
        return c == 0x2E || c == 0x21 || c == 0x3F || c == 0x0A
    }

    /// The replacement, capitalised only when it is entirely lower case AND it
    /// opens a sentence.
    private static func cased(_ replacement: String, _ units: [UInt16], _ start: Int) -> String {
        var scalars: [Unicode.Scalar] = Array(replacement.unicodeScalars)
        guard let first = scalars.first, isAlphaScalar(first) else { return replacement }
        if replacement != replacement.lowercased() { return replacement }
        if startsSentence(units, start) {
            scalars.removeFirst()
            return String(first).uppercased() + scalarString(scalars)
        }
        return replacement
    }

    private static func substitute(_ text: String, _ pairsIn: [(String, String)], recase: Bool = true) -> String {
        let nonEmpty: [(String, String)] = pairsIn.filter { !$0.0.isEmpty }
        if nonEmpty.isEmpty || text.isEmpty { return text }
        // Longest pattern first (stable).
        let indexed: [(Int, (String, String))] = Array(nonEmpty.enumerated()).map { ($0.offset, $0.element) }
        let sortedPairs: [(Int, (String, String))] = indexed.sorted {
            (a: (Int, (String, String)), b: (Int, (String, String))) -> Bool in
            let la: Int = scalarCount(a.1.0)
            let lb: Int = scalarCount(b.1.0)
            if la != lb { return la > lb }
            return a.0 < b.0
        }
        var parts: [String] = []
        var table: [String] = []
        for (i, entry) in sortedPairs.enumerated() {
            table.append(entry.1.1)
            parts.append("(?<m\(i)>" + patternFor(entry.1.0) + ")")
        }
        guard let rx = try? NSRegularExpression(pattern: parts.joined(separator: "|"),
                                                options: [.caseInsensitive]) else { return text }
        let units: [UInt16] = Array(text.utf16)
        let source: NSString = NSString(string: text)
        let matches: [NSTextCheckingResult] = rx.matches(
            in: text, options: [], range: NSRange(location: 0, length: source.length))
        if matches.isEmpty { return text }
        var out: String = ""
        var last: Int = 0
        for m in matches {
            out += source.substring(with: NSRange(location: last, length: m.range.location - last))
            var replacement: String = source.substring(with: m.range)
            for i in 0..<table.count {
                if m.range(at: i + 1).location != NSNotFound {
                    replacement = table[i]
                    break
                }
            }
            out += recase ? cased(replacement, units, m.range.location) : replacement
            last = m.range.location + m.range.length
        }
        out += source.substring(from: last)
        return out
    }

    // MARK: Vocabulary

    /// vocabulary_hotwords as a list: the distinct terms (case-insensitive),
    /// never the mishearings.
    public static func hotwords(_ entries: [VocabularyEntry]) -> [String] {
        var terms: [String] = []
        var seen: Set<String> = []
        for e in entries where !e.deleted {
            let term: String = e.term.pyStrip
            if !term.isEmpty && !seen.contains(term.lowercased()) {
                seen.insert(term.lowercased())
                terms.append(term)
            }
        }
        return terms
    }

    /// Replace each entry's known mishearings with its term.
    public static func applyVocabulary(_ text: String, entries: [VocabularyEntry]) -> String {
        if text.isEmpty { return text }
        var pairs: [(String, String)] = []
        for e in entries where !e.deleted {
            let term: String = e.term.pyStrip
            if term.isEmpty { continue }
            for raw in e.soundsLike {
                let variant: String = normalizeSpaces(raw)
                if scalarCount(variant) < minPatternLength || variant.lowercased() == term.lowercased() { continue }
                pairs.append((variant, term))
            }
        }
        return substitute(text, pairs)
    }

    // MARK: Fuzzy vocabulary (phonetic safety net)

    private static let fuzzyMinTermLen: Int = 4
    private static let fuzzyJW: Double = 0.70
    private static let fuzzyLenLo: Double = 0.5
    private static let fuzzyLenHi: Double = 1.7
    private static let fuzzyMaxWindow: Int = 5
    private static let managedSure: Double = 0.90
    private static let managedMinTermLen: Int = 5
    private static let managedJW: Double = 0.86
    private static let managedLenLo: Double = 0.7
    private static let managedLenHi: Double = 1.4
    private static let managedWordJW: Double = 0.9
    private static let managedMergeCover: Double = 0.85

    private static let commonWords: Set<String> = Set(
        """
        a about after all also am an and any are as at back be because been before being
        but by call came can come could day did do does doing done down each even every
        few first for from get give go going good got had has have he her here him his how
        i if in into is it its just keep know last less let like little long look made make
        man many may me might more most much must my never new next no not now of off on once
        one only or other our out over own put ran said same say see she should side so some
        such take than that the their them then there these they thing think this those
        through time to too two up us use very was way we well went were what when where which
        while who why will with would year you your
        cell cells bell bells sell sells sale sales share shares mail mails male sell seller
        tell well fell dwell shell smell spell swell dell hell fella
        again today tomorrow okay yes please thanks still really maybe sure
        """.pySplit)

    private static let functionWords: Set<String> = Set(
        """
        a an the this that these those
        i me my mine myself you your yours yourself yourselves he him his himself she
        her hers herself it its itself we us our ours ourselves they them their theirs
        themselves
        who whom whose which what when where why how here there
        all any both each either every neither no none some such another other
        more most much many few less least
        and or but nor so yet if as than then because although though while whilst
        unless until till whether since
        about above across after against along among amongst around at before behind
        below beneath beside between beyond by down during except for from in inside
        into like near of off on onto out outside over per through throughout to toward
        towards under underneath up upon via with within without
        am is are was were be been being do does did have has had having
        will would shall should can could may might must ought not
        i'm i've i'll i'd you're you've you'll you'd he's he'll he'd she's she'll she'd
        it's it'll it'd we're we've we'll we'd they're they've they'll they'd
        that's there's here's what's who's let's
        isn't aren't wasn't weren't don't doesn't didn't haven't hasn't hadn't won't
        wouldn't can't couldn't shouldn't mustn't shan't
        """.pySplit)

    private static let legalSuffixes: Set<String> = [
        "ltd", "limited", "llp", "llc", "plc", "inc", "incorporated", "corp",
        "corporation", "co", "company", "gmbh", "bv", "nv", "sa", "ag", "pty",
        "group", "holdings", "international",
    ]

    private static func jaro(_ s1: [Unicode.Scalar], _ s2: [Unicode.Scalar]) -> Double {
        if s1 == s2 { return 1.0 }
        let l1: Int = s1.count
        let l2: Int = s2.count
        if l1 == 0 || l2 == 0 { return 0.0 }
        var reach: Int = max(l1, l2) / 2 - 1
        if reach < 0 { reach = 0 }
        var m1: [Bool] = Array(repeating: false, count: l1)
        var m2: [Bool] = Array(repeating: false, count: l2)
        var matches: Int = 0
        for i in 0..<l1 {
            let lo: Int = max(0, i - reach)
            let hi: Int = min(i + reach + 1, l2)
            if lo >= hi { continue }
            for j in lo..<hi {
                if m2[j] || s1[i] != s2[j] { continue }
                m1[i] = true
                m2[j] = true
                matches += 1
                break
            }
        }
        if matches == 0 { return 0.0 }
        var transpositions: Int = 0
        var k: Int = 0
        for i in 0..<l1 {
            if !m1[i] { continue }
            while !m2[k] { k += 1 }
            if s1[i] != s2[k] { transpositions += 1 }
            k += 1
        }
        let t: Double = Double(transpositions) / 2.0
        let m: Double = Double(matches)
        return (m / Double(l1) + m / Double(l2) + (m - t) / m) / 3.0
    }

    private static func jaroWinkler(_ a: String, _ b: String) -> Double {
        let s1: [Unicode.Scalar] = Array(a.unicodeScalars)
        let s2: [Unicode.Scalar] = Array(b.unicodeScalars)
        let j: Double = jaro(s1, s2)
        var prefix: Int = 0
        for (x, y) in zip(s1, s2) {
            if x != y { break }
            prefix += 1
            if prefix == 4 { break }
        }
        return j + Double(prefix) * 0.1 * (1.0 - j)
    }

    private static let wordRE: PyRegex = PyRegex(#"[A-Za-z0-9']+"#)
    private static let digitsRE: PyRegex = PyRegex(#"\d+"#)
    private static let ampersandRE: PyRegex = PyRegex(#"\s*&\s*"#)
    private static let breakRE: PyRegex = PyRegex(#"[\-|/]"#)

    private static func digits(_ text: String) -> [String] { digitsRE.findall(text) }

    /// A term as it is said: "&" is "and", and hyphens and bars are breaks.
    private static func spokenForm(_ lowIn: String) -> String {
        let low: String = ampersandRE.sub(lowIn, " and ")
        return normalizeSpaces(breakRE.sub(low, " "))
    }

    private static func fwContained(_ termFW: [String], _ spanFW: [String]) -> Bool {
        var pool: [String] = spanFW
        for w in termFW {
            guard let i = pool.firstIndex(of: w) else { return false }
            pool.remove(at: i)
        }
        return true
    }

    private struct FuzzyTerm {
        let term: String
        let low: String
        let codes: (String, String)
        let strict: Bool
        let termFW: Int?
        let fwCount: Int
        let minSpan: Int
        let termWords: [String]
        let spokenKey: String
        let fwWords: [String]
    }

    private static func phoneticMatch(_ termCodes: (String, String), _ candCodes: (String, String)) -> Bool {
        let (tp, ts) = termCodes
        let (cp, cs) = candCodes
        if tp.isEmpty { return false }
        return tp == cp || tp == cs || (!cp.isEmpty && cp == ts)
    }

    /// Phonetic safety net: rewrite spans that SOUND like a vocabulary term but
    /// were not listed as an explicit mishearing (see text_expansion.py for the
    /// full safety gate).
    ///
    /// `wordConfidence`: the recogniser's confidence per word of `text`, where a
    /// word is a run of `[A-Za-z0-9']` (the Python `_WORD_RE`), `nil` where
    /// unknown. A nil array is Python `word_conf=None`.
    public static func applyVocabularyFuzzy(_ text: String, entries: [VocabularyEntry],
                                            wordConfidence: [Double?]? = nil) -> String {
        if text.isEmpty { return text }
        var dmCache: [String: (String, String)] = [:]
        func dm(_ s: String) -> (String, String) {
            if let hit = dmCache[s] { return hit }
            let code: (String, String) = DoubleMetaphone.encode(s)
            dmCache[s] = code
            return code
        }

        var terms: [FuzzyTerm] = []
        var seen: Set<String> = []
        for e in entries where !e.deleted {
            let term: String = e.term.pyStrip
            let low: String = term.lowercased()
            let managed: Bool = e.managed
            let strict: Bool = managed && !term.contains(" ")
            let minLen: Int = strict ? managedMinTermLen : fuzzyMinTermLen
            if scalarCount(term) < minLen || seen.contains(low) { continue }
            if strict && commonWords.contains(low) { continue }
            seen.insert(low)
            let spoken: String = spokenForm(low)
            let codes: (String, String) = dm(spoken)
            if codes.0.isEmpty { continue }
            let termWords: [String] = wordRE.findall(spoken)
            let fwWords: [String] = termWords.filter { functionWords.contains($0) }
            let fwCount: Int = fwWords.count
            let termFW: Int? = managed ? fwCount : nil
            // Words Double Metaphone cannot hear ("H", "W"): such a term may only
            // replace a span with at least as many words.
            let silent: Bool = termWords.contains { (w: String) -> Bool in
                if scalarCount(w) < 2 { return true }
                return dm(w).0.isEmpty
            }
            let minSpan: Int = silent ? termWords.count : 1
            terms.append(FuzzyTerm(term: term, low: low, codes: codes, strict: strict, termFW: termFW,
                                   fwCount: fwCount, minSpan: minSpan, termWords: termWords,
                                   spokenKey: spoken.replacingOccurrences(of: " ", with: ""),
                                   fwWords: fwWords))
        }
        if terms.isEmpty { return text }

        let tokens: [PyMatch] = wordRE.finditer(text)
        if tokens.isEmpty { return text }

        var termFirst: Set<String> = []
        for t in terms {
            if let c = t.codes.0.first { termFirst.insert(String(c)) }
            if let c = t.codes.1.first { termFirst.insert(String(c)) }
        }
        let allLows: Set<String> = Set(terms.map { $0.low })
        var byPrimary: [String: [Int]] = [:]
        var bySecondary: [String: [Int]] = [:]
        for (idx, t) in terms.enumerated() {
            byPrimary[t.codes.0, default: []].append(idx)
            if !t.codes.1.isEmpty { bySecondary[t.codes.1, default: []].append(idx) }
        }

        func candidates(_ cand: (String, String)) -> [FuzzyTerm] {
            let (cp, cs) = cand
            var found: Set<Int> = []
            if !cp.isEmpty { found.formUnion(byPrimary[cp] ?? []) }
            if !cs.isEmpty { found.formUnion(byPrimary[cs] ?? []) }
            if !cp.isEmpty { found.formUnion(bySecondary[cp] ?? []) }
            return found.sorted().map { terms[$0] }
        }

        let tokenText: [String] = tokens.map { $0.group(0) ?? "" }
        let wordDM: [(String, String)] = tokenText.map { dm($0) }
        let wordLow: [String] = tokenText.map { $0.lowercased() }
        let wordFW: [Bool] = wordLow.map { functionWords.contains($0) }

        var replacements: [(Int, Int, String)] = []
        var consumed: [Bool] = Array(repeating: false, count: tokens.count)
        let units: [UInt16] = Array(text.utf16)

        var size: Int = fuzzyMaxWindow
        while size >= 1 {
            defer { size -= 1 }
            if tokens.count - size + 1 <= 0 { continue }
            for i in 0..<(tokens.count - size + 1) {
                let wp: String = wordDM[i].0
                guard let wpFirst = wp.first, termFirst.contains(String(wpFirst)) else { continue }
                if consumed[i..<(i + size)].contains(true) { continue }
                // Words must be separated by whitespace only.
                var gapsOK: Bool = true
                if size > 1 {
                    for k in 0..<(size - 1) {
                        let gap: String = utf16Slice(text, tokens[i + k].end, tokens[i + k + 1].start)
                        if !gap.pyStrip.isEmpty { gapsOK = false; break }
                    }
                }
                if !gapsOK { continue }
                // Never rewrite a span that is entirely ordinary English.
                if (i..<(i + size)).allSatisfy({ commonWords.contains(wordLow[$0]) }) { continue }
                let cand: String = tokenText[i..<(i + size)].joined(separator: " ")
                let candLow: String = cand.lowercased()
                let candCodes: (String, String) = size == 1 ? wordDM[i] : dm(cand)
                let candKey: String = candLow.replacingOccurrences(of: " ", with: "")
                let spanFW: Int = wordFW[i..<(i + size)].filter { $0 }.count
                var best: String? = nil
                var bestJW: Double = 0.0
                if allLows.contains(candLow) { continue }
                let spanFWWords: [String] = wordLow[i..<(i + size)].filter { functionWords.contains($0) }
                var spanUnsure: Bool = wordConfidence == nil
                if let conf = wordConfidence {
                    for k in i..<(i + size) where k < conf.count {
                        if let v = conf[k], v < managedSure { spanUnsure = true; break }
                    }
                }
                for t in candidates(candCodes) {
                    if size < t.minSpan { continue }
                    if t.termFW != nil && !spanUnsure { continue }
                    // No swapping one function word for another.
                    if !t.fwWords.isEmpty && !fwContained(t.fwWords, spanFWWords) { continue }
                    // No term may add a function word the span did not hold.
                    if t.fwCount > spanFW { continue }
                    if let tfw = t.termFW, spanFW > tfw || 2 * spanFW >= size { continue }
                    if !phoneticMatch(t.codes, candCodes) { continue }
                    let termKey: String = t.spokenKey
                    // Digits must match exactly.
                    if digits(candKey) != digits(termKey) { continue }
                    if t.termFW != nil && size > 1 && size == t.termWords.count {
                        var swap: Bool = false
                        for (sw, tw) in zip(wordLow[i..<(i + size)], t.termWords) {
                            if sw != tw && commonWords.contains(sw) && jaroWinkler(sw, tw) < managedWordJW {
                                swap = true
                                break
                            }
                        }
                        if swap { continue }
                    }
                    let tight: Bool = t.strict || (t.termFW != nil && size == 1)
                    let denom: Double = Double(scalarCount(termKey) == 0 ? 1 : scalarCount(termKey))
                    let lr: Double = Double(scalarCount(candKey)) / denom
                    let lenLo: Double = tight ? managedLenLo : fuzzyLenLo
                    let lenHi: Double = tight ? managedLenHi : fuzzyLenHi
                    if !(lenLo <= lr && lr <= lenHi) { continue }
                    if t.termFW != nil && size < t.termWords.count && lr < managedMergeCover { continue }
                    let jw: Double = jaroWinkler(candKey, termKey)
                    let floorJW: Double = tight ? managedJW : fuzzyJW
                    if jw >= floorJW && jw > bestJW {
                        best = t.term
                        bestJW = jw
                    }
                }
                if let b = best {
                    let start: Int = tokens[i].start
                    let end: Int = tokens[i + size - 1].end
                    replacements.append((start, end, cased(b, units, start)))
                    for k in i..<(i + size) { consumed[k] = true }
                }
            }
        }

        if replacements.isEmpty { return text }
        replacements.sort { (a: (Int, Int, String), b: (Int, Int, String)) -> Bool in
            if a.0 != b.0 { return a.0 < b.0 }
            if a.1 != b.1 { return a.1 < b.1 }
            return a.2 < b.2
        }
        var out: String = ""
        var pos: Int = 0
        for (start, end, rep) in replacements {
            out += utf16Slice(text, pos, start)
            out += rep
            pos = end
        }
        out += utf16Slice(text, pos)
        return out
    }

    // MARK: Managed (CRM) names

    /// The forms of a CRM name worth correcting towards, longest first: the
    /// name as stored, then with a colon tagline and trailing legal suffixes
    /// removed.
    public static func managedVariants(_ raw: String) -> [String] {
        let name: String = normalizeSpaces(raw)
        if name.isEmpty { return [] }
        var out: [String] = []
        var seen: Set<String> = []

        func add(_ vIn: String) {
            let v: String = normalizeSpaces(vIn).pyStrip(" ,;:-&.")
            let low: String = v.lowercased()
            if v.isEmpty || seen.contains(low) { return }
            if !v.contains(" ") && scalarCount(v) < managedMinTermLen { return }
            seen.insert(low)
            out.append(v)
        }

        add(name)
        let head: String = name.components(separatedBy: ":")[0]
        add(head)
        var words: [String] = head.pySplit
        while words.count > 1 && legalSuffixes.contains(words[words.count - 1].lowercased().pyStrip(".,")) {
            words.removeLast()
            add(words.joined(separator: " "))
        }
        return out
    }

    // MARK: Snippets

    /// Expand each snippet's trigger phrase into its body (verbatim, never recased).
    public static func applySnippets(_ text: String, snippets: [Snippet]) -> String {
        if text.isEmpty { return text }
        var pairs: [(String, String)] = []
        for s in snippets where !s.deleted {
            let trigger: String = normalizeSpaces(s.trigger)
            if scalarCount(trigger) < minPatternLength || s.body.isEmpty { continue }
            pairs.append((trigger, s.body))
        }
        return substitute(text, pairs, recase: false)
    }

    // MARK: Validation

    /// nil when the variant is acceptable, else the message to show the user.
    public static func validateSoundsLike(_ variantIn: String, term: String = "") -> String? {
        let variant: String = normalizeSpaces(variantIn)
        if variant.isEmpty { return "Enter what it sounds like." }
        if scalarCount(variant) < minPatternLength {
            return "Too short \u{2014} needs \(minPatternLength) characters or more, or it will match ordinary speech."
        }
        if !term.isEmpty && variant.lowercased() == term.pyStrip.lowercased() {
            return "That's the same as the word itself."
        }
        return nil
    }

    /// nil when the trigger is acceptable, else the message to show the user.
    public static func validateTrigger(_ triggerIn: String) -> String? {
        let trigger: String = normalizeSpaces(triggerIn)
        if trigger.isEmpty { return "Enter a trigger phrase." }
        if scalarCount(trigger) < minPatternLength {
            return "Too short \u{2014} needs \(minPatternLength) characters or more, or it will fire while you talk."
        }
        if reservedTriggers.contains(trigger.lowercased()) {
            return "\u{201C}\(trigger)\u{201D} is too common \u{2014} it would expand "
                + "every time you said it. Try a longer phrase."
        }
        return nil
    }

    // MARK: Double Metaphone (port of the Python `metaphone` 0.6 package)

    /// (primary, secondary) Double Metaphone codes. Internal: exposed so the
    /// tests can pin the encoder against the Python package's output.
    static func doubleMetaphone(_ word: String) -> (String, String) {
        DoubleMetaphone.encode(word)
    }

    /// One step of the encoder: the code(s) to append and how far to advance.
    /// `three` mirrors the Python 3-tuple (separate primary and secondary
    /// codes); otherwise `p` goes to both.
    private struct DMNext {
        var p: String?
        var s: String?
        var three: Bool
        var step: Int

        static func two(_ code: String?, _ step: Int) -> DMNext {
            DMNext(p: code, s: nil, three: false, step: step)
        }

        static func pair(_ p: String?, _ s: String?, _ step: Int) -> DMNext {
            DMNext(p: p, s: s, three: true, step: step)
        }
    }

    /// Faithful to the Python implementation, including its quirk that
    /// `next` persists between characters: a character no rule handles (a
    /// digit, an apostrophe) re-applies the previous character's step.
    private struct DoubleMetaphone {
        let buffer: [Unicode.Scalar]
        let start: Int = 2
        let end: Int
        let slavo: Bool
        var position: Int
        var primary: String = ""
        var secondary: String = ""
        var next: DMNext = DMNext.two(nil, 1)

        static func encode(_ input: String) -> (String, String) {
            var enc: DoubleMetaphone = DoubleMetaphone(input)
            return enc.parse()
        }

        init(_ input: String) {
            var decoded: String = input.replacingOccurrences(of: "\u{C7}", with: "s")
            decoded = decoded.replacingOccurrences(of: "\u{E7}", with: "s")
            var normalized: [Unicode.Scalar] = []
            for u in decoded.decomposedStringWithCanonicalMapping.unicodeScalars
            where u.properties.generalCategory != .nonspacingMark {
                normalized.append(u)
            }
            var normalizedString: String.UnicodeScalarView = String.UnicodeScalarView()
            normalizedString.append(contentsOf: normalized)
            let upper: [Unicode.Scalar] = Array(String(normalizedString).uppercased().unicodeScalars)
            var hasW: Bool = false
            var hasK: Bool = false
            var hasCZ: Bool = false
            for (i, u) in upper.enumerated() {
                if u == "W" { hasW = true }
                if u == "K" { hasK = true }
                if u == "C" && i + 1 < upper.count && upper[i + 1] == "Z" { hasCZ = true }
            }
            self.slavo = hasW || hasK || hasCZ
            self.end = 2 + upper.count - 1
            let dash: Unicode.Scalar = "-"
            var buf: [Unicode.Scalar] = [dash, dash]
            buf.append(contentsOf: upper)
            buf.append(contentsOf: [dash, dash, dash, dash, dash, dash])
            self.buffer = buf
            self.position = 2
        }

        // MARK: buffer access (Python indexing and slicing)

        func ch(_ index: Int) -> String {
            var i: Int = index
            if i < 0 { i += buffer.count }
            if i < 0 || i >= buffer.count { return "" }
            return String(buffer[i])
        }

        func sl(_ a0: Int, _ b0: Int) -> String {
            let n: Int = buffer.count
            var a: Int = a0
            var b: Int = b0
            if a < 0 { a += n; if a < 0 { a = 0 } } else if a > n { a = n }
            if b < 0 { b += n; if b < 0 { b = 0 } } else if b > n { b = n }
            if a >= b { return "" }
            var v: String.UnicodeScalarView = String.UnicodeScalarView()
            v.append(contentsOf: buffer[a..<b])
            return String(v)
        }

        func isV(_ s: String) -> Bool { s == "A" || s == "E" || s == "I" || s == "O" || s == "U" || s == "Y" }

        // MARK: rules

        mutating func processInitialVowels() {
            next = DMNext.two(nil, 1)
            if position == start { next = DMNext.two("A", 1) }
        }

        mutating func processB() {
            next = DMNext.two("P", ch(position + 1) == "B" ? 2 : 1)
        }

        mutating func processC() {
            let p: Int = position
            let si: Int = start
            let germanicA: Bool = p > si + 1 && !isV(ch(p - 2)) && sl(p - 1, p + 2) == "ACH"
            let germanicB: Bool = ch(p + 2) != "I"
            let bacher: Bool = ["BACHER", "MACHER"].contains(sl(p - 2, p + 4))
            let germanicC: Bool = ch(p + 2) != "E" || bacher
            if germanicA && germanicB && germanicC {
                next = DMNext.two("K", 2)
            } else if p == si && sl(si, si + 6) == "CAESAR" {
                next = DMNext.two("S", 2)
            } else if sl(p, p + 4) == "CHIA" {
                next = DMNext.two("K", 2)
            } else if sl(p, p + 2) == "CH" {
                let greekA: Bool = ["HARAC", "HARIS"].contains(sl(p + 1, p + 6))
                let greekB: Bool = ["HOR", "HYM", "HIA", "HEM"].contains(sl(p + 1, p + 4))
                let chStart: Bool = p == si && (greekA || greekB) && sl(si, si + 5) != "CHORE"
                let g1: Bool = ["VAN ", "VON "].contains(sl(si, si + 4)) || sl(si, si + 3) == "SCH"
                let g2: Bool = ["ORCHES", "ARCHIT", "ORCHID"].contains(sl(p - 2, p + 4))
                let g3: Bool = ["T", "S"].contains(ch(p + 2))
                let before: Bool = ["A", "O", "U", "E"].contains(ch(p - 1)) || p == si
                let after: Bool = ["L", "R", "N", "M", "B", "H", "F", "V", "W"].contains(ch(p + 2))
                let germanicCH: Bool = g1 || g2 || g3 || (before && after)
                if p > si && sl(p, p + 4) == "CHAE" {
                    next = DMNext.pair("K", "X", 2)
                } else if chStart {
                    next = DMNext.two("K", 2)
                } else if germanicCH {
                    next = DMNext.two("K", 2)
                } else {
                    if p > si {
                        if sl(si, si + 2) == "MC" {
                            next = DMNext.two("K", 2)
                        } else {
                            next = DMNext.pair("X", "K", 2)
                        }
                    } else {
                        next = DMNext.two("X", 2)
                    }
                }
            } else if sl(p, p + 2) == "CZ" && sl(p - 2, p + 2) != "WICZ" {
                next = DMNext.pair("S", "X", 2)
            } else if sl(p + 1, p + 4) == "CIA" {
                next = DMNext.two("X", 3)
            } else if sl(p, p + 2) == "CC" && !(p == si + 1 && ch(si) == "M") {
                if ["I", "E", "H"].contains(ch(p + 2)) && sl(p + 2, p + 4) != "HU" {
                    if (p == si + 1 && ch(si) == "A") || ["UCCEE", "UCCES"].contains(sl(p - 1, p + 4)) {
                        next = DMNext.two("KS", 3)
                    } else {
                        next = DMNext.two("X", 3)
                    }
                } else {
                    next = DMNext.two("K", 2)
                }
            } else if ["CK", "CG", "CQ"].contains(sl(p, p + 2)) {
                next = DMNext.two("K", 2)
            } else if ["CI", "CE", "CY"].contains(sl(p, p + 2)) {
                if ["CIO", "CIE", "CIA"].contains(sl(p, p + 3)) {
                    next = DMNext.pair("S", "X", 2)
                } else {
                    next = DMNext.two("S", 2)
                }
            } else {
                if [" C", " Q", " G"].contains(sl(p + 1, p + 3)) {
                    next = DMNext.two("K", 3)
                } else if ["C", "K", "Q"].contains(ch(p + 1)) && !["CE", "CI"].contains(sl(p + 1, p + 3)) {
                    next = DMNext.two("K", 2)
                } else {
                    next = DMNext.two("K", 1)
                }
            }
        }

        mutating func processD() {
            let p: Int = position
            if sl(p, p + 2) == "DG" {
                if ["I", "E", "Y"].contains(ch(p + 2)) {
                    next = DMNext.two("J", 3)
                } else {
                    next = DMNext.two("TK", 2)
                }
            } else if ["DT", "DD"].contains(sl(p, p + 2)) {
                next = DMNext.two("T", 2)
            } else {
                next = DMNext.two("T", 1)
            }
        }

        mutating func processF() {
            next = DMNext.two("F", ch(position + 1) == "F" ? 2 : 1)
        }

        mutating func processG() {
            let p: Int = position
            let si: Int = start
            let gStartPair: [String] = ["ES", "EP", "EB", "EL", "EY", "IB", "IL", "IN", "IE", "EI", "ER"]
            let gNotDanger: Bool = !["DANGER", "RANGER", "MANGER"].contains(sl(si, si + 6))
            let gNotEI: Bool = !["E", "I"].contains(ch(p - 1))
            let gNotRGY: Bool = !["RGY", "OGY"].contains(sl(p - 1, p + 2))
            if ch(p + 1) == "H" {
                let parkerA: Bool = p > si + 1 && ["B", "H", "D"].contains(ch(p - 2))
                let parkerB: Bool = p > si + 2 && ["B", "H", "D"].contains(ch(p - 3))
                let parkerC: Bool = p > si + 3 && ["B", "H"].contains(ch(p - 4))
                let parkerRule: Bool = parkerA || parkerB || parkerC
                if p > si && !isV(ch(p - 1)) {
                    next = DMNext.two("K", 2)
                } else if p < si + 3 {
                    // 'ghislane', ghiradelli
                    if p == si {
                        if ch(p + 2) == "I" {
                            next = DMNext.two("J", 2)
                        } else {
                            next = DMNext.two("K", 2)
                        }
                    }
                } else if parkerRule {
                    next = DMNext.two(nil, 2)
                } else {
                    if p > si + 2 && ch(p - 1) == "U" && ["C", "G", "L", "R", "T"].contains(ch(p - 3)) {
                        next = DMNext.two("F", 2)
                    } else if p > si && ch(p - 1) != "I" {
                        next = DMNext.two("K", 2)
                    }
                }
            } else if ch(p + 1) == "N" {
                if p == si + 1 && isV(ch(si)) && !slavo {
                    next = DMNext.pair("KN", "N", 2)
                } else {
                    if sl(p + 2, p + 4) != "EY" && ch(p + 1) != "Y" && !slavo {
                        next = DMNext.pair("N", "KN", 2)
                    } else {
                        next = DMNext.two("KN", 2)
                    }
                }
            } else if sl(p + 1, p + 3) == "LI" && !slavo {
                next = DMNext.pair("KL", "L", 2)
            } else if p == si && (ch(p + 1) == "Y" || gStartPair.contains(sl(p + 1, p + 3))) {
                next = DMNext.pair("K", "J", 2)
            } else if (sl(p + 1, p + 3) == "ER" || ch(p + 1) == "Y") && gNotDanger && gNotEI && gNotRGY {
                next = DMNext.pair("K", "J", 2)
            } else if ["E", "I", "Y"].contains(ch(p + 1)) || ["AGGI", "OGGI"].contains(sl(p - 1, p + 3)) {
                if ["VON ", "VAN "].contains(sl(si, si + 4))
                    || sl(si, si + 3) == "SCH"
                    || sl(p + 1, p + 3) == "ET" {
                    next = DMNext.two("K", 2)
                } else {
                    if sl(p + 1, p + 5) == "IER " {
                        next = DMNext.two("J", 2)
                    } else {
                        next = DMNext.pair("J", "K", 2)
                    }
                }
            } else if ch(p + 1) == "G" {
                next = DMNext.two("K", 2)
            } else {
                next = DMNext.two("K", 1)
            }
        }

        mutating func processH() {
            let p: Int = position
            if (p == start || isV(ch(p - 1))) && isV(ch(p + 1)) {
                next = DMNext.two("H", 2)
            } else {
                next = DMNext.two(nil, 1)
            }
        }

        mutating func processJ() {
            let p: Int = position
            let si: Int = start
            let step: Int = ch(p + 1) == "J" ? 2 : 1
            if sl(p, p + 4) == "JOSE" || sl(si, si + 4) == "SAN " {
                if (p == si && ch(p + 4) == " ") || sl(si, si + 4) == "SAN " {
                    next = DMNext.two("H", step)
                } else {
                    next = DMNext.pair("J", "H", step)
                }
            } else if p == si && sl(p, p + 4) != "JOSE" {
                next = DMNext.pair("J", "A", step)
            } else {
                if isV(ch(p - 1)) && !slavo && ["A", "O"].contains(ch(p + 1)) {
                    next = DMNext.pair("J", "H", step)
                } else {
                    if p == end {
                        next = DMNext.pair("J", " ", step)
                    } else {
                        if !["L", "T", "K", "S", "N", "M", "B", "Z"].contains(ch(p + 1))
                            && !["S", "K", "L"].contains(ch(p - 1)) {
                            next = DMNext.two("J", step)
                        } else {
                            next = DMNext.two(nil, step)
                        }
                    }
                }
            }
        }

        mutating func processK() {
            next = DMNext.two("K", ch(position + 1) == "K" ? 2 : 1)
        }

        mutating func processL() {
            let p: Int = position
            if ch(p + 1) == "L" {
                let spanishA: Bool = p == end - 2 && ["ILLO", "ILLA", "ALLE"].contains(sl(p - 1, p + 3))
                let endsAO: Bool = ["AS", "OS"].contains(sl(end - 1, end + 1)) || ["A", "O"].contains(ch(end))
                let spanishB: Bool = endsAO && sl(p - 1, p + 3) == "ALLE"
                if spanishA || spanishB {
                    next = DMNext.pair("L", "", 2)
                } else {
                    next = DMNext.two("L", 2)
                }
            } else {
                next = DMNext.two("L", 1)
            }
        }

        mutating func processM() {
            let p: Int = position
            if (sl(p + 1, p + 4) == "UMB" && (p + 1 == end || sl(p + 2, p + 4) == "ER"))
                || ch(p + 1) == "M" {
                next = DMNext.two("M", 2)
            } else {
                next = DMNext.two("M", 1)
            }
        }

        mutating func processN() {
            next = DMNext.two("N", ch(position + 1) == "N" ? 2 : 1)
        }

        mutating func processP() {
            let p: Int = position
            if ch(p + 1) == "H" {
                next = DMNext.two("F", 2)
            } else if ch(p + 1) == "P" || ch(p + 1) == "B" {
                next = DMNext.two("P", 2)
            } else {
                next = DMNext.two("P", 1)
            }
        }

        mutating func processQ() {
            next = DMNext.two("K", ch(position + 1) == "Q" ? 2 : 1)
        }

        mutating func processR() {
            let p: Int = position
            let step: Int = ch(p + 1) == "R" ? 2 : 1
            if p == end && !slavo && sl(p - 2, p) == "IE" && !["ME", "MA"].contains(sl(p - 4, p - 2)) {
                next = DMNext.pair("", "R", step)
            } else {
                next = DMNext.two("R", step)
            }
        }

        mutating func processS() {
            let p: Int = position
            let si: Int = start
            if ["ISL", "YSL"].contains(sl(p - 1, p + 2)) {
                next = DMNext.two(nil, 1)
            } else if p == si && sl(si, si + 5) == "SUGAR" {
                next = DMNext.pair("X", "S", 1)
            } else if sl(p, p + 2) == "SH" {
                if ["HEIM", "HOEK", "HOLM", "HOLZ"].contains(sl(p + 1, p + 5)) {
                    next = DMNext.two("S", 2)
                } else {
                    next = DMNext.two("X", 2)
                }
            } else if ["SIO", "SIA"].contains(sl(p, p + 3)) || sl(p, p + 4) == "SIAN" {
                if !slavo {
                    next = DMNext.pair("S", "X", 3)
                } else {
                    next = DMNext.two("S", 3)
                }
            } else if (p == si && ["M", "N", "L", "W"].contains(ch(p + 1))) || ch(p + 1) == "Z" {
                next = DMNext.pair("S", "X", ch(p + 1) == "Z" ? 2 : 1)
            } else if sl(p, p + 2) == "SC" {
                if ch(p + 2) == "H" {
                    if ["OO", "ER", "EN", "UY", "ED", "EM"].contains(sl(p + 3, p + 5)) {
                        if ["ER", "EN"].contains(sl(p + 3, p + 5)) {
                            next = DMNext.pair("X", "SK", 3)
                        } else {
                            next = DMNext.two("SK", 3)
                        }
                    } else {
                        if p == si && !isV(ch(si + 3)) && ch(si + 3) != "W" {
                            next = DMNext.pair("X", "S", 3)
                        } else {
                            next = DMNext.two("X", 3)
                        }
                    }
                } else if ["I", "E", "Y"].contains(ch(p + 2)) {
                    next = DMNext.two("S", 3)
                } else {
                    next = DMNext.two("SK", 3)
                }
            } else if p == end && ["AI", "OI"].contains(sl(p - 2, p)) {
                next = DMNext.pair("", "S", 1)
            } else {
                next = DMNext.two("S", (ch(p + 1) == "S" || ch(p + 1) == "Z") ? 2 : 1)
            }
        }

        mutating func processT() {
            let p: Int = position
            let si: Int = start
            if sl(p, p + 4) == "TION" {
                next = DMNext.two("X", 3)
            } else if ["TIA", "TCH"].contains(sl(p, p + 3)) {
                next = DMNext.two("X", 3)
            } else if sl(p, p + 2) == "TH" || sl(p, p + 3) == "TTH" {
                if ["OM", "AM"].contains(sl(p + 2, p + 4))
                    || ["VON ", "VAN "].contains(sl(si, si + 4))
                    || sl(si, si + 3) == "SCH" {
                    next = DMNext.two("T", 2)
                } else {
                    next = DMNext.pair("0", "T", 2)
                }
            } else if ch(p + 1) == "T" || ch(p + 1) == "D" {
                next = DMNext.two("T", 2)
            } else {
                next = DMNext.two("T", 1)
            }
        }

        mutating func processV() {
            next = DMNext.two("F", ch(position + 1) == "V" ? 2 : 1)
        }

        mutating func processW() {
            let p: Int = position
            let si: Int = start
            let wEnd: Bool = p == end && isV(ch(p - 1))
            let wSki: Bool = ["EWSKI", "EWSKY", "OWSKI", "OWSKY"].contains(sl(p - 1, p + 4))
            let wPolish: Bool = wEnd || wSki || sl(si, si + 3) == "SCH"
            if sl(p, p + 2) == "WR" {
                next = DMNext.two("R", 2)
            } else if p == si && (isV(ch(p + 1)) || sl(p, p + 2) == "WH") {
                if isV(ch(p + 1)) {
                    next = DMNext.pair("A", "F", 1)
                } else {
                    next = DMNext.two("A", 1)
                }
            } else if wPolish {
                next = DMNext.pair("", "F", 1)
            } else if ["WICZ", "WITZ"].contains(sl(p, p + 4)) {
                next = DMNext.pair("TS", "FX", 4)
            } else {
                next = DMNext.two(nil, 1)
            }
        }

        mutating func processX() {
            let p: Int = position
            var code: String? = nil
            if !(p == end
                 && (["IAU", "EAU"].contains(sl(p - 3, p)) || ["AU", "OU"].contains(sl(p - 2, p)))) {
                code = "KS"
            }
            next = DMNext.two(code, (ch(p + 1) == "C" || ch(p + 1) == "X") ? 2 : 1)
        }

        mutating func processZ() {
            let p: Int = position
            let step: Int = (ch(p + 1) == "Z" || ch(p + 1) == "H") ? 2 : 1
            if ch(p + 1) == "H" {
                next = DMNext.two("J", step)
            } else if ["ZO", "ZI", "ZA"].contains(sl(p + 1, p + 3))
                        || (slavo && p > start && ch(p - 1) != "T") {
                next = DMNext.pair("S", "TS", step)
            } else {
                next = DMNext.two("S", step)
            }
        }

        mutating func parse() -> (String, String) {
            position = start
            // skip these silent letters when at start of word
            if ["GN", "KN", "PN", "WR", "PS"].contains(sl(start, start + 2)) { position += 1 }
            // Initial 'X' is pronounced 'Z' e.g. 'Xavier'
            if ch(start) == "X" {
                primary = "S"
                secondary = "S"
                position += 1
            }
            while position <= end {
                let c: String = ch(position)
                if isV(c) {
                    processInitialVowels()
                } else if c == " " {
                    position += 1
                    continue
                } else if c == "B" { processB()
                } else if c == "C" { processC()
                } else if c == "D" { processD()
                } else if c == "F" { processF()
                } else if c == "G" { processG()
                } else if c == "H" { processH()
                } else if c == "J" { processJ()
                } else if c == "K" { processK()
                } else if c == "L" { processL()
                } else if c == "M" { processM()
                } else if c == "N" { processN()
                } else if c == "P" { processP()
                } else if c == "Q" { processQ()
                } else if c == "R" { processR()
                } else if c == "S" { processS()
                } else if c == "T" { processT()
                } else if c == "V" { processV()
                } else if c == "W" { processW()
                } else if c == "X" { processX()
                } else if c == "Z" { processZ()
                }
                if !next.three {
                    if let code = next.p, !code.isEmpty {
                        primary += code
                        secondary += code
                    }
                } else {
                    if let code = next.p, !code.isEmpty { primary += code }
                    if let code = next.s, !code.isEmpty { secondary += code }
                }
                position += next.step
            }
            if primary == secondary { secondary = "" }
            return (primary, secondary)
        }
    }
}
