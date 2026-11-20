import Foundation

/// Sound-alike words picked from the rest of the sentence ("Revenue one this
/// quarter" -> "Revenue won this quarter"): a faithful port of homophones.py.
///
/// This REWRITES words the user said, so it is deliberately timid: every rule
/// is one confusable pair in one narrow shape and needs evidence on BOTH sides
/// of the word; only spaces may sit between the words of a shape; a rule that
/// could be reading an enumeration stands down. The safe direction is to
/// UNDER-correct.
///
/// Per-word confidence: Python keys confidence by the engine's own
/// [(word, confidence)] record, aligned to the text by word identity. Here the
/// caller passes one optional confidence per whitespace-separated word of the
/// text; that array is turned into the same kind of record internally
/// (`WordConfidence.recorded(from:perWord:)`) and aligned exactly as Python
/// does, so rules marked `unsure` behave identically. With no confidence,
/// those rules never fire. The telemetry reporter is not ported.
public enum Homophones {
    private typealias Guard = (String, PyMatch) -> Bool

    private struct Rule: @unchecked Sendable {
        let name: String
        /// Group "w" is the word that changes. Left context is matched, right
        /// context lives in a lookahead so a rule never swallows the word the
        /// next rule needs.
        let pattern: PyRegex
        let replacement: String
        let guardFn: Guard?
        /// Keep a capital the word already had mid-sentence ("Closed One" ->
        /// "Closed Won").
        let keepTitle: Bool
        /// Fire only when the recogniser itself was UNSURE of the word.
        let unsure: Double?
    }

    // MARK: pattern building blocks

    /// Word edges. A word may not continue into letters, digits, apostrophes
    /// or a hyphen, and may not follow a path, handle or file-name character.
    private static let rxB: String = #"(?<![\w'’/@#.\\-])"#
    private static let rxE: String = #"(?![\w'’-])"#
    /// Only spaces or tabs between the words of a shape.
    private static let rxS: String = #"[ \t]+"#
    /// End of the clause: closing punctuation or the end of the text.
    private static let rxEnd: String = #"[ \t]*(?:[.!?,;:]|$)"#

    private static func j(_ parts: String...) -> String {
        return parts.joined()
    }

    /// Whitespace-separated words -> a non-capturing alternation, longest
    /// first. A word written with an underscore matches a multi-word phrase.
    private static func alt(_ wordLists: String...) -> String {
        let words: String = wordLists.joined(separator: " ")
        var seen = Set<String>()
        var items: [String] = []
        for piece in words.split(whereSeparator: { $0 == " " || $0 == "\n" || $0 == "\t" }) {
            let w = String(piece)
            if seen.insert(w).inserted { items.append(w) }
        }
        items.sort { (a: String, b: String) -> Bool in
            if a.count != b.count { return a.count > b.count }
            return a < b
        }
        let parts: [String] = items.map { $0.replacingOccurrences(of: "_", with: rxS) }
        return "(?:" + parts.joined(separator: "|") + ")"
    }

    private static func rx(_ pattern: String) -> PyRegex {
        return PyRegex(pattern, [.caseInsensitive])
    }

    // MARK: shared context

    /// Plural things you win.
    private static let wonPlurals: String = """
    awards prizes deals contracts games matches tenders bids cases elections
    titles trophies medals races points seats votes customers clients accounts
    pitches battles arguments rounds goals
    """

    /// "the" after "one" is the verb's object EXCEPT in these time and size
    /// phrases.
    private static let theNotObject: String = alt("""
    other next last same whole day week month year morning afternoon evening
    night weekend size one first second previous following
    """)

    private static let number: String = j(
        #"(?:\d[\d,.]*|a_couple_of|a_few|two|three|four|five|six|seven|"#,
        #"eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|hundred|"#,
        #"several|some|both)"#
    ).replacingOccurrences(of: "_", with: rxS)

    /// What "won" takes as its object: "the deal", "it", "them", "(three) awards".
    private static let objectRx: String = j(
        "(?:the", rxS, "(?!", theNotObject, rxE, ")",
        #"|it(?![\w'’])|them"#, rxE,
        "|(?:", number, rxS, ")?", alt(wonPlurals), rxE, ")")

