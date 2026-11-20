import Foundation

/// A thin Python-`re` lookalike over NSRegularExpression, so the text modules
/// ported from the desktop app read line-for-line like their Python originals
/// (and behave the same). Both engines are ICU-style backtracking engines;
/// `\b`, `\w`, `\d` and `\s` are Unicode-aware in both.
///
/// Flags map as: re.IGNORECASE -> .caseInsensitive, re.MULTILINE ->
/// .anchorsMatchLines, re.DOTALL -> .dotMatchesLineSeparators,
/// re.VERBOSE -> .allowCommentsAndWhitespace.
public struct PyRegex: @unchecked Sendable {
    public let pattern: String
    public let regex: NSRegularExpression

    /// Patterns are program constants, so a bad one is a programming error:
    /// crash in debug, and match nothing in release rather than take the app down.
    public init(_ pattern: String, _ options: NSRegularExpression.Options = []) {
        self.pattern = pattern
        if let regex = try? NSRegularExpression(pattern: pattern, options: options) {
            self.regex = regex
        } else {
            assertionFailure("Invalid regex: \(pattern)")
            // (?!) never matches.
            self.regex = try! NSRegularExpression(pattern: "(?!)", options: [])
        }
    }

    private static func ns(_ s: String) -> NSRange { NSRange(s.startIndex..<s.endIndex, in: s) }

    /// re.search: first match anywhere.
    public func search(_ text: String) -> PyMatch? {
        regex.firstMatch(in: text, options: [], range: Self.ns(text)).map { PyMatch(text: text, result: $0) }
    }

    /// re.match: a match that starts at the beginning of `text`.
    public func match(_ text: String) -> PyMatch? {
        regex.firstMatch(in: text, options: [.anchored], range: Self.ns(text)).map { PyMatch(text: text, result: $0) }
    }

    /// re.fullmatch: a match covering all of `text`.
    public func fullMatch(_ text: String) -> PyMatch? {
        let whole = Self.ns(text)
        for result in regex.matches(in: text, options: [.anchored], range: whole)
        where result.range.location == 0 && result.range.length == whole.length {
            return PyMatch(text: text, result: result)
        }
        // A greedy first match may be shorter than an alternative; retry
        // with an explicit end anchor.
        if let anchored = try? NSRegularExpression(pattern: "(?:\(pattern))\\z", options: regex.options),
           let result = anchored.firstMatch(in: text, options: [.anchored], range: whole) {
            return PyMatch(text: text, result: result)
        }
        return nil
    }

    public func finditer(_ text: String) -> [PyMatch] {
        regex.matches(in: text, options: [], range: Self.ns(text)).map { PyMatch(text: text, result: $0) }
    }

    /// re.findall semantics: whole match when there are no groups, group 1
    /// when there is one group (tuples are not modelled; use finditer).
    public func findall(_ text: String) -> [String] {
        finditer(text).map { m in
            regex.numberOfCaptureGroups >= 1 ? (m.group(1) ?? "") : m.group(0)!
        }
    }

    public func contains(_ text: String) -> Bool { search(text) != nil }

    /// re.sub with a function replacement. `count` 0 means all.
    public func sub(_ text: String, count: Int = 0, _ replace: (PyMatch) -> String) -> String {
        let matches = regex.matches(in: text, options: [], range: Self.ns(text))
        if matches.isEmpty { return text }
        let source = text as NSString
        var out = ""
        var last = 0
        var done = 0
        for result in matches {
            if count > 0 && done >= count { break }
            out += source.substring(with: NSRange(location: last, length: result.range.location - last))
            out += replace(PyMatch(text: text, result: result))
            last = result.range.location + result.range.length
            done += 1
        }
        out += source.substring(from: last)
        return out
    }

    /// re.sub with a Python-style template: `\1`, `\g<1>`, `\g<name>`, `\\`,
    /// and the escapes `\n` and `\t`. Unmatched groups expand to "" (Python 3.5+).
    public func sub(_ text: String, _ template: String, count: Int = 0) -> String {
        sub(text, count: count) { $0.expand(template) }
    }

    /// re.subn: the result and the number of replacements.
    public func subn(_ text: String, _ template: String) -> (String, Int) {
        let n = regex.numberOfMatches(in: text, options: [], range: Self.ns(text))
        return (sub(text, template), n)
    }

