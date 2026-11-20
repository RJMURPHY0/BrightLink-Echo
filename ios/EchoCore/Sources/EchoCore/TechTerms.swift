import Foundation

/// Port of tech_terms.py: AI model names and version numbers, written the way
/// people type them ("opus five point five" -> "Opus 5.5", "chat gpt" ->
/// "ChatGPT"). Names that are also English words are only touched when a
/// version number follows them, and a number is only digitised after a model
/// name.
public enum TechTerms {

    // MARK: Tables (arrays of pairs: Python dict order matters in alternations)

    private static let ones: [(String, Int)] = [
        ("zero", 0), ("oh", 0), ("one", 1), ("two", 2), ("three", 3), ("four", 4), ("five", 5),
        ("six", 6), ("seven", 7), ("eight", 8), ("nine", 9), ("ten", 10), ("eleven", 11),
        ("twelve", 12), ("thirteen", 13), ("fourteen", 14), ("fifteen", 15),
        ("sixteen", 16), ("seventeen", 17), ("eighteen", 18), ("nineteen", 19),
    ]
    private static let tens: [(String, Int)] = [
        ("twenty", 20), ("thirty", 30), ("forty", 40), ("fifty", 50), ("sixty", 60),
        ("seventy", 70), ("eighty", 80), ("ninety", 90),
    ]

    private static let onesMap: [String: Int] = Dictionary(uniqueKeysWithValues: ones)
    private static let tensMap: [String: Int] = Dictionary(uniqueKeysWithValues: tens)

    /// Python `sorted(keys, key=len, reverse=True)`: longest first, stable.
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

    private static let numWords: String = {
        let all: [String] = ones.map { $0.0 } + tens.map { $0.0 }
        return byLengthDescending(all).joined(separator: "|")
    }()

    private static let onesAlt: String = ones.map { $0.0 }.joined(separator: "|")

    private static let tierEntries: [(String, String)] = [
        ("pro", "Pro"), ("flash", "Flash"), ("ultra", "Ultra"), ("max", "Max"),
        ("mini", "mini"), ("nano", "nano"), ("turbo", "Turbo"), ("lite", "Lite"),
        ("preview", "Preview"), ("instruct", "Instruct"), ("thinking", "Thinking"),
    ]
    private static let tiers: [String: String] = Dictionary(uniqueKeysWithValues: tierEntries)