    /// Words that make "one" a count or a pronoun when they follow it.
    private static let oneAsCount: String = alt("""
    day time of more another or and thing point way last less too either each
    at by in on for to with from that which who is was
    """)

    /// Words after which "two" is a count, never "too".
    private static let countTakers: String = """
    the these those other another of for only just all about around roughly maybe
    perhaps last first next top bottom or and than between no any every each both
    our my your their his her its we us you them they it me him I some few
    number page step option phase version part level round chapter team section
    stage point line row column item slide question plan tier floor year week day
    plus minus times by to at from under over nearly almost exactly like versus vs
    are were is was be been am take took takes taking buy bought need needed needs
    want wanted wants get got gets have had has having make made makes give gave
    gives add added adds pick picked choose chose keep kept sell sold send sent
    order ordered book booked use used hold held see saw found find count counted
    one two three four five six seven eight nine ten eleven twelve zero
    a an per table room gate platform terminal channel series season episode
    this his was has does goes yes plus less unless thus always perhaps
    gets takes needs uses costs makes wants says buys sells holds gives keeps
    runs comes sees counts picks adds scores wins loses shows lists sends owns
    seats sleeps serves carries brings leaves pays charges requires allows
    offers includes contains supports has_got equals hits gains earns spends
    asks expects plays rolls throws deals draws books orders eats drinks
    fits splits cuts divides becomes turns makes_it ones
    """

    // MARK: guards (text-level helpers)

