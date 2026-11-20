import Foundation

/// Stutter / false-start collapse: a faithful port of disfluency.py.
///
/// Only ever DELETES tokens (bar lowering a restart's capital on a function
/// word) in three shapes: a non-inflectional prefix fragment ("rec recent"), an
/// exact double from `dupCollapse` ("the the"), or one copy of an unfinished
/// 2-4 word phrase said twice ("in the in the CRM"); plus the 3+ repeat
/// catch-all. Everything else, including paragraph breaks, is preserved
/// byte for byte. The desktop's reporter/telemetry hook is not ported.
///
/// Note: Python indexes by code point, Swift by Character (grapheme cluster).
/// They only differ for combining marks/emoji, which never reach these
/// ASCII-word comparisons in practice.
public enum Disfluency {
    private static let minFragment: Int = 2
    private static let stripChars: String = " \t\"'.,!?;:()[]{}-—–…"
    private static let sentEnd: Set<Character> = [".", "!", "?"]
    private static let phraseMin: Int = 2
    private static let phraseMax: Int = 4

    private static func wordSet(_ s: String) -> Set<String> {
        var out = Set<String>()
        for piece in s.split(whereSeparator: { $0 == " " || $0 == "\n" || $0 == "\t" }) {
            out.insert(String(piece))
        }
        return out
    }

    private static let inflections: Set<String> = wordSet("""
        d ed en er ers es est ies ing ings ion ions ly ment ments n ness s y
""")

    private static let dupCollapse: Set<String> = wordSet("""
        a about across actually against also am an and are aren't at basically be because been
        between but by can can't could couldn't did didn't do does doesn't don't during for from
        get has hasn't have haven't he he's her his how i i'd i'll i'm i've if in into is isn't it
        it's its just less let's like make maybe me more my need of okay on onto or our probably
        really right she she's should shouldn't so that's the their them there's these they they'd
        they'll they're they've think this those through to us want was wasn't we we'd we'll we're
        we've well weren't what what's when where whether which whose why will with within without
        won't would wouldn't yeah yep you you'd you'll you're you've your
""")

    private static let phraseLead: Set<String> = wordSet("""
        a about across after against am an and are around at be because been before between but by
        can could did does during for from had has have her his how if in into is its may might
        must my of on onto or our over shall should so that the their then these this those
        through to under was what when where whether which who whose why will with within without
        would your
""")

    private static let phraseDangle: Set<String> = wordSet("""
        a am an are be been can could did does had has have her his is its may might must my of
        our shall should the their these this those to was will would your
""")

    private static let phraseNeverEnd: Set<String> = ["and", "or", "nor"]
    private static let iForms: Set<String> = ["i", "i'm", "i've", "i'll", "i'd"]

    private static let commonWords: Set<String> = wordSet("""
        a about above across act add after again age ago air all also am an and any apple are area
        arm army art as ask at away baby back bad bag ball ban band bank bar base bat be bear beat
        bed been beer bell best bet big bill bind bird bit black blue boat body book born both box
        boy bug bus but buy by cab call came camp can cap car card care case cast cat catch cause
        cell chat check child city class clay clean clear cloud club coal coat cod code cold come
        cool cop copy cord core corn cost could cow crew cry cup cut dad dam dark data date day
        dead deal dear deep deny desk did die diet dig dim dip do dock doctor does dog done door
        dot down draw dream drink drop drug dry due dust each ear earn ease east easy eat edge egg
        eight else end even ever every eye face fact fail fair fall fan far farm fast fat fear
        feed feel fell few field file fill film find fine fire firm fish fist fit five fix flag
        flat flow fly fold food foot for force form fort four free from fuel full fun fund fur
        gain game gap gas gate gave gear get gift girl give glad go goal god gold gone good got
        grab gray great grew grid grow gun guy had hair half hall hand hang happy hard has hat
        hate have he head heal hear heat held hell help her here hero hey hi hide high hill him
        his hit hold hole home hope host hot hour how huge hunt hurt ice idea if ill in inch info
        ink into iron is it item its jam job join joke joy jump just keep kept key kick kid kill
        kind king kiss kit know lab lack lady laid lake lamp land lane last late lawn lay lazy
        lead leaf lean leap learn led left leg lend less let lie life lift like line link lip list
        live load loan lock log long look loop lord lose loss lost lot loud love low luck mad made
        mail main make male man many map mark mask mass mat match math may me meal mean meat meet
        men menu mess met mid mild mile milk mind mine mint miss mix mob mode mood moon more most
        move much mud must my nail name near neat neck need net new news next nice night nine no
        node none nor nose not note now null nut oak obey odd off oil old on once one only onto
        open or oral our out over own pace pack page paid pain pair pale palm pan park part pass
        past path pay peak peer pen per pet pick pie pig pile pin pink pipe pit plan play plot
        plug plus poem poet point pole poll pond pool poor pop port pose post pour pray prep prey
        pro push put quiz race rack rage rail rain rank rare rate raw read real rear red rely rent
        rest rice rich ride ring riot rise risk road rob rock rod role roll roof room root rope
        rose row rule run rush sad safe said sail sale salt same sand save saw say sea seat see
        seed seek seem seen self sell send sent set sew shall ship shoe shop shot show shut sick
        side sign silk sing sink sir sit site six size skin sky slip slow snap snow so soap sock
        soft soil sold sole solid some son song soon sort soul soup sour spa spin spot spy stab
        star stay stem step still stir stop such suit sum sun sure swim tab tail take tale talk
        tall tank tap tape task tax tea team tear tech tell ten tend tent term test text than that
        the them then there these they thin thing this those thus tick tide tie till time tin tiny
        tip tire to today toe told toll tone too took tool top torn toss tour town toy trap tray
        tree trim trip true try tube tune turn twin two type ugly unit up upon urge us use user
        vary vast very vet via vice view vote wage wait wake walk wall want war ward warm warn
        wash wave way we weak wear web week well went were west wet what when where which while
        whip who whom why wide wife wild will win wind wine wing wipe wire wise wish with wolf won
        wood wool word wore work worm worn wrap yard yeah year yes yet you your zero zone zoo
""")

