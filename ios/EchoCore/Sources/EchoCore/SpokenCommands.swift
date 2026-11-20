import Foundation

/// Port of spoken_commands.py: spoken symbol names become symbols ("slash
/// settings" -> "/settings"), spoken addresses collapse ("ryan dot murphy at
/// ftc dash ss dot com" -> "ryan.murphy@ftc-ss.com"), "fifty four percent" ->
/// "54%", "1.2 times speed" -> "1.2x speed". Ends by applying tech terms.
public enum SpokenCommands {

    // MARK: Address tables

    private static let tlds: Set<String> = Set(
        """
        com co uk org net io ai dev app gov edu info biz me tv eu ie de fr es nl ch se
        dk fi pl pt cz ca au nz jp cn br za shop site online store tech cloud email
        live news blog xyz agency group ltd plc solutions systems
        """.pySplit)

    private static let exts: Set<String> = Set(
        """
        pdf doc docx xls xlsx ppt pptx csv txt md rtf png jpg jpeg gif svg webp zip rar
        py js ts jsx tsx html htm css json yaml yml xml sql sh bat exe msi dll log
        mp3 mp4 wav mov avi psd ai eps
        """.pySplit)

    private static let sepAlt: String = #"(?:at\s+sign|at\s+symbol|underscore|hyphen|dash|dot|at)"#
    private static let sepSym: [String: String] = [
        "dot": ".", "dash": "-", "hyphen": "-", "underscore": "_", "at": "@",
        "atsign": "@", "atsymbol": "@",
    ]
    private static let labelSeps: Set<String> = [".", "-", "_"]

