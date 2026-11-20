import XCTest
@testable import EchoCore

/// Sound-alike words picked from the rest of the sentence (ported from
/// tests/test_homophones.py). The fix cases are the reported want; the
/// must-not-fire cases are the worse regression, because this code rewrites
/// words the user genuinely said.
final class HomophonesTests: XCTestCase {

    private func fixes(_ cases: [(String, String)], file: StaticString = #filePath, line: UInt = #line) {
        for (src, want) in cases {
            XCTAssertEqual(Homophones.fix(src), want, src, file: file, line: line)
        }
    }

    private func keeps(_ cases: [String], file: StaticString = #filePath, line: UInt = #line) {
        for src in cases {
            XCTAssertEqual(Homophones.fix(src), src, src, file: file, line: line)
        }
    }

    // MARK: the reported case

    func testTheReportedDictationBothEngines() {
        fixes([
            ("Revenue one this quarter.", "Revenue won this quarter."),
            // Parakeet capitalised the mis-picked word as if it were a name;
            // that capital is the mistake and must not survive.
            ("Revenue One this quarter.", "Revenue won this quarter."),
        ])
    }

    func testSameShapeOtherSalesNouns() {
        fixes([
            ("Deals one so far this year", "Deals won so far this year"),
            ("new business one since March", "new business won since March"),
            ("clients one against Acme", "clients won against Acme"),
            ("Tenders one in Q3 were up", "Tenders won in Q3 were up"),
        ])
    }

    func testEnumerationsAreNotTheVerb() {
        keeps([
            "Phase one this quarter.",
            "We're shipping deal one this week.",
            "Step one today, step two tomorrow.",
            "We lost two customers one this week and one last week.",
            "We lost two customers one this week.",
            "Two new clients one since Monday.",
        ])
    }

    // MARK: one -> won

    func testSubjectPronoun() {
        fixes([
            ("We one the Acme tender.", "We won the Acme tender."),
            ("I think they one it.", "I think they won it."),
            ("She one.", "She won."),
        ])
    }

    func testSubjectPronounCountsAndPronounsStay() {
        keeps([
            "Is she one of them?",
            "Am I one?",
            "Are we one team or two?",
            "We one day decided to leave.",
            "I one time went there.",
            "They one by one left the room.",
            "Did we one?",
            "I owe you one.",
            "Can you give me one the same colour?",
        ])
    }

    func testHavePlusObject() {
        fixes([
            ("We have one the contract", "We have won the contract"),
            ("they've one three awards", "they've won three awards"),
            ("she has one it twice", "she has won it twice"),
            ("We've finally one the tender", "We've finally won the tender"),
        ])
    }

    func testHaveOneAsACountStays() {
        keeps([
            "I have one.",
            "Can I have one back?",
            "I had one the other day.",
            "I had one again this morning.",
            "I have one every day.",
            "We have one this week.",
            "We have one the whole time.",
            "Do you have one the size of a phone?",
            "I have one deal left.",
            "We have one more to go.",
        ])
    }

    func testMarginAndOutcomePairs() {
        fixes([
            ("It was one by a landslide", "It was won by a landslide"),
            ("how many deals were one or lost", "how many deals were won or lost"),
            ("deals lost and one", "deals lost and won"),
        ])
        keeps(["one by one", "one by the window"])
    }

    func testClosedWonStage() {
        fixes([
            ("move it to closed one", "move it to closed won"),
            ("Marked as Closed One.", "Marked as Closed Won."),
            ("closed one and closed lost", "closed won and closed lost"),
        ])
        keeps(["I closed one yesterday.", "We closed one this week."])
    }

    func testWonToOne() {
        fixes([
            ("won of the best", "one of the best"),
            ("No won knows.", "No one knows."),
            ("this won is better", "this one is better"),
        ])
        keeps([
            "We won of course.",
            "There were no won deals this month.",
            "The bid that won.",
            "This won us the deal.",
            "We won more time.",
        ])
    }

    // MARK: other pairs

    func testThen() {
        fixes([
            ("more then a hundred", "more than a hundred"),
            ("better then ever", "better than ever"),
            ("other then that it's fine", "other than that it's fine"),
            ("bigger then expected", "bigger than expected"),
        ])
        keeps([
            "See you later then.",
            "Add a bit more then save it.",
            "We'll call each other then.",
            "It gets bigger then smaller.",
            "If we get more then we can start.",
        ])
    }

    func testModalOf() {
        fixes([("I should of done it", "I should have done it"),
               ("it could of been worse", "it could have been worse")])
        keeps(["In May of last year", "what should of course happen"])
    }

    func testWhether() {
        fixes([("weather or not", "whether or not"),
               ("I don't know weather we should go", "I don't know whether we should go")])
        keeps(["The weather or not much else.", "The weather we had was awful.",
               "Nice weather we're having."])
    }