    private static let nonSpace = PyRegex(#"\S+"#)

    // MARK: helpers

    /// Comparison key: edge punctuation and case carry no stutter information.
    private static func key(_ tok: String) -> String {
        return tok.pyStrip(stripChars).lowercased().replacingOccurrences(of: "’", with: "'")
    }

    /// True when the token's trailing punctuation includes a sentence mark.
    private static func endsSentence(_ tok: String) -> Bool {
        for ch in tok.reversed() {
            if ch.isLetter || ch.isNumber { return false }
            if sentEnd.contains(ch) { return true }
        }
        return false
    }

    private static func isAlpha(_ s: String) -> Bool {
        return !s.isEmpty && s.allSatisfy { $0.isLetter }
    }

    /// Python str.isupper(): at least one cased char, none lowercase.
    private static func isUpperStr(_ s: String) -> Bool {
        var cased = false
        for ch in s {
            if ch.isLowercase { return false }
            if ch.isUppercase { cased = true }
        }
        return cased
    }

    /// `prev` is an aborted attempt at `cur`: a strict, non-inflectional
    /// prefix that is not itself an ordinary word.
    private static func isFalseStart(_ prevKey: String, _ curKey: String) -> Bool {
        if prevKey.count < minFragment || prevKey.count >= curKey.count { return false }
        if !isAlpha(prevKey) || !isAlpha(curKey) { return false }
        if !curKey.hasPrefix(prevKey) { return false }
        if commonWords.contains(prevKey) { return false }
        // A clean inflectional tail means these are two real words.
        if inflections.contains(String(curKey.dropFirst(prevKey.count))) { return false }
        return true
    }

    /// `prev` and `cur` are the same never-validly-doubled function word.
    private static func isFunctionDouble(_ prevKey: String, _ curKey: String) -> Bool {
        return prevKey == curKey && dupCollapse.contains(prevKey)
    }

    private static func isAcronym(_ tok: String) -> Bool {
        let core = tok.pyStrip(stripChars)
        return core.count > 1 && isUpperStr(core)
    }

    /// `keys` (one copy of an exactly repeated phrase) is an unfinished
    /// fragment, so the repeat is a restart rather than emphasis.
    private static func isPhraseRestart(_ keys: [String]) -> Bool {
        if keys.count < phraseMin || keys.count > phraseMax { return false }
        if keys.contains(where: { $0.isEmpty }) { return false }
        if Set(keys).count == 1 { return false }   // "no no", "very very"
        // "on and on", "in and out": a conjunction inside makes it a pair.
        if keys.dropFirst().contains(where: { phraseNeverEnd.contains($0) }) { return false }
        return phraseLead.contains(keys[0]) || phraseDangle.contains(keys[keys.count - 1])
    }

    /// Move a leading capital from the dropped false-start onto the kept word
    /// (and, for a function-word restart, lower a capital that sits mid-sentence).
    private static func carryCapital(_ dropped: String, _ kept: String) -> String {
        let lead = kept.count - kept.pyLStrip(stripChars).count
        let d: String = dropped.pyLStrip(stripChars)
        let k: String = String(kept.dropFirst(lead))
        if let d0 = d.first, let k0 = k.first {
            if d0.isUppercase && k0.isLowercase {
                return String(kept.prefix(lead)) + k0.uppercased() + String(k.dropFirst())
            }
            // The reverse: "also a A thing", "if you're If you're working".
            let ck = key(kept)
            let k1IsUpper: Bool = {
                let rest = k.dropFirst()
                if let c = rest.first { return c.isUppercase }
                return false
            }()
            if d0.isLowercase && k0.isUppercase
                && !k1IsUpper                       // an acronym keeps its caps
                && (dupCollapse.contains(ck) || phraseLead.contains(ck))
                && !iForms.contains(ck) {
                return String(kept.prefix(lead)) + k0.lowercased() + String(k.dropFirst())
            }
        }
        return kept
    }

    // MARK: destutter

    /// Collapse false-start and function-word-double stutters. Only the
    /// dropped fragment and the single space beside it are removed.
    public static func destutter(_ text: String) -> String {
        if text.isEmpty { return text }
        var spans: [Range<String.Index>] = []
        for m in nonSpace.finditer(text) {
            if let r = m.range() { spans.append(r) }
        }
        if spans.count < 2 { return text }
        let toks: [String] = spans.map { String(text[$0]) }

        // Phase 1: decide which tokens to drop, comparing each against the
        // last token still standing (so cascaded stutters resolve).
        var fin: [String] = toks            // mutated only to carry a capital
        var dropped = Set<Int>()
        var last: Int? = nil                  // index of the last kept token
        var runKey: String = ""
        var runStart: Int? = nil              // first token of the current run
        for i in 0..<toks.count {
            let tok = toks[i]
            if let l = last, !endsSentence(fin[l]) {
                let pk = key(fin[l])
                let ck0 = key(tok)
                if !pk.isEmpty && !ck0.isEmpty
                    && (isFalseStart(pk, ck0) || isFunctionDouble(pk, ck0)) {
                    if isFunctionDouble(pk, ck0) && (isAcronym(fin[l]) != isAcronym(tok)) {
                        last = i              // "it IT", "us US": two different words
                        runKey = ck0
                        runStart = i
                        continue
                    }
                    fin[i] = carryCapital(fin[l], tok)
                    dropped.insert(l)
                    last = i
                    if ck0 != runKey {
                        runKey = ck0
                        runStart = i
                    }
                    continue
                }
            }

            // Tier 2: triple+ repeat catch-all.
            let ck = key(tok)
            if !ck.isEmpty && ck == runKey, let rs = runStart {
                var runCount = 1
                var ri = i - 1
                while ri >= rs {
                    if key(toks[ri]) == ck { runCount += 1 } else { break }
                    ri -= 1
                }
                if runCount >= 3 {
                    var firstKept: Int? = nil
                    var r2 = rs
                    while r2 < i {
                        if !dropped.contains(r2) && key(toks[r2]) == ck {
                            firstKept = r2
                            break
                        }
                        r2 += 1
                    }
                    if let fk = firstKept {
                        fin[i] = carryCapital(fin[fk], tok)
                        var r3 = fk + 1
                        while r3 < i {
                            if key(toks[r3]) == ck && !dropped.contains(r3)
                                && !endsSentence(fin[r3]) {
                                dropped.insert(r3)
                            }
                            r3 += 1
                        }
                        if !dropped.contains(fk) && !endsSentence(fin[fk]) {
                            dropped.insert(fk)
                        }
                        last = i
                    }
                    continue
                }
            }
            // New word: reset run tracking.
            if ck != runKey {
                runKey = ck
                runStart = i
            }

            last = i
        }

        // Phase 1b: phrase restarts, over the tokens still standing. Longest
        // first at each position; after a collapse the scan steps back one
        // phrase so "in the in the in the" resolves, but never restarts from
        // the top.
        var kept: [Int] = (0..<toks.count).filter { !dropped.contains($0) }
        var kk: [String] = kept.map { key(fin[$0]) }
        var j = 0
        while j < kept.count {
            var hit = 0
            var n = phraseMax
            while n >= phraseMin {
                defer { n -= 1 }
                if j + 2 * n > kept.count { continue }
                let ka: [String] = Array(kk[j..<(j + n)])
                let kb: [String] = Array(kk[(j + n)..<(j + 2 * n)])
                if ka != kb || !isPhraseRestart(ka) { continue }
                var anyEnds = false
                for x in kept[j..<(j + n)] where endsSentence(fin[x]) { anyEnds = true; break }
                if anyEnds { continue }
                // "on and on and on": the X of an "and X" repeat sits just before.
                if phraseNeverEnd.contains(ka[0]) && j > 0 && kk[j - 1] == ka[ka.count - 1] {
                    continue
                }
                hit = n
                break
            }
            if hit == 0 {
                j += 1
                continue
            }
            fin[kept[j + hit]] = carryCapital(fin[kept[j]], fin[kept[j + hit]])
            for x in kept[j..<(j + hit)] { dropped.insert(x) }
            kept.removeSubrange(j..<(j + hit))
            kk.removeSubrange(j..<(j + hit))
            j = max(0, j - phraseMax)
        }

        if dropped.isEmpty { return text }

        // Phase 2: rebuild, preserving the original whitespace everywhere
        // except the gap beside a dropped token, which collapses to one space.
        var out: String = String(text[text.startIndex..<spans[0].lowerBound])
        var started = false
        var gapDirty = false
        var prevEnd: String.Index = text.startIndex
        for i in 0..<spans.count {
            if dropped.contains(i) {
                gapDirty = true
                continue
            }
            if !started {
                out += fin[i]
                started = true
            } else {
                if gapDirty {
                    out += " "
                } else {
                    out += String(text[prevEnd..<spans[i].lowerBound])
                }
                out += fin[i]
            }
            prevEnd = spans[i].upperBound
            gapDirty = false
        }
        out += String(text[spans[spans.count - 1].upperBound...])
        return out
    }
}