    private static let always: [(String, String)] = [
        (#"chat[ \t\-]?gpt"#, "ChatGPT"),
        (#"open[ \t]?ai"#, "OpenAI"),
        (#"deep[ \t]?seek"#, "DeepSeek"),
        (#"l\.?m\.?[ \t]?arena"#, "LMArena"),
        (#"hugging[ \t]?face"#, "Hugging Face"),
        (#"mid[ \t]?journey"#, "Midjourney"),
        (#"eleven[ \t]?labs"#, "ElevenLabs"),
        ("anthropic", "Anthropic"),
        ("gpt", "GPT"),
        ("grok", "Grok"),
        ("qwen", "Qwen"),
        ("kimi", "Kimi"),
        ("llm", "LLM"),
        ("llms", "LLMs"),
    ]

    private static let families: [(String, String)] = [
        ("claude", "Claude"), ("opus", "Opus"), ("sonnet", "Sonnet"),
        ("haiku", "Haiku"), ("fable", "Fable"), ("gemini", "Gemini"),
        ("gemma", "Gemma"), ("llama", "Llama"), ("mistral", "Mistral"),
        ("grok", "Grok"), ("qwen", "Qwen"), ("kimi", "Kimi"), ("phi", "Phi"),
        ("gpt", "GPT"), ("deepseek", "DeepSeek"), ("deepseek v", "DeepSeek V"),
        ("deep seek", "DeepSeek"), ("deep seek v", "DeepSeek V"),
        ("codex", "Codex"), ("veo", "Veo"), ("sora", "Sora"), ("kling", "Kling"),
    ]
    private static let famCanon: [String: String] = Dictionary(uniqueKeysWithValues: families)

    private static let famAlt: String = {
        let keys: [String] = byLengthDescending(families.map { $0.0 })
        let parts: [String] = keys.map { (k: String) -> String in
            // re.escape(k) then " " -> "[ \t]+"; the keys hold only letters and spaces.
            k.replacingOccurrences(of: " ", with: "[ \t]+")
        }
        return parts.joined(separator: "|")
    }()

    private static let tierAlt: String = tierEntries.map { $0.0 }.joined(separator: "|")

    private static let sep: String = #"[ \t]+"#

    private static let numPattern: String =
        #"(?:\d+|(?:"# + numWords + #")(?:[ \t\-]+(?:"# + onesAlt + #"))?)"#

    private static let verPattern: String =
        "(?:" + numPattern + #"(?:(?:[ \t]+point[ \t]+|\.(?=\d))"# + numPattern + ")?)"

    private static let versioned: PyRegex = {
        let parts: [String] = [
            #"\b(?<fam>"#, famAlt, #")(?<sep>[ \t\-]*)(?<ver>"#, verPattern, ")",
            #"(?<o>[ \t]+o\b|o\b)?(?<tier>"#, sep, "(?:", tierAlt, #")\b)?"#,
        ]
        return PyRegex(parts.joined(), [.caseInsensitive])
    }()

    private static let alwaysRegexes: [(PyRegex, String)] = always.map { (p: (String, String)) -> (PyRegex, String) in
        (PyRegex(#"\b(?:"# + p.0 + #")\b"#, [.caseInsensitive]), p.1)
    }

    private static let ws: PyRegex = PyRegex(#"[ \t]+"#)
    private static let numSplit: PyRegex = PyRegex(#"[ \t\-]+"#)
    private static let verSplit: PyRegex = PyRegex(#"[ \t]+point[ \t]+|\."#, [.caseInsensitive])
    private static let claudeBefore: PyRegex = PyRegex(
        #"\bclaude(?=[ \t]+(?:Opus|Sonnet|Haiku|Fable)\b)"#, [.caseInsensitive])

    // MARK: Helpers

    private static func isAllDigits(_ s: String) -> Bool {
        if s.isEmpty { return false }
        for u in s.unicodeScalars {
            if u.properties.numericType != .decimal && u.properties.numericType != .digit { return false }
        }
        return true
    }

    private static func num(_ tokIn: String) -> String? {
        let tok: String = tokIn.pyStrip.lowercased()
        if isAllDigits(tok) { return tok }
        let parts: [String] = numSplit.split(tok).filter { !$0.isEmpty }
        var total: Int = 0
        for p in parts {
            if let t = tensMap[p] {
                total += t
            } else if let o = onesMap[p] {
                total += o
            } else {
                return nil
            }
        }
        return String(total)
    }

    /// Python `re.split(pattern, s, maxsplit=1)` for a pattern without groups.
    private static func splitOnce(_ regex: PyRegex, _ s: String) -> [String] {
        guard let m = regex.search(s), let r = m.range() else { return [s] }
        return [String(s[s.startIndex..<r.lowerBound]), String(s[r.upperBound...])]
    }

    private static func version(_ spoken: String) -> String? {
        let halves: [String] = splitOnce(verSplit, spoken.pyStrip)
        var out: [String] = []
        for h in halves {
            guard let n = num(h) else { return nil }
            out.append(n)
        }
        return out.joined(separator: ".")
    }

    private static func subVersioned(_ m: PyMatch) -> String {
        let whole: String = m.group(0) ?? ""
        guard let ver = version(m.group("ver") ?? "") else { return whole }
        let famRaw: String = m.group("fam") ?? ""
        let key: String = ws.sub(famRaw.lowercased(), " ")
        let fam: String = famCanon[key] ?? famRaw
        // Claude is also a first name: only a decimal marks the model.
        if fam == "Claude" && !ver.contains(".") { return whole }
        var out: String
        if fam == "DeepSeek V" {
            out = "DeepSeek V" + ver
        } else if fam == "GPT" {
            out = "GPT-" + ver
        } else {
            out = fam + " " + ver
        }
        if let o = m.group("o"), !o.isEmpty { out += "o" }
        if let t = m.group("tier"), !t.isEmpty {
            let k: String = t.pyStrip.lowercased()
            out += " " + (tiers[k] ?? "")
        }
        return out
    }

    // MARK: Public

    /// Write AI model names and versions the way they are spelt.
    public static func apply(_ text: String) -> String {
        if text.isEmpty { return text }
        var out: String = versioned.sub(text) { (m: PyMatch) -> String in subVersioned(m) }
        for (pat, canon) in alwaysRegexes {
            out = pat.sub(out) { (_: PyMatch) -> String in canon }
        }
        out = claudeBefore.sub(out) { (_: PyMatch) -> String in "Claude" }
        return out
    }
}