    func testYourYoure() {
        fixes([
            ("your going to love it", "you're going to love it"),
            ("your not wrong", "you're not wrong"),
            ("Thanks. Your welcome.", "Thanks. You're welcome."),
            ("do it you're own way", "do it your own way"),
            ("thanks for you're feedback", "thanks for your feedback"),
        ])
        keeps([
            "Send your welcome email.",
            "your not-for-profit arm",
            "It's your right to ask.",
            "you're team lead now",
            "you're account manager for Acme",
            "you're number one",
            "your going-away party",
        ])
    }

    func testIts() {
        fixes([("its the newest one", "it's the newest one"),
               ("its been a while", "it's been a while"),
               ("it has it's own page", "it has its own page")])
        keeps(["its own page", "its really good battery life",
               "in its time", "its fine print", "its going rate"])
    }

    func testThereTheir() {
        fixes([("Their is a problem", "There is a problem"),
               ("their will be a delay", "there will be a delay"),
               ("they have there own team", "they have their own team")])
        keeps(["their team is great", "Is there going to be a demo?",
               "Are there all kinds of options?", "over there"])
    }

    func testToo() {
        fixes([("It's way to expensive", "It's way too expensive"),
               ("that is to late", "that is too late"),
               ("not to bad", "not too bad")])
        keeps([
            "The plan is to close the deal.",
            "The aim is to slow the spread.",
            "The goal is to short the stock.",
            "I went to many places.",
            "we're getting to many customers now",
            "way to go",
            "the idea was to hard-code it",
        ])
    }

    func testWriteRight() {
        fixes([
            ("Right an email to John", "Write an email to John"),
            ("can you right me a summary", "can you write me a summary"),
            ("right that down", "write that down"),
        ])
        keeps([
            "All right the report is done.",
            "That's right an email came in.",
            "Yeah right a note would help.",
            "Turn right a letter box is there.",
            "right a wrong",
            "right down the road",
            "I'll write now",
        ])
    }

    func testHearHere() {
        fixes([("I can't here you", "I can't hear you"),
               ("looking forward to here from you", "looking forward to hear from you"),
               ("come in hear.", "come in here.")])
        keeps(["Are you here about the job?", "from there to here it takes an hour",
               "fly to here from London", "come hear the band"])
    }

    func testKnowNo() {
        fixes([("let me no", "let me know"), ("I don't no", "I don't know"),
               ("you no what", "you know what")])
        keeps(["I no longer work there", "let me no longer wait",
               "don't no matter what"])
    }

    func testWeekWeak() {
        fixes([("see you next weak.", "see you next week."),
               ("a weak ago", "a week ago"), ("two weaks ago", "two weeks ago")])
        keeps(["this weak argument", "the last weak point", "every weak link"])
    }

    func testFixedPhrases() {
        fixes([
            ("for piece of mind", "for peace of mind"),
            ("a peace of code", "a piece of code"),
            ("out of site.", "out of sight."),
            ("don't lose site of it", "don't lose sight of it"),
            ("role out the update", "roll out the update"),
            ("a great roll model", "a great role model"),
            ("we're on a role today", "we're on a roll today"),
            ("the hole team", "the whole team"),
            ("bare with me", "bear with me"),
            ("in the passed.", "in the past."),
            ("take a brake", "take a break"),
            ("Wear is the file?", "Where is the file?"),
        ])
        keeps([
            "which role out of these",
            "take on a role that suits you",
            "check the brake pads",
            "dig the hole deeper",
            "What to wear is up to you.",
            "the dice roll",
        ])
    }

    // MARK: confidence-gated rules

    /// Per-whitespace-word confidences for `text`: every word `conf`, words
    /// whose normalised spelling is in `unsure` at `low`.
    private func rec(_ text: String, unsure: Set<String> = [], conf: Double = 0.97,
                     low: Double = 0.55) -> [Double?] {
        var out: [Double?] = []
        for token in text.pySplit {
            let w = WordConfidence.normaliseWord(token)
            out.append(unsure.contains(w) ? low : conf)
        }
        return out
    }

    private func fixUnsure(_ src: String, _ words: Set<String>) -> String {
        return Homophones.fix(src, wordConfidence: rec(src, unsure: words))
    }

    private func keepsWhenAllUnsure(_ cases: [String], file: StaticString = #filePath, line: UInt = #line) {
        for src in cases {
            XCTAssertEqual(Homophones.fix(src, wordConfidence: rec(src, conf: 0.3)), src,
                           src, file: file, line: line)
        }
    }