    private static let enumerationRx = rx(#"(?<![\w'’])(?:one|another|other)(?![\w'’])"#)
    private static let noCountBeforeRx = rx(j(#"(?<![\w'’])"#, number, #"[ \t]+(?:\w+[ \t]+)?$"#))
    private static let wordsRx = PyRegex(#"[\w'’]+"#)

    private static let subjectWords: Set<String> = [
        "he", "she", "it", "this", "that", "which", "who", "what", "there",
        "here", "one", "each", "everyone", "someone", "nobody", "everybody",
    ]

    /// text[pos:] up to (not including) the next . ! ? or newline.
    private static func sentenceTail(_ text: String, _ pos: Int) -> String {
        let n = NSString(string: text)
        let len = n.length
        if pos >= len { return "" }
        var i = pos
        while i < len {
            let u = n.character(at: i)
            if u == 0x2E || u == 0x21 || u == 0x3F || u == 0x0A { break }
            i += 1
        }
        return n.substring(with: NSRange(location: pos, length: i - pos))
    }

    /// text[cut + 1:pos] where cut is the last . ! ? or newline before pos.
    private static func sentenceHead(_ text: String, _ pos: Int) -> String {
        let n = NSString(string: text)
        let end = min(pos, n.length)
        var cut = -1
        var i = end - 1
        while i >= 0 {
            let u = n.character(at: i)
            if u == 0x2E || u == 0x21 || u == 0x3F || u == 0x0A {
                cut = i
                break
            }
            i -= 1
        }
        return n.substring(with: NSRange(location: cut + 1, length: end - (cut + 1)))
    }

    private static func atSentenceStart(_ text: String, _ pos: Int) -> Bool {
        let n = NSString(string: text)
        let before = n.substring(to: min(pos, n.length)).pyRStrip(" \t\"'“‘(")
        guard let last = before.unicodeScalars.last else { return true }
        return last == "." || last == "!" || last == "?" || last == "\n"
    }

    private static func wRange(_ m: PyMatch) -> NSRange {
        return m.result.range(withName: "w")
    }

    /// A later "one"/"another"/"other" in the same sentence means the first
    /// "one" was a count in a list.
    private static func notEnumeration(_ text: String, _ m: PyMatch) -> Bool {
        let w = wRange(m)
        let tail = sentenceTail(text, w.location + w.length)
        return !enumerationRx.contains(tail)
    }

    /// "we lost two customers one this week": a number before the noun makes
    /// the "one" a share of it, not the verb.
    private static func noCountBefore(_ text: String, _ m: PyMatch) -> Bool {
        let head = sentenceHead(text, m.start)
        return !noCountBeforeRx.contains(head)
    }

    /// "Did we one?" reads as a pronoun more often than the verb.
    private static func notQuestion(_ text: String, _ m: PyMatch) -> Bool {
        let w = wRange(m)
        let endW = w.location + w.length
        let tail = sentenceTail(text, endW)
        let idx = endW + tail.utf16.count
        let n = NSString(string: text)
        if idx < n.length { return n.character(at: idx) != 0x3F }
        return true
    }

    /// "Toy Story two", "Rocky two": a capitalised word before the number in
    /// mid-sentence is a title, and the number is its sequel.
    private static func leftNotName(_ text: String, _ m: PyMatch) -> Bool {
        let whole = NSString(string: m.group(0) ?? "")
        let ws = max(0, min(wRange(m).location - m.start, whole.length))
        let left = whole.substring(to: ws).pyStrip
        guard let f = left.first, f.isUppercase else { return true }
        return atSentenceStart(text, m.start)
    }

    /// "it fixes two", "the tool fixes two": a subject right before the
    /// plural-looking word makes it a verb with a count.
    private static func noSubjectBefore(_ text: String, _ m: PyMatch) -> Bool {
        let head = sentenceHead(text, m.start).pyRStrip()
        let prev: [String] = wordsRx.findall(head)
        guard let last = prev.last else { return true }
        return !subjectWords.contains(last.lowercased())
    }

    private static func all(_ guards: [Guard]) -> Guard {
        return { (t: String, m: PyMatch) -> Bool in
            for g in guards where !g(t, m) { return false }
            return true
        }
    }

    // MARK: the rules

    private static func rule(_ name: String, _ pattern: String, _ replacement: String,
                             guardFn: Guard? = nil, keepTitle: Bool = false,
                             unsure: Double? = nil) -> Rule {
        return Rule(name: name, pattern: rx(pattern), replacement: replacement,
                    guardFn: guardFn, keepTitle: keepTitle, unsure: unsure)
    }

    private static let rules: [Rule] = buildRules()

    private static func buildRules() -> [Rule] {
        let B = rxB, E = rxE, S = rxS, END = rxEnd
        var r: [Rule] = []

        // ---- one -> won -------------------------------------------------

        // Subject pronoun + "one": "we one the deal", "they one it", "We one."
        r.append(rule("won_after_subject", j(
            #"(?<![\w'’])(?<!is )(?<!am )(?<!are )(?<!was )(?<!were )(?<!be )"#,
            #"(?:I|we|they|he|she)"#, S,
            #"(?<w>one)"#, E,
            #"(?!"#, S, oneAsCount, E, #")"#,
            #"(?![ \t]*[?,;:])"#
        ), "won", guardFn: all([notQuestion, notEnumeration])))

        // Perfect "have" + "one" + an object.
        r.append(rule("won_after_have", j(
            B, #"(?:have|has|had|having|haven't|hasn't|hadn't|[a-z]+'ve|[a-z]+’ve)"#,
            S, #"(?<w>one)"#, E, #"(?="#, S, objectRx, #")"#
        ), "won", guardFn: notEnumeration))

        // Adverb + "one" + an object: "we finally one the tender".
        r.append(rule("won_after_adverb", j(
            B, #"(?:just|never|finally|already|recently|narrowly|eventually|"#,
            #"nearly|almost|actually|comfortably|easily)"#, S,
            #"(?<w>one)"#, E, #"(?="#, S, objectRx, #")"#
        ), "won", guardFn: notEnumeration))

        // The reported case: "Revenue one this quarter".
        r.append(rule("won_after_sales_noun", j(
            B, alt("revenue business sales orders opportunities jobs projects", wonPlurals), S,
            #"(?<w>one)"#, E,
            #"(?="#, S, alt("this last so_far since today yesterday recently ", "to_date year_to_date ytd against over_the ", "over_last in_q1 in_q2 in_q3 in_q4"), E, #")"#
        ), "won", guardFn: all([notEnumeration, noCountBefore])))

        // A winning margin: "one by a mile".
        r.append(rule("won_by_margin", j(
            B, #"(?<w>one)"#, S,
            #"(?=by"#, S, #"(?:a|an)"#, S,
            alt("mile country_mile landslide whisker nose length head ", "narrow_margin clear_margin wide_margin big_margin huge_margin ", "small_margin"), E, #")"#
        ), "won"))

        // "one or lost", "deals one and lost", "lost or one".
        r.append(rule("won_or_lost", j(
            B, #"(?<w>one)"#, S, #"(?=(?:or|and|vs|versus)"#, S,
            #"(?:lost|drawn)"#, E, #")"#
        ), "won"))
        r.append(rule("lost_or_won", j(
            B, "lost", S, #"(?:or|and|vs|versus)"#, S, #"(?<w>one)"#, E
        ), "won"))

        // The CRM deal stage: "marked as closed one" -> "closed won".
        r.append(rule("closed_won_stage", j(
            B, #"(?:as|to|into|in|at|stage|status|marked|mark|set|move|moved)"#,
            S, "closed(?:", S, #"|-)(?<w>one)"#, E
        ), "won", keepTitle: true))
        r.append(rule("closed_won_pair", j(
            B, "closed(?:", S, #"|-)(?<w>one)"#, E,
            #"(?="#, S, #"(?:or|and|vs|versus)"#, S,
            "closed(?:", S, #"|-)lost"#, E, #")"#
        ), "won", keepTitle: true))

        // ---- won -> one -------------------------------------------------

        r.append(rule("one_of", j(
            B, #"(?<w>won)"#, S, "(?=of", S,
            alt("the my our your their his her its those these them us you ", "which what many several"), E, ")"
        ), "one"))
        r.append(rule("no_one", j(
            B, "no", S, #"(?<w>won)"#, E,
            "(?=", END, "|'s|’s|", S, alt(
                "is was will would can could should has had knows knew else wants ", "cares seems really actually ever here there"), E, ")"
        ), "one"))
        r.append(rule("the_one", j(
            B, "(?:the|this)", S, #"(?<w>won)"#, E,
            "(?=", S, alt("that who which is was looks seems works here"),
            E, ")"
        ), "one"))

        // ---- then -> than -----------------------------------------------

        r.append(rule("than", j(
            B, alt("more less fewer better worse bigger smaller higher lower ", "faster slower greater larger longer shorter cheaper easier ", "harder quicker stronger weaker heavier lighter older ", "younger busier safer simpler clearer"), S,
            #"(?<w>then)"#, E,
            "(?=", S, #"(?:\d|"#, alt(
                "a an one two three four five six seven eight nine ten twenty ", "fifty hundred thousand million ever usual expected before ", "anything anyone anybody everyone everything average normal ", "necessary needed planned twice half"), E, "))"
        ), "than"))
        r.append(rule("other_than", j(
            B, "(?<!each )(?<!one )(?<!the )(?:other|rather)", S,
            #"(?<w>then)"#, E,
            "(?=", S, alt("that this the a an me you him her us them"),
            E, ")"
        ), "than"))

        // ---- of -> have -------------------------------------------------

        r.append(rule("modal_have", j(
            B, "(?:could|should|would|must|might)(?:n't|n’t)?", S,
            #"(?<w>of)"#, S, "(?=", alt(
                "been had done gone got gotten seen known made said taken thought ", "liked loved wanted told given come become heard sent asked tried ", "used called checked missed forgotten left put let"), E, ")"
        ), "have"))

        // ---- whether ----------------------------------------------------

        r.append(rule("whether_or_not", j(
            B, #"(?<!the )(?<w>weather)"#, S, "(?=or", S, "not", E, ")"
        ), "whether"))
        r.append(rule("whether_clause", j(
            #"(?:(?:^|(?<=[.!?\n]))[ \t]*|"#, B, alt(
                "know knows knew see check decide decided ask asked wondering ", "wonder unsure sure matter matters doubt confirm tell clear"),
            S, #")(?<w>weather)"#, S,
            "(?=(?:we|you|they|I|he|she|it's)", S, alt(
                "should can could will would want need go are were do did ", "decide is was"), E, ")"
        ), "whether"))

        // ---- you're / your, it's / its, there / their -------------------

        r.append(rule("youre", j(
            B, #"(?<w>your)"#, S,
            "(?=going", S, "to", E, "|(?:gonna|able|already|absolutely|",
            #"probably|definitely)"#, E, #"|not(?![\w'’-])|welcome"#, END, ")"
        ), "you're"))
        r.append(rule("your_things", j(
            B, "(?<w>you're|you’re)", S, "(?=", alt(
                "own thoughts feedback details calendar inbox laptop computer ", "behalf name"), E, ")"
        ), "your"))
        r.append(rule("its_is", j(
            B, #"(?<w>its)"#, S,
            "(?=going", S, "to", E, #"|not(?![\w'’-])|"#,
            alt("a an the been gonna okay ok"), E, ")"
        ), "it's"))
        r.append(rule("its_own", j(
            B, "(?<w>it's|it’s)", S, "(?=own", E, ")"
        ), "its"))
        r.append(rule("there_is", j(
            B, #"(?<w>their)"#, S, "(?=(?:is|are|was|were|isn't|aren't|",
            "wasn't|weren't|seems|seem|(?:will|would|must|might|could|should)",
            S, "be|(?:has|have)", S, "been|used", S, "to", S,
            "be)", E, ")"
        ), "there"))
        r.append(rule("their_own", j(
            B, "(?<w>there|they're|they’re)", S, "(?=own", E, ")"
        ), "their"))

        // ---- too --------------------------------------------------------

        r.append(rule("too", j(
            B, alt("is was are were be it's that's not bit way far slightly"),
            S, #"(?<w>to)"#, S, "(?=", alt(
                "much many long late early big small soon expensive hard easy ", "often high busy complicated complex risky dark bright loud ", "tight hot cold heavy bad"), E, ")"
        ), "too"))

        r.append(rule("too_also", j(
            #"(?<![\w'’/@#.\\-])(?!"#, alt(countTakers), E, ")",
            "[A-Za-z]+[abcdefghjklmnopqrtvwxyz]s", S, #"(?<w>two)"#, E,
            "(?=", END, "|", S, alt(
                "so but as_well though yeah please again anyway then"), E, ")"
        ), "too", guardFn: all([leftNotName, noSubjectBefore]), unsure: 0.80))

        // ---- cool / call ------------------------------------------------

        r.append(rule("cool_be", j(
            B, alt("that'd that’d it'd it’d that'll that’ll it'll it’ll would ", "will gonna to"), S, "be", S,
            "(?:(?:", alt("pretty super quite very kinda kind_of"), ")", S,
            #")?(?<w>call)"#, E,
            "(?=", END, "|", S, alt("too as_well though yeah and but so"),
            E, ")"
        ), "cool", unsure: 0.95))
        r.append(rule("cool_is", j(
            B, "(?:that's|that’s|thats|it's|it’s|sounds|looks|seems)", S,
            "(?:(?:", alt("pretty super quite very kinda kind_of"), ")", S,
            #")?(?<w>call)"#, E,
            "(?=", END, "|", S, alt("too as_well though yeah and but so ", "with_me with_us"), E, ")"
        ), "cool", unsure: 0.95))
        r.append(rule("call_you", j(
            B, "(?:I'll|I’ll|we'll|we’ll|I", S, "will|we", S,
            "will|I'd|I’d|can|could|should|gonna|please|to)", S,
            #"(?<w>cool)"#, S, "(?=(?:you|him|her|them|me|us)", S, alt(
                "back later tomorrow tonight today now first_thing on_monday ", "on_tuesday on_wednesday on_thursday on_friday this_afternoon ", "this_evening in_a_bit"), E, ")"
        ), "call", unsure: 0.90))
        r.append(rule("give_a_call", j(
            B, "(?:give|gave|giving|gives)", S,
            "(?:you|him|her|them|me|us)", S, "a", S,
            "(?:(?:quick|ring)", S, #")?(?<w>cool)"#, E,
            "(?=", END, "|", S, alt(
                "back later tomorrow tonight today now when after about on at ", "first_thing this_afternoon this_evening"), E, ")"
        ), "call"))

