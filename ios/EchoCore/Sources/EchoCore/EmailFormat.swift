import Foundation

/// Port of email_format.py (without the Windows-only `is_email_app` gate):
/// lay a dictated email out with a greeting line, body paragraph, sign-off and
/// name on their own lines. Words are never added or removed; with no
/// greeting and no sign-off the text comes back byte-identical.
///
/// All offsets are UTF-16 offsets (what NSRegularExpression reports).
public enum EmailFormat {

    // MARK: Helpers

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

    private static func scalarString(_ scalars: [Unicode.Scalar]) -> String {
        var v: String.UnicodeScalarView = String.UnicodeScalarView()
        v.append(contentsOf: scalars)
        return String(v)
    }

    private static func isAlpha(_ u: Unicode.Scalar) -> Bool {
        switch u.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter:
            return true
        default:
            return false
        }
    }

    private static func isAlnum(_ u: Unicode.Scalar) -> Bool {
        if isAlpha(u) { return true }
        switch u.properties.generalCategory {
        case .decimalNumber, .letterNumber, .otherNumber:
            return true
        default:
            return false
        }
    }

    private static func isSpace(_ u: Unicode.Scalar) -> Bool { u.properties.isWhitespace }

    private static let capFirstSkip: Set<Unicode.Scalar> = Set("\"'(\u{2018}\u{201c}".unicodeScalars)

    /// _cap_first: capitalise the first letter, skipping leading space/quotes.
    private static func capFirst(_ s: String) -> String {
        let scalars: [Unicode.Scalar] = Array(s.unicodeScalars)
        for (i, ch) in scalars.enumerated() {
            if isAlpha(ch) {
                if ch.properties.isLowercase {
                    return scalarString(Array(scalars[0..<i])) + String(ch).uppercased()
                        + scalarString(Array(scalars[(i + 1)...]))
                }
                return s
            }
            if !isSpace(ch) && !capFirstSkip.contains(ch) { return s }
        }
        return s
    }

    private static func bare(_ word: String) -> String {
        word.pyStrip(".,!?;:").replacingOccurrences(of: "\u{2019}", with: "'").lowercased()
    }

    private static func nameRange(_ m: PyMatch, _ name: String) -> NSRange? {
        let r: NSRange = m.result.range(withName: name)
        return r.location == NSNotFound ? nil : r
    }

    // MARK: Shapes

    private static let nameP: String = #"[A-Z][\w'’\-]*"#
    private static let honorific: String = #"(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof)\.?"#
    private static let person: String = [
        "(?:", honorific, #"\s+)?"#, nameP, #"(?:\s+"#, nameP, #"){0,2}"#,
    ].joined()
    private static let groupWords: [String] = ["all", "everyone", "everybody", "team", "guys", "folks", "there", "both"]
    private static let groupP: String =
        #"(?i:you\s+all|all\s+of\s+you|"# + groupWords.joined(separator: "|") + #")\b"#
    private static let addressee: String = [
        "(?:", groupP, #"|(?i:sir\s+or\s+madam|sir/madam)|"#,
        person, #"(?:\s+(?:and|&)\s+"#, person, ")?)",
    ].joined()
    private static let greetingWord: String =
        #"(?i:good\s+(?:morning|afternoon|evening)|hiya|hi|hello|"#
        + #"hey|dear|morning|afternoon|evening)"#

    private static let fixedAddressee: PyRegex = PyRegex(groupP + #"|(?i:sir\s+or\s+madam|sir/madam)"#)

    private static let greetingRE: PyRegex = PyRegex([
        #"\s*(?<greet>"#, greetingWord, #")\b"#,
        #"(?:\s*,?\s+(?<addr>"#, addressee, #"))?"#,
    ].joined())

    private static let notNames: Set<String> = [
        "i", "i'm", "im", "i've", "i'll", "i'd", "thanks", "thank", "just", "hope",
        "hoping", "please", "can", "could", "would", "will", "is", "are", "was",
        "do", "did", "does", "have", "has", "had", "so", "we", "we're", "we've",
        "we'll", "you", "your", "you're", "it", "it's", "its", "this", "that",
        "these", "those", "the", "a", "an", "sorry", "apologies", "great", "good",
        "quick", "following", "further", "as", "re", "regarding", "here", "there's",
        "yes", "no", "ok", "okay", "sure", "let", "let's", "my", "our", "what",
        "when", "where", "why", "how", "who", "any", "happy", "welcome",
        "congratulations", "congrats", "unfortunately", "hopefully", "also",
        "attached", "kind", "best", "many", "cheers", "regards", "not", "if",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday", "january", "february", "march", "april", "may", "june", "july",
        "august", "september", "october", "november", "december", "today",
        "tomorrow", "yesterday",
    ]
    private static let joiners: Set<String> = ["and", "&"]

    private static let strong: [String] = [
        "many thanks and kind regards", "many thanks and best regards",
        "thank you and kind regards", "thank you and best regards",
        "thanks and kind regards", "thanks and best regards", "thanks and regards",
        "with kind regards", "with best wishes", "with many thanks",
        "kindest regards", "warmest regards", "kind regards", "best regards",
        "warm regards", "many regards", "regards", "best wishes", "warm wishes",
        "all the best", "yours sincerely", "yours faithfully", "yours truly",
        "sincerely", "many thanks", "with thanks",
    ]
    private static let weak: [String] = [
        "thank you very much", "thank you so much", "thanks very much",
        "thanks so much", "thanks in advance", "thanks again", "thanks a lot",
        "thank you", "thanks", "cheers", "speak soon", "talk soon", "take care",
        "best",
    ]
    private static let strongSet: Set<String> = Set(strong)
    private static let needsName: Set<String> = ["best"]

    private static let runOn: Set<String> = [
        "many thanks and kind regards", "many thanks and best regards",
        "thank you and kind regards", "thank you and best regards",
        "thanks and kind regards", "thanks and best regards", "thanks and regards",
        "kindest regards", "warmest regards", "kind regards", "best regards",
        "warm regards", "yours sincerely", "yours faithfully",
    ]
    private static let governs: Set<String> = [
        "my", "your", "our", "his", "her", "their", "its", "it", "the", "a", "an",
        "and", "or", "of", "to", "for", "with", "by", "as", "in", "like", "is",
        "was", "be", "just", "off", "send", "sends", "sent", "sending", "give",
        "gives", "gave", "giving", "pass", "passes", "passed", "passing", "extend",
        "extends", "convey", "conveys", "offer", "offers", "say", "says", "said",
        "saying", "sign", "signs", "signed", "signing", "end", "ends", "ended",
        "ending", "close", "closes", "closed", "closing", "write", "writes",
        "wrote", "writing", "put", "use", "uses", "used", "using", "no", "some",
        "any", "these", "those", "very", "many", "all", "kind", "kindest", "best",
        "warm", "warmest",
    ]
    private static let anywhere: Set<String> = Set(strong.filter { $0.contains("regards") }).union([
        "yours sincerely", "yours faithfully", "sincerely", "best wishes",
        "warm wishes", "with best wishes",
    ])

    private static func alt(_ phrases: [String]) -> String {
        phrases.map { $0.replacingOccurrences(of: " ", with: #"\s+"#) }.joined(separator: "|")
    }

    private static let signoffRE: PyRegex = {
        let parts: [String] = [
            #"(?<lead>^\s*|(?<=[.!?])\s+|,\s+|[ \t]*\n\s*|(?<=\w)\s+)"#,
            #"(?<phrase>(?i:"#, alt(strong), "|", alt(weak), #"))\b"#,
            #"(?<p1>\s*[,.!]?)"#,
            #"(?:\s+(?<name>"#, nameP, #"(?:\s+"#, nameP, #"){0,3}))?"#,
            #"(?<p2>\s*[.!]?)\s*$"#,
        ]
        return PyRegex(parts.joined())
    }()

    // MARK: Greeting

    private static let nonSpaceRun: PyRegex = PyRegex(#"\S+"#)
    private static let greetPunct: PyRegex = PyRegex(#"\s*([,.!:;])(?=\s|$)"#)

    /// (greeting line, addressee, body start) or nil.
    private static func splitGreeting(_ text: String) -> (String, String, Int)? {
        guard let m = greetingRE.match(text) else { return nil }
        let greet: String = m.group("greet") ?? ""
        guard let greetRange = nameRange(m, "greet") else { return nil }
        var end: Int = greetRange.location + greetRange.length
        var addr: String = ""
        if let raw = m.group("addr"), !raw.isEmpty, let addrRange = nameRange(m, "addr") {
            let words: [PyMatch] = nonSpaceRun.finditer(raw)
            var kept: Int = words.count
            if fixedAddressee.fullMatch(raw) == nil {
                // A capitalised run can carry the body's first word with it.
                kept = 0
                for (i, w) in words.enumerated() {
                    if notNames.contains(bare(w.group(0) ?? "")) { break }
                    kept = i + 1
                }
                while kept > 0 && joiners.contains(bare(words[kept - 1].group(0) ?? "")) { kept -= 1 }
            }
            if kept > 0 {
                end = addrRange.location + words[kept - 1].end
                addr = slice(raw, 0, words[kept - 1].end)
            }
        }
        if greet.lowercased() == "dear" && addr.isEmpty { return nil }
        let rest: String = slice(text, end)
        let punct: String
        let bodyStart: Int
        if let pm = greetPunct.match(rest) {
            punct = pm.group(1) ?? ""
            bodyStart = end + pm.end
        } else if rest.pyStrip.isEmpty {
            punct = ""
            bodyStart = text.utf16.count
        } else if !addr.isEmpty {
            punct = ""
            bodyStart = end
        } else {
            // "Morning meeting moved to three": a greeting word, nothing marks it as one.
            return nil
        }
        let line: String = capFirst(slice(text, 0, end).pyStrip) + (punct == "!" ? "!" : ",")
        return (line, addr, bodyStart)
    }

    // MARK: Sign-off

    private static func firstName(_ full: String) -> String {
        let parts: [String] = full.pySplit
        return parts.first.map { bare($0) } ?? ""
    }

    private static func leadKind(_ m: PyMatch, _ text: String) -> String {
        let lead: String = m.group("lead") ?? ""
        if lead.contains("\n") { return "newline" }
        if lead.hasPrefix(",") { return "comma" }
        if m.start == 0 { return "start" }
        if ".!?".contains(slice(text, m.start - 1, m.start)) && m.start >= 1 { return "sentence" }
        return "bare"
    }

    private static func prevWord(_ text: String, _ end: Int) -> String {
        let words: [String] = slice(text, 0, end).pySplit
        return words.last.map { bare($0) } ?? ""
    }

    private static func acceptSignoff(_ m: PyMatch, _ text: String, _ addresseeText: String,
                                      _ senderFirst: String, _ anywhereOnly: Bool) -> Bool {
        let phrase: String = (m.group("phrase") ?? "").lowercased().pySplit.joined(separator: " ")
        let kind: String = leadKind(m, text)
        let atStart: Bool = kind == "start"
        let afterComma: Bool = kind == "comma"
        let name: String = m.group("name") ?? ""
        let first: String = name.isEmpty ? "" : bare(name.pySplit.first ?? "")
        let isStrong: Bool = strongSet.contains(phrase)

        if anywhereOnly && !(!name.isEmpty && anywhere.contains(phrase)) { return false }
        if kind == "bare" {
            // Run straight on from the body: only an unmistakable close, or a
            // casual one followed by the sender's own name.
            if governs.contains(prevWord(text, m.start)) { return false }
            if !runOn.contains(phrase) && !(!isStrong && !first.isEmpty && first == senderFirst) {
                return false
            }
        }

        if !name.isEmpty {
            if notNames.contains(first) || groupWords.contains(first) { return false }
            if isStrong { return true }
            if !senderFirst.isEmpty { return first == senderFirst }
            if atStart || afterComma { return false }
            return first != firstName(addresseeText)
        }
        if needsName.contains(phrase) { return false }
        if afterComma && !isStrong { return false }
        if atStart && !isStrong { return false }
        return true
    }

    /// regex.search(text, pos): lookbehinds see the text before `pos`, and `^`
    /// only matches at the real start.
    private static func search(_ regex: PyRegex, _ text: String, from pos: Int) -> PyMatch? {
        let length: Int = text.utf16.count
        if pos > length { return nil }
        let range: NSRange = NSRange(location: pos, length: length - pos)
        guard let result = regex.regex.firstMatch(
            in: text, options: [.withTransparentBounds, .withoutAnchoringBounds], range: range)
        else { return nil }
        return PyMatch(text: text, result: result)
    }

    private static func findSignoff(_ text: String, _ addresseeText: String, _ senderFirst: String,
                                    _ anywhereOnly: Bool) -> PyMatch? {
        var pos: Int = 0
        while true {
            guard let m = search(signoffRE, text, from: pos) else { return nil }
            if acceptSignoff(m, text, addresseeText, senderFirst, anywhereOnly) { return m }
            pos = m.start + 1
            // Never start inside a surrogate pair.
            let units: [UInt16] = Array(text.utf16)
            if pos < units.count && UTF16.isTrailSurrogate(units[pos]) { pos += 1 }
        }
    }

    private static func signoffBlock(_ m: PyMatch) -> String {
        let phrase: String = capFirst((m.group("phrase") ?? "").pySplit.joined(separator: " "))
        let name: String = (m.group("name") ?? "").pySplit.joined(separator: " ")
        if !name.isEmpty { return phrase + ",\n" + name }
        let bang: Bool = ((m.group("p1") ?? "") + (m.group("p2") ?? "")).contains("!")
        return phrase + (bang ? "!" : "")
    }

    private static func closeBody(_ body: String, _ m: PyMatch, _ text: String) -> String {
        // "...tomorrow, kind regards": the comma or run-on was the break.
        let kind: String = leadKind(m, text)
        if (kind == "comma" || kind == "bare"), let l = body.unicodeScalars.last, isAlnum(l) {
            return body + "."
        }
        return body
    }

    private static let misheardClose: [String] = [
        "camera guards", "camera regards", "kind of regards", "kinda regards",
        "kinder regards", "kind regard", "kine regards", "kind guards",
    ]
    private static let misheardRE: PyRegex = {
        let parts: [String] = [
            #"(?<lead>^\s*|(?<=[.!?])\s+|,\s+|\n\s*)"#,
            #"(?<phrase>(?i:"#, alt(misheardClose), #"))\b"#,
            #"(?<tail>\s*[,.!]?\s+"#, nameP, #"(?:\s+"#, nameP, #"){0,3}\s*[.!]?\s*)$"#,
        ]
        return PyRegex(parts.joined())
    }()

    private static func repairClose(_ text: String) -> String {
        guard let m = misheardRE.search(text), let phraseRange = nameRange(m, "phrase") else { return text }
        let lead: String = m.group("lead") ?? ""
        let kind: String = lead.pyStrip == "," ? "kind" : "Kind"
        return slice(text, 0, phraseRange.location) + kind + " regards" + (m.group("tail") ?? "")
    }

    // MARK: Public

    /// Lay out a dictated email. Unchanged when no greeting or sign-off.
    public static func formatEmail(_ input: String, senderName: String = "") -> String {
        if input.isEmpty || input.pyStrip.isEmpty { return input }
        let text: String = repairClose(input)
        let greeting: (String, String, Int)? = splitGreeting(text)
        let bodyStart: Int = greeting?.2 ?? 0
        let addresseeText: String = greeting?.1 ?? ""

        // Searched in the body alone, so a sign-off straight after the greeting
        // still finds its start-of-body lead.
        let rest: String = slice(text, bodyStart)
        let m: PyMatch? = findSignoff(rest, addresseeText, firstName(senderName), false)
        let signoff: String? = m.map { signoffBlock($0) }
        let bodyEnd: Int = m?.start ?? rest.utf16.count

        if greeting == nil && signoff == nil { return text }

        var body: String = slice(rest, 0, bodyEnd).pyStrip
        if let mm = m { body = closeBody(body, mm, rest) }
        body = capFirst(body)

        var parts: [String] = []
        for p in [greeting?.0 ?? "", body, signoff ?? ""] where !p.isEmpty { parts.append(p) }
        var out: String = parts.joined(separator: "\n\n")
        if greeting != nil && body.isEmpty && signoff == nil {
            out += "\n\n"   // just the greeting: leave the caret where the body goes
        }
        return out
    }

    /// Outside an email client: put an unmistakable letter close and the name
    /// after it on their own lines. Only the `anywhere` phrases, and only with a
    /// name. Everything else, greeting included, is left as spoken.
    public static func formatSignoff(_ input: String, senderName: String = "") -> String {
        if input.isEmpty || input.pyStrip.isEmpty { return input }
        let repaired: String = repairClose(input)
        guard let m = findSignoff(repaired, "", firstName(senderName), true) else { return input }
        let body: String = closeBody(slice(repaired, 0, m.start).pyRStrip(), m, repaired)
        let block: String = signoffBlock(m)
        return body.pyStrip.isEmpty ? block : body + "\n\n" + block
    }
}