    func testReportedTwoForToo() {
        // "push the usage card fixes too", Parakeet "two" at 0.62.
        let cases: [(String, String)] = [
            ("Push the usage card fixes two.", "Push the usage card fixes too."),
            ("the usage card fixes two, but like it reads",
             "the usage card fixes too, but like it reads"),
            ("Can you check the logs two please", "Can you check the logs too please"),
        ]
        for (src, want) in cases {
            XCTAssertEqual(fixUnsure(src, ["two"]), want, src)
        }
    }

    func testTwoNeedsTheEngineUnsure() {
        let src = "Push the usage card fixes two."
        XCTAssertEqual(Homophones.fix(src), src)                                      // no record
        XCTAssertEqual(Homophones.fix(src, wordConfidence: rec(src)), src)            // sure
        XCTAssertEqual(Homophones.fix(src, wordConfidence: [0.3]), src)               // two unknown
    }

    func testTwoAsACountNeverFires() {
        keepsWhenAllUnsure([
            "I want the other two.", "Take two.", "We sold two.",
            "Give me two.", "Just the two.", "One or two.", "Maybe two.",
            "Page two.", "Step two, then we deploy.", "We need two.",
            "I bought two, but one broke.", "There are two.",
            "I watched Toy Story two.", "Phase one and phase two.",
            "Table for two.", "Between one and two.", "Count to two.",
            "Those two.", "You two.", "Us two.", "Version two.",
            "It was two, then three.", "About two.", "Line two.",
            "If you want me to.", "I'd love to but I can't.",
        ])
    }

    func testReportedCallForCool() {
        let cases: [(String, String)] = [
            ("thought that'd be call.", "thought that'd be cool."),
            ("That would be call, yeah.", "That would be cool, yeah."),
            ("It'll be pretty call.", "It'll be pretty cool."),
            ("That's call.", "That's cool."),
            ("Sounds call with me.", "Sounds cool with me."),
        ]
        for (src, want) in cases {
            XCTAssertEqual(fixUnsure(src, ["call"]), want, src)
        }
    }

    func testCoolForCall() {
        let cases: [(String, String)] = [
            ("I'll cool you back later.", "I'll call you back later."),
            ("Give me a cool tomorrow.", "Give me a call tomorrow."),
            ("can you give him a quick cool when you're free",
             "can you give him a quick call when you're free"),
        ]
        for (src, want) in cases {
            XCTAssertEqual(fixUnsure(src, ["cool"]), want, src)
        }
    }

    func testCallAndCoolMustNotFire() {
        keepsWhenAllUnsure([
            "Who would you call.", "Do they really call?", "It's not like you'd call.",
            "The next step will be call them.", "If so call me.",
            "It's call or text, your choice.", "That's a call for the client.",
            "Let them cool down.", "We'll cool them in the fridge.",
            "I'll cool them overnight.", "Give it a cool drink.",
            "Leave it to cool.", "That's so cool.", "It'd be cool to call.",
            "Call me later.", "We should call them back.",
        ])
    }

    func testCoolBeNeedsTheEngineUnsure() {
        let src = "That would be call."
        XCTAssertEqual(Homophones.fix(src, wordConfidence: rec(src, conf: 0.99)), src)
    }

    // MARK: mechanics

    func testPunctuationIsTheSpeakersBoundary() {
        // A comma or stop between the words ends the shape.
        keeps(["Revenue, one this quarter.", "We, one the deal", "we have one, the contract"])
    }

    func testSpacingAndLineBreaksKept() {
        let src = "Hi John,\n\nRevenue one this quarter.\n\nKind regards,\nRyan"
        XCTAssertEqual(Homophones.fix(src),
                       "Hi John,\n\nRevenue won this quarter.\n\nKind regards,\nRyan")
    }

    func testSentenceStartAndAllCaps() {
        fixes([("Their is one.", "There is one."),
               ("THEIR IS A BUG", "THERE IS A BUG")])
    }

    func testNotInsidePathsOrHandles() {
        keeps(["open /revenue one this", "tag #their is"])
    }

    func testEmptyAndUntouched() {
        XCTAssertEqual(Homophones.fix(""), "")
        keeps(["Hello, my name is Ryan. This is a test."])
    }

    func testFastOnALongDictation() {
        // Runs on the stop-to-text path: a 700-word dictation must stay far
        // below anything a person could notice. (The Python bound is 50 ms; a
        // generous 1 s here keeps a debug build on a busy CI machine from
        // flaking while still catching accidental quadratic behaviour.)
        let unit = "Okay so we had a really good quarter and I think revenue "
            + "one this quarter is up on last year, but there is more then "
            + "one thing to do. "
        let text = String(repeating: unit, count: 25)
        _ = Homophones.fix("warm up the regex cache")
        let t0 = Date()
        _ = Homophones.fix(text)
        XCTAssertLessThan(Date().timeIntervalSince(t0), 1.0)
    }
}