        // ---- write / right ----------------------------------------------

        r.append(rule("write_a", j(
            B, "(?<!all )(?<!that's )(?<!that’s )(?<!yeah )(?<!yes )",
            "(?<!okay )(?<!ok )(?<!right )(?<!turn )(?<!left )(?<!is )",
            "(?<!was )(?<!exactly )(?<!quite )",
            #"(?<w>right)"#, S,
            "(?=(?:a|an|me", S, "(?:a|an)|up", S, "(?:a|an|the))", S,
            alt("email emails letter report note message blog post review script ", "proposal summary function story cheque list brief article essay ", "update invoice reply response description prompt query comment ", "draft spec"), E, ")"
        ), "write"))
        r.append(rule("write_down", j(
            B, #"(?<w>right)"#, S, "(?=(?:it|that|this|them|these|those)",
            S, "down", E, ")"
        ), "write"))

        // ---- hear / here ------------------------------------------------

        r.append(rule("hear", j(
            B, "(?:can|can't|cannot|could|couldn't|didn't|did", S, "you|",
            "did", S, "they|did", S, "we|will|won't|never)", S,
            #"(?<w>here)"#, S, "(?=(?:you|me|him|her|them|us|that|what|",
            "anything|nothing|something|back|from", S,
            "(?:you|him|her|them|us|me)|about", S,
            "(?:it|that|this|them|him|her))", E, ")"
        ), "hear"))
        r.append(rule("to_hear", j(
            B, "to", S, #"(?<w>here)"#, S,
            "(?=(?:back|from", S, "(?:you|him|her|them|us|me)|about", S,
            "(?:it|that|this|them|him|her))", E, ")"
        ), "hear"))
        r.append(rule("in_here", j(
            B, "(?:right|in|out)", S, #"(?<w>hear)"#, E,
            "(?=", END, "|", S, alt("and now too with is was for"), E, ")"
        ), "here"))

