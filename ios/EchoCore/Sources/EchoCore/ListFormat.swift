import Foundation

/// Port of list_format.py: turn a clearly enumerated dictation ("first ...
/// second ... third ...", "bullet point one ...", or "here are the three
/// things: milk, bread and eggs") into a real numbered or bulleted list.
///
/// All offsets are UTF-16 offsets (what NSRegularExpression reports); the
/// private `slice` helper does Python-style slicing on them.
public enum ListFormat {

    // MARK: Python-style helpers

    /// text[a:b] on UTF-16 offsets, with Python's clamping.
    private static func slice(_ s: String, _ a: Int, _ b: Int? = nil) -> String {
        let ns: NSString = NSString(string: s)
        let n: Int = ns.length
        var lo: Int = a
        var hi: Int = b ?? n
        if lo < 0 { lo = max(0, lo + n) }
        if hi < 0 { hi = max(0, hi + n) }
        lo = min(lo, n)
        hi = min(hi, n)
        if lo >= hi { return "" }
        return ns.substring(with: NSRange(location: lo, length: hi - lo))
    }

    private static func utf16Length(_ s: String) -> Int { s.utf16.count }

    private static func scalarString(_ scalars: [Unicode.Scalar]) -> String {
        var v: String.UnicodeScalarView = String.UnicodeScalarView()
        v.append(contentsOf: scalars)
        return String(v)
    }

    /// s[:-1] by code point.
    private static func dropLastScalar(_ s: String) -> String {
        var scalars: [Unicode.Scalar] = Array(s.unicodeScalars)
        if !scalars.isEmpty { scalars.removeLast() }
        return scalarString(scalars)
    }

    private static func lastScalar(_ s: String) -> Unicode.Scalar? { s.unicodeScalars.last }

    private static func scalarIn(_ u: Unicode.Scalar?, _ set: String) -> Bool {
        guard let u = u else { return false }
        return set.unicodeScalars.contains(u)
    }

    /// Python `longest first, stable`.
    private static func byLengthDescending(_ items: [String]) -> [String] {
        let indexed: [(Int, String)] = Array(items.enumerated()).map { ($0.offset, $0.element) }
        let sorted: [(Int, String)] = indexed.sorted { (a: (Int, String), b: (Int, String)) -> Bool in
            let la: Int = a.1.unicodeScalars.count
            let lb: Int = b.1.unicodeScalars.count
            if la != lb { return la > lb }
            return a.0 < b.0
        }
        return sorted.map { $0.1 }
    }

    /// _cap: upper-case the first character only when it is lower case.
    private static func cap(_ s: String) -> String {
        var scalars: [Unicode.Scalar] = Array(s.unicodeScalars)
        guard let first = scalars.first, first.properties.isLowercase else { return s }
        scalars.removeFirst()
        return String(first).uppercased() + scalarString(scalars)
    }

    private static func isAllWhitespace(_ s: String) -> Bool { s.pyStrip.isEmpty }

    // MARK: Markers