    /// re.split (without capture-group interleaving).
    public func split(_ text: String) -> [String] {
        let source = text as NSString
        var parts: [String] = []
        var last = 0
        for result in regex.matches(in: text, options: [], range: Self.ns(text)) {
            if result.range.length == 0 && result.range.location == last && last != 0 { continue }
            parts.append(source.substring(with: NSRange(location: last, length: result.range.location - last)))
            last = result.range.location + result.range.length
        }
        parts.append(source.substring(from: last))
        return parts
    }

    /// re.escape
    public static func escape(_ s: String) -> String {
        NSRegularExpression.escapedPattern(for: s)
    }
}

public struct PyMatch {
    public let text: String
    public let result: NSTextCheckingResult

    /// Group text, or nil when the group did not participate.
    public func group(_ index: Int = 0) -> String? {
        guard index <= result.numberOfRanges - 1 else { return nil }
        let r = result.range(at: index)
        guard r.location != NSNotFound, let range = Range(r, in: text) else { return nil }
        return String(text[range])
    }

    public func group(_ name: String) -> String? {
        let r = result.range(withName: name)
        guard r.location != NSNotFound, let range = Range(r, in: text) else { return nil }
        return String(text[range])
    }

    /// Range of the whole match (or a group) as String indices.
    public func range(_ index: Int = 0) -> Range<String.Index>? {
        let r = result.range(at: index)
        guard r.location != NSNotFound else { return nil }
        return Range(r, in: text)
    }

    /// UTF-16 offsets, matching NSString / NSRange arithmetic.
    public var start: Int { result.range.location }
    public var end: Int { result.range.location + result.range.length }

    /// Python template expansion.
    public func expand(_ template: String) -> String {
        var out = ""
        var chars = Array(template)
        var i = 0
        while i < chars.count {
            let c = chars[i]
            if c == "\\" && i + 1 < chars.count {
                let n = chars[i + 1]
                if n.isNumber, let first = n.wholeNumberValue {
                    var num = first
                    var j = i + 2
                    if j < chars.count, let second = chars[j].wholeNumberValue,
                       num * 10 + second < result.numberOfRanges {
                        num = num * 10 + second
                        j += 1
                    }
                    out += group(num) ?? ""
                    i = j
                    continue
                }
                if n == "g", i + 2 < chars.count, chars[i + 2] == "<",
                   let close = chars[(i + 3)...].firstIndex(of: ">") {
                    let ref = String(chars[(i + 3)..<close])
                    if let num = Int(ref) { out += group(num) ?? "" } else { out += group(ref) ?? "" }
                    i = close + 1
                    continue
                }
                switch n {
                case "n": out.append("\n")
                case "t": out.append("\t")
                case "\\": out.append("\\")
                default: out.append(c); out.append(n)
                }
                i += 2
                continue
            }
            out.append(c)
            i += 1
        }
        chars.removeAll()
        return out
    }
}

public extension String {
    /// Python str.strip() with no arguments (whitespace incl. newlines).
    var pyStrip: String { trimmingCharacters(in: .whitespacesAndNewlines) }

    /// Python str.strip(chars).
    func pyStrip(_ chars: String) -> String {
        trimmingCharacters(in: CharacterSet(charactersIn: chars))
    }

    func pyLStrip(_ chars: String? = nil) -> String {
        let set = chars.map { CharacterSet(charactersIn: $0) } ?? .whitespacesAndNewlines
        var s = Substring(self)
        while let f = s.unicodeScalars.first, set.contains(f) { s = s.dropFirst() }
        return String(s)
    }

    func pyRStrip(_ chars: String? = nil) -> String {
        let set = chars.map { CharacterSet(charactersIn: $0) } ?? .whitespacesAndNewlines
        var s = Substring(self)
        while let l = s.unicodeScalars.last, set.contains(l) { s = s.dropLast() }
        return String(s)
    }

    /// Python str.split() with no arguments: runs of whitespace, no empties.
    var pySplit: [String] {
        split(whereSeparator: { $0.isWhitespace }).map(String.init)
    }

    /// Python str.capitalize() is NOT this; this upper-cases only the first
    /// character and leaves the rest (the desktop's `text[0].upper() + text[1:]`).
    var upperFirst: String {
        guard let f = first else { return self }
        return f.uppercased() + dropFirst()
    }
}