        // ---- know / no --------------------------------------------------

        r.append(rule("let_know", j(
            B, "let", S, "(?:me|us|you|them|him|her)", S,
            #"(?<w>no)"#, E, "(?!", S, "(?:longer|more|one)", E, ")"
        ), "know"))
        r.append(rule("dont_know", j(
            B, "(?:don't|didn't|doesn't|don’t|didn’t|doesn’t|dont)", S,
            #"(?<w>no)"#, E, "(?!", S, "(?:longer|more|one|matter)", E, ")"
        ), "know"))
        r.append(rule("i_know", j(
            B, "(?:I|you|we|they)", S, #"(?<w>no)"#, S,
            "(?=", alt("that what how why where when who if whether"), E, ")"
        ), "know"))

        // ---- week / weak ------------------------------------------------

        r.append(rule("week", j(
            B, "(?:this|next|last|per|each|every)", S, #"(?<w>weak)"#, E,
            "(?=", END, "|", S, alt(
                "we I you they he she it is was the on in at for to with so but ", "then because if when there now too already though anyway"),
            E, ")"
        ), "week"))
        r.append(rule("a_week_ago", j(
            B, "(?:a|one)", S, #"(?<w>weak)"#, S, "(?=ago", E, ")"
        ), "week"))
        r.append(rule("weeks_ago", j(
            B, #"(?<w>weaks)"#, S, "(?=ago", E, ")"
        ), "weeks"))