    private static let ordinals: [(String, Int)] = [
        ("first", 1), ("firstly", 1),
        ("second", 2), ("secondly", 2),
        ("third", 3), ("thirdly", 3),
        ("fourth", 4), ("fourthly", 4),
        ("fifth", 5), ("fifthly", 5),
        ("sixth", 6), ("sixthly", 6),
        ("seventh", 7), ("eighth", 8), ("ninth", 9), ("tenth", 10),
    ]
    private static let ordinalMap: [String: Int] = Dictionary(uniqueKeysWithValues: ordinals)
    private static let numberWords: [(String, Int)] = [
        ("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5),
        ("six", 6), ("seven", 7), ("eight", 8), ("nine", 9), ("ten", 10),
    ]
    private static let numberWordMap: [String: Int] = Dictionary(uniqueKeysWithValues: numberWords)
    private static let closers: [String] = ["lastly", "finally", "last of all", "last but not least"]

    private static let numAlt: String =
        byLengthDescending(numberWords.map { $0.0 }).joined(separator: "|") + #"|\d{1,2}"#

    private static let posWords: String =
        "first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|next|last|final"

    private static let bulletAlt: String = {
        let numbered: String = #"bullet(?:\s+point)?(?:\s+number)?\s+(?:"# + numAlt + ")"
        let positional: String = #"(?:the\s+)?(?:"# + posWords + #")\s+bullet(?:\s+point)?"#
            + #"(?:\s+(?:is|would\s+be|will\s+be))?"#
        let parts: [String] = [
            #"(?:another|next|new)\s+bullet(?:\s+point)?"#,
            numbered,
            positional,
            #"bullet\s+point"#,
        ]
        return parts.joined(separator: "|")
    }()

    private static let ordNounAlt: String =
        #"(?:the\s+)?(?:"# + posWords + #")\s+(?:thing|point|item|one|step|reason)"#
        + #"\s+(?:is|would\s+be|will\s+be)"#

    private static let markerAlt: String = {
        var parts: [String] = [bulletAlt, ordNounAlt, "first of all", "first off"]
        parts += byLengthDescending(ordinals.map { $0.0 })
        parts.append(#"number\s+(?:"# + numAlt + ")")
        parts += closers.map { PyRegex.escape($0) }
        return parts.joined(separator: "|")
    }()

    // group 1 separator, 2 connective, 3 marker, 4 punctuation
    private static let markerRE: PyRegex = PyRegex(
        [
            #"(^|[.!?;:,]\s+|\n+|\s+)"#,
            #"((?:(?:and|then|also|but|so|now|next|okay|ok|right|for|like)\s*,?\s+)*)"#,
            #"("#, markerAlt, #")\b(\s*[,:])?"#,
        ].joined(),
        [.caseInsensitive])

    private static let announce: PyRegex = PyRegex(
        [
            #"\b(?:here(?:'s|s| is| are)|there (?:is|are|were)|these are|those are"#,
            #"|the following|as follows|a list of|list of"#,
            #"|(?:start|make|do|write|begin|got|have)\s+a\s+(?:quick\s+|short\s+)?list"#,
            #"|list (?:for|of)"#,
            #"|(?:to|me|i'll|i will|let's|let us|gonna|going to) list"#,
            #"|(?:a )?(?:couple(?: of)?|few|number of|handful of|bunch of) "#,
            #"(?:things|reasons|steps|points|items|bits|tasks|ideas)"#,
            #"|(?:two|three|four|five|six|seven|eight|nine|ten|\d+)\s+"#,
            #"(?:things|reasons|steps|points|items|options|problems|issues|changes)"#,
            #"|(?:things|reasons|steps|points|items) (?:are|to do|i need|we need|i want)"#,
            #")\b"#,
        ].joined(),
        [.caseInsensitive])

    private static let sentenceEnd: PyRegex = PyRegex(#"[.!?](?:["'”’)\]]+)?(?=\s|$)"#)
    private static let minItemWords: Int = 2
    private static let announceReach: Int = 8

    private static let hanging: Set<String> = [
        "a", "an", "the", "and", "or", "but", "for", "to", "of", "with", "about",
        "from", "in", "on", "at", "by", "into", "onto", "than", "that", "which",
        "who", "my", "your", "our", "their", "his", "her", "its", "this", "these",
        "those", "is", "are", "was", "were", "be", "get", "got", "have", "has",
    ]

    private static let wordsRE: PyRegex = PyRegex(#"[A-Za-z']+"#)

    private static func lastSentence(_ text: String) -> String {
        let parts: [String] = sentenceEnd.split(text.pyStrip)
        guard let last = parts.last else { return text }
        if !last.pyStrip.isEmpty { return last }
        return parts.count > 1 ? parts[parts.count - 2] : text
    }

    private static func announced(_ lead: String) -> Bool {
        if lead.isEmpty { return false }
        let sentence: String = lastSentence(lead)
        var lastMatch: PyMatch? = nil
        for m in announce.finditer(sentence) { lastMatch = m }
        guard let last = lastMatch else { return false }
        return slice(sentence, last.end).pySplit.count <= announceReach
    }

    private static func lastWord(_ text: String) -> String {
        let words: [String] = wordsRE.findall(text)
        return words.last?.lowercased() ?? ""
    }

    private static let exampleTail: PyRegex = PyRegex(
        #"(?:sort of thing|kind of thing|or something|or whatever|etc|and so on|and stuff)"#,
        [.caseInsensitive])

    // MARK: Marker kinds

    private enum Kind { case ord, num, bullet, close }

    /// A marker's position: a number, "next" (takes the next slot) or none.
    private enum Slot: Equatable {
        case none
        case next
        case number(Int)
    }

    private struct Mark {
        var sep: Int
        var item: Int
        var body: Int
        var idx: Slot
        var kind: Kind
        var bare: Bool
    }

    /// Python `_num`: int(word) if word.isdigit() else _NUMBER_WORDS.get(word).
    private static func numValue(_ word: String) -> Int? {
        if !word.isEmpty && word.unicodeScalars.allSatisfy({ $0.value >= 48 && $0.value <= 57 }) {
            return Int(word)
        }
        return numberWordMap[word]
    }

    private static func markerKind(_ word: String) -> (Slot, Kind) {
        let w: String = word.lowercased().pySplit.joined(separator: " ")
        var words: [String] = w.pySplit
        if words.isEmpty { return (.none, .ord) }
        if words[0] == "the" { words.removeFirst() }
        if words.isEmpty { return (.none, .ord) }
        let head: String = words[0]

        func position() -> Slot {
            if let o = ordinalMap[head] { return .number(o) }
            if head == "last" || head == "final" { return .none }
            return .next
        }

        if head == "number" {
            if words.count > 1, let n = numValue(words[1]) { return (.number(n), .num) }
            return (.none, .num)
        }
        if words.contains("bullet") {
            if let n = numValue(words[words.count - 1]), n != 0 { return (.number(n), .bullet) }
            return (position(), .bullet)
        }
        if words.count > 2 && ["thing", "point", "item", "one", "step", "reason"].contains(words[1]) {
            return (position(), .num)
        }
        if w == "first of all" || w == "first off" { return (.number(1), .ord) }
        if closers.contains(w) { return (.none, .close) }
        if let o = ordinalMap[w] { return (.number(o), .ord) }
        return (.none, .ord)
    }

    /// (location, length) of a capture group, nil when it did not take part.
    private static func groupSpan(_ m: PyMatch, _ g: Int) -> (Int, Int)? {
        guard g < m.result.numberOfRanges else { return nil }
        let r: NSRange = m.result.range(at: g)
        if r.location == NSNotFound { return nil }
        return (r.location, r.length)
    }

    private static func markers(_ text: String) -> [Mark] {
        var marks: [Mark] = []
        for m in markerRE.finditer(text) {
            let (idx, kind): (Slot, Kind) = markerKind(m.group(3) ?? "")
            let sepText: String = m.group(1) ?? ""
            let bare: Bool = !sepText.isEmpty && sepText.pyStrip.isEmpty
            // A bare-space separator is only believable in front of an explicit marker.
            if bare && (kind == .ord || kind == .close) { continue }
            let g4: String = m.group(4) ?? ""
            let drop: Bool = !g4.isEmpty || kind == .num || kind == .bullet

            let sepSpan: (Int, Int) = groupSpan(m, 1) ?? (m.start, 0)
            let itemStart: Int = (groupSpan(m, 2)?.0) ?? (sepSpan.0 + sepSpan.1)
            let g3: (Int, Int) = groupSpan(m, 3) ?? (m.end, 0)
            var bodyStart: Int = g3.0
            if drop {
                if !g4.isEmpty, let s4 = groupSpan(m, 4) {
                    bodyStart = s4.0 + s4.1
                } else {
                    bodyStart = g3.0 + g3.1
                }
            }
            marks.append(Mark(sep: sepSpan.0, item: itemStart, body: bodyStart,
                              idx: idx, kind: kind, bare: bare))
        }
        return marks
    }

    // MARK: Item shape

    private static let subjectRE: PyRegex = PyRegex(
        #"^(?:i|i'm|i've|i'll|i'd|we|we're|you|you're|they|they're|he|she|it|"#
        + #"it's|there|this|that|these|those|my|our)\b"#, [.caseInsensitive])
    private static let verbRE: PyRegex = PyRegex(
        #"\b(?:is|are|was|were|am|be|been|want|wants|need|needs|have|has|had|"#
        + #"will|would|can|could|should|must|do|does|did|think|make|makes|get|"#
        + #"gets|go|goes|going)\b"#, [.caseInsensitive])

    private static func isSentence(_ item: String) -> Bool {
        item.pySplit.count >= 3 && (subjectRE.search(item) != nil || verbRE.search(item) != nil)
    }

    private static let loneI: PyRegex = PyRegex(#"(?<![\w.'])i(?=\s|'[a-z])"#)

    private static func fixLoneI(_ item: String) -> String { loneI.sub(item, "I") }

    private static func numbered(_ text: String) -> String? {
        let marks: [Mark] = markers(text)
        if marks.isEmpty { return nil }
        for bullets in [true, false] {
            if let out = buildRun(text, marks, bullets), !out.isEmpty { return out }
        }
        return nil
    }

    private static func buildRun(_ text: String, _ marks: [Mark], _ bullets: Bool) -> String? {
        var run: [Mark] = []
        var expect: Int = 1
        for mk in marks {
            if mk.kind != .close && (mk.kind == .bullet) != bullets { continue }
            let idx: Int
            switch mk.idx {
            case .none:
                // "finally" only ever closes a run
                if run.isEmpty { continue }
                idx = expect
            case .next:
                idx = expect
            case .number(let n):
                idx = n
            }
            // "first, so like number one, I want ...": the same slot said twice.
            if !run.isEmpty && idx == expect - 1 && mk.kind != .close {
                let prev: Mark = run[run.count - 1]
                if slice(text, prev.body, mk.sep).pySplit.count <= 3 {
                    var replaced: Mark = prev
                    replaced.body = mk.body
                    run[run.count - 1] = replaced
                    continue
                }
            }
            if idx != expect { continue }
            run.append(mk)
            expect += 1
        }
        if run.count < 2 { return nil }

        let lead: String = slice(text, 0, run[0].item).pyRStrip()
        let isAnnounced: Bool = announced(lead)
        let explicit: Bool = run.allSatisfy { $0.kind == .num || $0.kind == .bullet || $0.kind == .close }
        if run.count < 3 && !isAnnounced && !explicit { return nil }
        if run.contains(where: { $0.bare }) && !isAnnounced { return nil }

        var bodies: [String] = []
        for (i, mk) in run.enumerated() {
            let end: Int = i + 1 < run.count ? run[i + 1].sep : utf16Length(text)
            bodies.append(slice(text, mk.body, end).pyStrip.pyStrip(",;"))
        }
        if bodies.contains(where: { $0.pySplit.count < minItemWords }) { return nil }
        if bodies.contains(where: { exampleTail.match($0) != nil }) { return nil }

        // Anything after the last item's full stop is the user carrying on.
        var tail: String = ""
        let allButLast: [String] = Array(bodies.dropLast())
        if allButLast.allSatisfy({ sentenceEnd.search(dropLastScalar($0)) == nil }) {
            let lastBody: String = bodies[bodies.count - 1]
            if let cut = sentenceEnd.search(lastBody) {
                let after: String = slice(lastBody, cut.end).pyStrip
                if !after.isEmpty {
                    tail = after
                    bodies[bodies.count - 1] = slice(lastBody, 0, cut.end)
                }
            }
        }

        let items: [String] = finishItems(bodies, bullets)
        let colon: Bool = isAnnounced || (explicit && !lead.isEmpty && !scalarIn(lastScalar(lead), ".!?"))
        return assemble(lead, items, tail, colon)
    }

    // MARK: Bulleted list

    private static let fillerItems: Set<String> = [
        "you know", "i mean", "like", "sort of", "kind of", "i guess", "i think",
        "and stuff", "or something", "or whatever", "basically", "actually",
        "so yeah", "yeah", "obviously", "honestly", "literally", "right", "okay",
        "ok", "well", "so", "um", "uh", "er", "also", "then", "too", "plus",
        "everything", "and everything", "etc", "and so on",
    ]
    private static let fillerOpeners: [String] = ["you know ", "i mean ", "like ", "sort of ", "kind of "]
    private static let clauseOpeners: Set<String> = [
        "that", "which", "who", "whose", "whom", "but", "so", "because", "cause",
    ]

    private static func isSeriesItem(_ item: String) -> Bool {
        let words: [String] = wordsRE.findall(item.lowercased())
        guard let first = words.first, let last = words.last else { return false }
        let bare: String = words.joined(separator: " ")
        if fillerItems.contains(bare) { return false }
        let padded: String = bare + " "
        if fillerOpeners.contains(where: { padded.hasPrefix($0) }) { return false }
        return !clauseOpeners.contains(first) && !hanging.contains(last)
    }

    private static let leadingConj: PyRegex = PyRegex(#"^(?:and|or)\s+(?=\S)"#, [.caseInsensitive])
    private static let innerConj: PyRegex = PyRegex(#"\s+(?:and|or)\s+"#, [.caseInsensitive])
    private static let maxBulletWords: Int = 8

    private static func trimStop(_ itemIn: String) -> String {
        let item: String = itemIn.pyRStrip()
        return item.hasSuffix(".") ? dropLastScalar(item).pyRStrip() : item
    }

    private static func splitFinalConjunction(_ partsIn: [String]) -> [String]? {
        var parts: [String] = partsIn
        guard let last = parts.last else { return nil }
        let stripped: String = leadingConj.sub(last, "")
        if stripped != last {
            parts[parts.count - 1] = stripped
            return parts
        }
        var splitAt: PyMatch? = nil
        for m in innerConj.finditer(last) { splitAt = m }
        guard let sp = splitAt else { return nil }
        parts.removeLast()
        parts.append(slice(last, 0, sp.start).pyStrip)
        parts.append(slice(last, sp.end).pyStrip)
        return parts.allSatisfy({ !$0.isEmpty }) ? parts : nil
    }

    private static let seriesStart: PyRegex = PyRegex(#"[:.]\s+|:\s*"#)

    private static func bulleted(_ text: String) -> String? {
        for m in seriesStart.finditer(text) {
            let lead: String = slice(text, 0, m.start).pyRStrip()
            if !announced(lead) { continue }
            if (m.group(0) ?? "").hasPrefix(".") && hanging.contains(lastWord(lead)) { continue }
            let rest: String = slice(text, m.end)
            let stop: PyMatch? = sentenceEnd.search(rest)
            let series: String
            let after: String
            if let st = stop {
                series = slice(rest, 0, st.end - 1)
                after = slice(rest, st.end).pyStrip
            } else {
                series = rest
                after = ""
            }
            let rawParts: [String] = series.components(separatedBy: ",").map { $0.pyStrip }
            if rawParts.isEmpty || rawParts.contains(where: { $0.isEmpty }) { continue }
            guard let parts = splitFinalConjunction(rawParts), parts.count >= 3 else { continue }
            if parts.contains(where: { $0.pySplit.count > maxBulletWords }) { continue }
            if !parts.allSatisfy({ isSeriesItem($0) }) { continue }
            return assemble(lead, finishItems(parts, true), after, true)
        }
        return nil
    }

    private static func finishItems(_ bodies: [String], _ bullets: Bool) -> [String] {
        let texts: [String] = bodies.map { cap(fixLoneI(trimStop($0))) }
        let sentenceCount: Int = texts.filter { isSentence($0) }.count
        let stops: Bool = sentenceCount * 2 > texts.count
        var out: [String] = []
        for (i, original) in texts.enumerated() {
            var t: String = original
            if stops, let l = lastScalar(t), !scalarIn(l, "?!.") { t += "." }
            out.append((bullets ? "- " : "\(i + 1). ") + t)
        }
        return out
    }

    private static func assemble(_ leadIn: String, _ items: [String], _ tail: String,
                                 _ announcedFlag: Bool) -> String {
        var lead: String = leadIn.pyRStrip()
        if !lead.isEmpty && announcedFlag && !lead.hasSuffix(":") {
            if scalarIn(lastScalar(lead), ".,;") { lead = dropLastScalar(lead).pyRStrip() }
            if !lead.isEmpty && !scalarIn(lastScalar(lead), "?!") { lead += ":" }
        }
        var out: String = (lead.isEmpty ? "" : lead + "\n\n") + items.joined(separator: "\n")
        if !tail.isEmpty { out += "\n\n" + cap(tail) }
        return out
    }

    private static let alreadyListed: PyRegex = PyRegex(#"^\s*(?:\d+\.|-)\s"#, [.anchorsMatchLines])

    // MARK: Public

    /// Return `text` with a clearly-spoken list laid out, or unchanged.
    public static func format(_ text: String) -> String {
        if text.isEmpty || text.pySplit.count < 6 { return text }
        if text.contains("•") || alreadyListed.search(text) != nil { return text }
        let builders: [(String) -> String?] = [
            { (t: String) -> String? in numbered(t) },
            { (t: String) -> String? in bulleted(t) },
        ]
        for build in builders {
            if let out = build(text), !out.isEmpty, out != text { return out }
        }
        return text
    }
}