    private static let addrToken: String = #"[A-Za-z0-9]+(?:[\-._][A-Za-z0-9]+)*"#
    private static let addrRun: PyRegex = PyRegex(
        [#"(?<![\w@\-])("#, addrToken, #"(?:\s+"#, sepAlt, #"\s+"#, addrToken, #")+)(?![\w@\-])"#].joined(),
        [.caseInsensitive])
    private static let splitSep: PyRegex = PyRegex(#"\s+("# + sepAlt + #")\s+"#, [.caseInsensitive])

    private static let proseBeforeAt: Set<String> = Set(
        """
        a an and are as at back be been being but by call called can check contact did
        do does done email emailed find for found get go going got had has have he her
        here him his how i in is it its just look looked looking made make me meet met
        my no not now of off on one or order our out over post posted put see seen send
        sent she so staying start stay stop that the their them then there these they
        this those to try trying up us use used very was we went were what when where
        which who why will with work working would you your
        """.pySplit)

    /// Python `re.split` with ONE capture group: text pieces interleaved with
    /// the group text.
    private static func splitKeepingGroup(_ regex: PyRegex, _ s: String) -> [String] {
        var parts: [String] = []
        var last: String.Index = s.startIndex
        for m in regex.finditer(s) {
            guard let r = m.range() else { continue }
            parts.append(String(s[last..<r.lowerBound]))
            parts.append(m.group(1) ?? "")
            last = r.upperBound
        }
        parts.append(String(s[last...]))
        return parts
    }

    private static func rewriteAddress(_ m: PyMatch) -> String {
        let raw: String = m.group(1) ?? ""
        let parts: [String] = splitKeepingGroup(splitSep, raw)
        var words: [String] = []
        var seps: [String] = []
        for (i, p) in parts.enumerated() {
            if i % 2 == 0 {
                words.append(p)
            } else {
                seps.append(sepSym[p.lowercased().replacingOccurrences(of: " ", with: "")] ?? "")
            }
        }
        if seps.isEmpty || seps.contains("") { return raw }

        let n: Int = words.count
        let lastWord: String = words[n - 1]
        let lastWordLower: String = lastWord.lowercased()
        let lastIsDottedDomain: Bool = lastWord.contains(".") && !lastWord.hasPrefix(".")
        let known: Set<String> = tlds.union(exts)

        if lastIsDottedDomain {
            let dotted: [String] = lastWord.components(separatedBy: ".")
            if !known.contains(dotted[dotted.count - 1]) { return raw }
        } else if seps[seps.count - 1] != "." || !known.contains(lastWordLower) {
            return raw
        }

        var i: Int = n - 1
        if !lastIsDottedDomain {
            while i > 0 && labelSeps.contains(seps[i - 1]) { i -= 1 }
        }

        if i > 0 && seps[i - 1] == "@" {
            let atI: Int = i - 1
            var j: Int = atI
            while j > 0 && labelSeps.contains(seps[j - 1]) { j -= 1 }
            if lastIsDottedDomain || !(j == atI && proseBeforeAt.contains(words[j].lowercased())) {
                i = j
            }
        }

        if i == n - 1 { return raw }
        // A one-character leading label is prose; an email is exempt.
        let innerSeps: ArraySlice<String> = seps[i..<(n - 1)]
        if !innerSeps.contains("@") && words[i].unicodeScalars.count < 2 { return raw }

        var head: String = ""
        if i > 0 {
            head = words[0]
            if i > 1 {
                for k in 1..<i {
                    head += " " + parts[2 * k - 1] + " " + words[k]
                }
            }
            head += " " + parts[2 * i - 1] + " "
        }

        var addr: String = words[i]
        if i + 1 < n {
            for k in (i + 1)..<n {
                addr += seps[k - 1] + words[k]
            }
        }
        return head + addr.lowercased()
    }

    // MARK: Spoken numbers

    private static let numSmall: [(String, Int)] = [
        ("zero", 0), ("oh", 0), ("nought", 0), ("one", 1), ("two", 2), ("three", 3), ("four", 4),
        ("five", 5), ("six", 6), ("seven", 7), ("eight", 8), ("nine", 9), ("ten", 10),
        ("eleven", 11), ("twelve", 12), ("thirteen", 13), ("fourteen", 14), ("fifteen", 15),
        ("sixteen", 16), ("seventeen", 17), ("eighteen", 18), ("nineteen", 19),
        ("twenty", 20), ("thirty", 30), ("forty", 40), ("fourty", 40), ("fifty", 50),
        ("sixty", 60), ("seventy", 70), ("eighty", 80), ("ninety", 90),
    ]
    private static let numScale: [(String, Int)] = [("hundred", 100), ("thousand", 1000), ("million", 1_000_000)]
    private static let numSmallMap: [String: Int] = Dictionary(uniqueKeysWithValues: numSmall)
    private static let numScaleMap: [String: Int] = Dictionary(uniqueKeysWithValues: numScale)

    private static let numWord: String = {
        let all: [String] = numSmall.map { $0.0 } + numScale.map { $0.0 }
        let indexed: [(Int, String)] = Array(all.enumerated()).map { ($0.offset, $0.element) }
        let sorted: [(Int, String)] = indexed.sorted { (a: (Int, String), b: (Int, String)) -> Bool in
            if a.1.count != b.1.count { return a.1.count > b.1.count }
            return a.0 < b.0
        }
        return sorted.map { $0.1 }.joined(separator: "|")
    }()

    private static let numRun: String =
        "(?:" + numWord + #")(?:[\s\-]+(?:and[\s\-]+)?(?:"# + numWord + ")" + ")*"

    private static let tokenSplit: PyRegex = PyRegex(#"[\s\-]+"#)

    private static func wordsToNumber(_ phrase: String) -> Int? {
        var total: Int = 0
        var current: Int = 0
        var seen: Bool = false
        for tok in tokenSplit.split(phrase.pyStrip.lowercased()) {
            if tok.isEmpty || tok == "and" { continue }
            // Python ints never overflow; Swift's trap. A run long enough to
            // overflow ("hundred hundred hundred ...") is left as spoken.
            if let v = numSmallMap[tok] {
                let (sum, o) = current.addingReportingOverflow(v)
                if o { return nil }
                current = sum
                seen = true
            } else if let scale = numScaleMap[tok] {
                let (product, o1) = (current != 0 ? current : 1).multipliedReportingOverflow(by: scale)
                if o1 { return nil }
                if scale == 100 {
                    current = product
                } else {
                    let (sum, o2) = total.addingReportingOverflow(product)
                    if o2 { return nil }
                    total = sum
                    current = 0
                }
                seen = true
            } else {
                return nil
            }
        }
        if !seen { return nil }
        let (result, o) = total.addingReportingOverflow(current)
        return o ? nil : result
    }

    private static let percentWords: PyRegex = PyRegex(
        #"\b("# + numRun + #")[\s\-]+per\s?cent\b"#, [.caseInsensitive])
    private static let percentDigits: PyRegex = PyRegex(#"(\d)[\s\-]*per\s?cent\b"#, [.caseInsensitive])
    private static let currencyWords: PyRegex = PyRegex(
        #"([$£€])\s*("# + numRun + #")\b"#, [.caseInsensitive])

    // MARK: Times

    private static let numPat: String = #"\d+(?:,\d{3})*(?:\.\d+)?"#
    private static let timesArith: PyRegex = PyRegex(
        #"(?<![\w.])("# + numPat + #")[ \t]+times[ \t]+("# + numPat + #")(?![\w.]|\.\d)"#,
        [.caseInsensitive])
    private static let timesBy: PyRegex = PyRegex(
        #"\btimes[ \t]+by[ \t]+("# + numPat + #")(?![\w]|\.\d)"#, [.caseInsensitive])
    private static let timesDecimal: PyRegex = PyRegex(
        #"(?<![\w.])(\d+\.\d+)[ \t]+times\b"#, [.caseInsensitive])
    private static let compareWords: String =
        "faster|slower|quicker|more|less|fewer|bigger|smaller|larger|higher"
        + "|lower|longer|shorter|cheaper|better|worse|greater|as|speed|zoom"
    private static let timesCompare: PyRegex = PyRegex(
        #"(?<![\w.])(\d+)[ \t]+times(?=[ \t]+(?:"# + compareWords + #")\b)"#, [.caseInsensitive])

    private static func applyTimes(_ text: String) -> String {
        var out: String = timesArith.sub(text, #"\1 x \2"#)
        out = timesBy.sub(out, #"x \1"#)
        out = timesDecimal.sub(out, #"\1x"#)
        return timesCompare.sub(out, #"\1x"#)
    }

    private static func subPercentWords(_ m: PyMatch) -> String {
        let whole: String = m.group(0) ?? ""
        let phrase: String = (m.group(1) ?? "").pyStrip.lowercased()
        if numScaleMap[phrase] != nil { return whole }
        if let n = wordsToNumber(phrase) { return "\(n)%" }
        return whole
    }

    private static func subCurrencyWords(_ m: PyMatch) -> String {
        let whole: String = m.group(0) ?? ""
        if let n = wordsToNumber(m.group(2) ?? "") { return (m.group(1) ?? "") + String(n) }
        return whole
    }

    // MARK: Symbol names

    private static let joinBoth: [(String, String)] = [
        ("forward slash", "/"),
        ("back ?slash", "\\"),
        ("slash", "/"),
        ("underscore", "_"),
        ("hyphen", "-"),
        ("at symbol", "@"),
        ("apostrophe", "'"),
    ]
    private static let joinRight: [(String, String)] = [
        ("hash ?tag", "#"),
        ("dollar sign", "$"),
        ("pound sign", "£"),
        ("euro sign", "€"),
        ("tilde", "~"),
        ("open square bracket", "["),
        ("open curly bracket", "{"),
        ("open brace", "{"),
        ("open bracket", "("),
        ("open paren(?:thesis)?", "("),
        ("open(?:ing)? (?:double )?quotes?", "\""),
        ("begin quotes?", "\""),
        ("open(?:ing)? single quote", "'"),
    ]
    private static let joinLeft: [(String, String)] = [
        ("percent sign", "%"),
        ("semicolon", ";"),
        ("close square bracket", "]"),
        ("close curly bracket", "}"),
        ("close brace", "}"),
        ("close bracket", ")"),
        ("close paren(?:thesis)?", ")"),
        ("clos(?:e|ing) (?:double )?quotes?", "\""),
        ("end quotes?", "\""),
        ("un ?quote", "\""),
        ("clos(?:e|ing) single quote", "'"),
        ("exclamation (?:mark|point)", "!"),
    ]
    private static let spaced: [(String, String)] = [
        ("ampersand", "&"),
        ("asterisk", "*"),
        ("plus sign", "+"),
        ("equals? sign", "="),
        ("pipe symbol", "|"),
        ("vertical bar", "|"),
        ("caret", "^"),
        ("less ?than sign", "<"),
        ("greater ?than sign", ">"),
        ("back ?tick", "`"),
    ]

    private static let rules: [(PyRegex, String)] = {
        let s: String = #"[ \t]*"#
        var out: [(PyRegex, String)] = []
        for (p, sym) in joinBoth {
            out.append((PyRegex(s + #"\b(?:"# + p + #")\b"# + s, [.caseInsensitive]), sym))
        }
        for (p, sym) in joinRight {
            out.append((PyRegex(#"\b(?:"# + p + #")\b"# + s, [.caseInsensitive]), sym))
        }
        for (p, sym) in joinLeft {
            out.append((PyRegex(s + #"\b(?:"# + p + #")\b"#, [.caseInsensitive]), sym))
        }
        for (p, sym) in spaced {
            out.append((PyRegex(#"\b(?:"# + p + #")\b"#, [.caseInsensitive]), sym))
        }
        return out
    }()

    private static let multiSpace: PyRegex = PyRegex(" {2,}")
    private static let spaceBeforePunct: PyRegex = PyRegex(#" +([.,!?;:])"#)

    // MARK: Public

    /// Replace spoken symbol names with the symbols themselves.
    public static func apply(_ text: String) -> String {
        if text.isEmpty { return text }
        var out: String = text
        // Addresses first: they own "dot"/"dash"/"at".
        out = addrRun.sub(out) { (m: PyMatch) -> String in rewriteAddress(m) }
        for (pat, sym) in rules {
            out = pat.sub(out) { (_: PyMatch) -> String in sym }
        }
        // Numbers last: "dollar sign fifty" has to become "$fifty" first.
        out = percentWords.sub(out) { (m: PyMatch) -> String in subPercentWords(m) }
        out = percentDigits.sub(out, #"\1%"#)
        out = currencyWords.sub(out) { (m: PyMatch) -> String in subCurrencyWords(m) }
        out = applyTimes(out)
        out = TechTerms.apply(out)
        if out != text {
            out = multiSpace.sub(out, " ")
            out = spaceBeforePunct.sub(out, #"\1"#)
            out = out.pyStrip
        }
        return out
    }
}