        // ---- fixed phrases ----------------------------------------------

        r.append(rule("peace_of_mind", j(
            B, #"(?<w>piece)"#, S, "(?=of", S, "mind", E, ")"
        ), "peace"))
        r.append(rule("piece_of", j(
            B, #"(?<w>peace)"#, S, "(?=of", S, alt(
                "cake paper work code advice information content equipment ", "software kit furniture feedback evidence news text data writing ", "the_puzzle"), E, ")"
        ), "piece"))
        r.append(rule("out_of_sight", j(
            B, "out", S, "of", S, #"(?<w>site)"#, E, "(?=", END, ")"
        ), "sight"))
        r.append(rule("lose_sight_of", j(
            B, "(?:lose|lost|losing)", S, #"(?<w>site)"#, S,
            "(?=of", E, ")"
        ), "sight"))
        r.append(rule("roll_out", j(
            B, #"(?<w>role)"#, S, "(?=out", E, "(?!", S, "of", E, "))"
        ), "roll"))
        r.append(rule("role_model", j(
            B, #"(?<w>roll)"#, S, "(?=", alt("model models play playing"),
            E, ")"
        ), "role"))
        r.append(rule("on_a_roll", j(
            B, "on", S, "a", S, #"(?<w>role)"#, E,
            "(?=", END, "|", S, alt(
                "lately today recently right_now at_the_moment"), E, ")"
        ), "roll"))
        r.append(rule("whole", j(
            B, "(?:the|a)", S, #"(?<w>hole)"#, S, "(?=", alt(
                "lot thing team day week month year time point idea process ", "company world project system app page website document bunch ", "new"), E, ")"
        ), "whole"))
        r.append(rule("bear_with", j(
            B, #"(?<w>bare)"#, S,
            "(?=(?:with", S, "(?:me|us)|in", S, "mind)", E, ")"
        ), "bear"))
        r.append(rule("the_past", j(
            B, "the", S, #"(?<w>passed)"#, E,
            "(?=", END, "|", S, alt(
                "week month year few couple hour days weeks months years decade ", "day night two three"), E, ")"
        ), "past"))
        r.append(rule("take_a_break", j(
            B, "(?:(?:take|took|taking|takes|grab)", S, "a|lunch|coffee|",
            "tea|summer|christmas|easter)", S, #"(?<w>brake)"#, E,
            "(?!", S, alt("pad pads fluid light lights disc discs pedal ", "system line lines caliper cable"), E, ")"
        ), "break"))
        r.append(rule("where_is", j(
            #"(?:^|(?<=[.!?\n]))[ \t]*(?<w>wear)"#, S, "(?=", alt(
                "is are was were does did can should would has have"), E, ")"
        ), "where"))

        return r
    }

    // MARK: casing

    /// Python str.isupper(): at least one cased char, none lowercase.
    private static func isUpperStr(_ s: String) -> Bool {
        var cased = false
        for ch in s {
            if ch.isLowercase { return false }
            if ch.isUppercase { cased = true }
        }
        return cased
    }

    /// The replacement takes the old word's capital only where a capital
    /// belongs: a sentence start, or a Title Case phrase for rules that keep
    /// one. A capital anywhere else was the engine's mistake ("Revenue One").
    private static func cased(_ new: String, _ old: String, _ text: String,
                              _ pos: Int, _ keepTitle: Bool) -> String {
        if old.count > 1 && isUpperStr(old) {
            return new.uppercased()
        }
        if let f = old.first, f.isUppercase, keepTitle || atSentenceStart(text, pos) {
            return new.upperFirst
        }
        return new
    }

    // MARK: fix

    /// Pick the right spelling of each sound-alike word the rules recognise.
    /// Returns the text unchanged when no rule fires. Only the one word a rule
    /// names is ever replaced; spacing, punctuation and line breaks are kept.
    ///
    /// `wordConfidence`, when non-nil, holds one entry per whitespace-separated
    /// word of `text` (nil = unknown). Rules marked `unsure` need it: without
    /// it, or where a word cannot be aligned to it, they never fire.
    public static func fix(_ text: String, wordConfidence: [Double?]? = nil) -> String {
        if text.isEmpty { return text }
        var recorded: [WordConfidence.Recorded] = []
        if let wc = wordConfidence, !wc.isEmpty {
            recorded = WordConfidence.recorded(from: text, perWord: wc)
        }
        var result = text
        for rule in rules {
            let current = result
            var confAt: [Int: Double]? = nil
            if rule.unsure != nil {
                if recorded.isEmpty || rule.pattern.search(current) == nil { continue }
                confAt = WordConfidence.byOffset(current, recorded)
            }
            let theConfAt = confAt
            result = rule.pattern.sub(current) { (m: PyMatch) -> String in
                let whole: String = m.group(0) ?? ""
                if let g = rule.guardFn, !g(current, m) { return whole }
                let wr: NSRange = m.result.range(withName: "w")
                if wr.location == NSNotFound { return whole }
                if let table = theConfAt, let limit = rule.unsure {
                    guard let c = table[wr.location], c < limit else { return whole }
                }
                let old: String = m.group("w") ?? ""
                let new: String = cased(rule.replacement, old, current, wr.location, rule.keepTitle)
                if new == old { return whole }
                let ws: Int = wr.location - m.result.range.location
                let wholeNS = NSString(string: whole)
                if ws < 0 || ws + wr.length > wholeNS.length { return whole }
                return wholeNS.substring(to: ws) + new + wholeNS.substring(from: ws + wr.length)
            }
        }
        return result
    }
}
