import XCTest
@testable import EchoCore

/// Stutter / false-start collapse (ported from tests/test_destutter.py).
/// Both directions are pinned: a stutter that survives is the reported want;
/// real speech being rewritten is the worse regression.
final class DisfluencyTests: XCTestCase {

    private func check(_ cases: [(String, String)], file: StaticString = #filePath, line: UInt = #line) {
        for (src, want) in cases {
            XCTAssertEqual(Disfluency.destutter(src), want, src, file: file, line: line)
        }
    }

    private func keeps(_ cases: [String], file: StaticString = #filePath, line: UInt = #line) {
        for s in cases {
            XCTAssertEqual(Disfluency.destutter(s), s, s, file: file, line: line)
        }
    }

    // MARK: false starts

    func testTheReportedExample() {
        XCTAssertEqual(Disfluency.destutter("push all most rec recent changes"),
                       "push all most recent changes")
    }

    func testReportedExampleInASentence() {
        XCTAssertEqual(
            Disfluency.destutter("Do this and then push almost rec recent changes to main."),
            "Do this and then push almost recent changes to main.")
    }

    func testCommonFragments() {
        check([
            ("prob probably not", "probably not"),
            ("def definitely yes", "definitely yes"),
            ("the config configuration file", "the configuration file"),
            ("trans transcription is slow", "transcription is slow"),
            ("be able to re resize stuff", "be able to resize stuff"),
        ])
    }

    func testLeadingCapitalCarriesToTheKeptWord() {
        XCTAssertEqual(Disfluency.destutter("Rec recent changes"), "Recent changes")
    }

    func testFragmentAcrossAComma() {
        XCTAssertEqual(Disfluency.destutter("push rec, recent changes"), "push recent changes")
    }

    // MARK: function-word doubles

    func testCommonDoubles() {
        check([
            ("I I think we should go", "I think we should go"),
            ("the the file is here", "the file is here"),
            ("optimal usage for for this task", "optimal usage for this task"),
            ("right but it it then just", "right but it then just"),
            ("they actually do do something", "they actually do something"),
        ])
    }

    func testTripleCollapsesToOne() {
        XCTAssertEqual(Disfluency.destutter("turn it on on on or off"), "turn it on or off")
    }

    func testARestartCapitalMidSentenceIsLowered() {
        XCTAssertEqual(Disfluency.destutter("ones you restricted and And if I"),
                       "ones you restricted and if I")
        XCTAssertEqual(Disfluency.destutter("make sure it's also a A thing"),
                       "make sure it's also a thing")
    }

    func testIAndAcronymsKeepTheirCapitals() {
        XCTAssertEqual(Disfluency.destutter("so i I think"), "so I think")
        XCTAssertEqual(Disfluency.destutter("then it IT said"), "then it IT said")
    }

    func testWiderNeverDoubledWords() {
        check([
            ("have like if if you can", "have like if you can"),
            ("so it's it's it's much easier", "so it's much easier"),
            ("Yeah, just just just come up with", "Yeah, just come up with"),
            ("What what do you think", "What do you think"),
            ("it would be more more potentially", "it would be more potentially"),
            ("Can you also make make it so", "Can you also make it so"),
            ("an easy transition between between them", "an easy transition between them"),
            ("stuff that I've I've liked", "stuff that I've liked"),
            ("so yeah, maybe maybe leave it", "so yeah, maybe leave it"),
            ("because they\u{2019}re they\u{2019}re things", "because they\u{2019}re things"),
        ])
    }

    // MARK: phrase restarts

    func testRestartsCollapse() {
        check([
            ("notes or something in the in the CRM", "notes or something in the CRM"),
            ("the thing to be to be like the side", "the thing to be like the side"),
            ("you know, it will it will basically tell you",
             "you know, it will basically tell you"),
            ("Bring that up to fill the fill the space.", "Bring that up to fill the space."),
            ("the home page? Does it does it like slowly change",
             "the home page? Does it like slowly change"),
            ("and then, like, if you're If you're working overtime",
             "and then, like, if you're working overtime"),
            ("I want to I want to go", "I want to go"),
            ("in the in the in the CRM", "in the CRM"),
        ])
    }

    func testARestartAtTheStartKeepsItsCapital() {
        XCTAssertEqual(Disfluency.destutter("In the in the morning we go"),
                       "In the morning we go")
    }

    func testEmphasisAndIdiomsSurvive() {
        keeps([
            "I know, I know, it's late.", "come on, come on, hurry up",
            "thank you thank you so much", "it went on and on and on",
            "over and over and over again", "breathe in and out, in and out",
            "you know you know", "It's fine, it's fine.", "do it, do it",
            "one two one two testing", "much much better",
            "hold on hold on", "For example. For example, if",
            "Is it? Is it?",
        ])
    }

    // MARK: never touch

    func testAWordThatPrefixesTheNextButIsARealWord() {
        keeps(["the theory of everything", "does he help me",
               "in industry today", "we website today", "part party time",
               "so sophisticated"])
    }

    func testBaseThenInflectedIsTwoWords() {
        keeps(["I bought a car cars are expensive", "read reading is fun",
               "book books on the shelf", "help helped him", "form former self"])
    }

    func testEmphaticAndGrammaticalDoublesSurvive() {
        keeps(["it was very very important", "no no that is fine",
               "he had had enough", "I know that that report is late",
               "much much better"])
    }

    func testLightFillerDoublesAreCollapsed() {
        check([
            ("like like this", "like this"),
            ("yeah yeah I know", "yeah I know"),
            ("so so good", "so good"),
            ("really really quick", "really quick"),
            ("right right let's go", "right let's go"),
            ("well well basically", "well basically"),
            ("okay okay done", "okay done"),
            ("I was like like waiting", "I was like waiting"),
            ("so yeah, yeah maybe leave it", "so yeah maybe leave it"),
            ("and and and then", "and then"),
            ("so so so tired", "so tired"),
        ])
    }

    func testTripleRepeatCatchallCollapsesAnyWord() {
        check([
            ("very very very important", "very important"),
            ("no no no that is fine", "no that is fine"),
            ("had had had enough", "had enough"),
            ("that that that report", "that report"),
            ("the the the file", "the file"),
            ("I I I think", "I think"),
            ("and and and and then", "and then"),
            ("stop stop stop doing that", "stop doing that"),
            ("look look look at this", "look at this"),
            ("go go go to the", "go to the"),
            ("very very good", "very very good"),
            ("very very very good", "very good"),
        ])
    }

    func testSentenceBoundaryIsNeverCrossed() {
        XCTAssertEqual(Disfluency.destutter("the cat. Cat food is here."),
                       "the cat. Cat food is here.")
    }

    func testContentWordDoubleIsNotCollapsed() {
        XCTAssertEqual(Disfluency.destutter("recent recent thing"), "recent recent thing")
    }

    func testShortAndEmptyInputs() {
        for s in ["", "hello", "  ", "one two three"] {
            XCTAssertEqual(Disfluency.destutter(s), s, "\"\(s)\"")
        }
    }

    // MARK: whitespace

    func testParagraphBreakSurvivesACollapse() {
        let src = "para one has for for this.\n\nPara two is clean."
        XCTAssertEqual(Disfluency.destutter(src),
                       "para one has for this.\n\nPara two is clean.")
    }

    func testNoQualifyingPairReturnsIdentical() {
        let src = "line one\n\nline two\twith  odd   spacing"
        XCTAssertEqual(Disfluency.destutter(src), src)
    }

    // MARK: known stutters (verbatim dictations)

    func testTheTwoKnownStuttersAreActuallyFixed() {
        let known: [(String, String)] = [
            ("push all most rec recent changes", "push all most recent changes"),
            ("I also want to add an option, so if like on the the chat bot.",
             "I also want to add an option, so if like on the chat bot."),
        ]
        for (before, after) in known {
            XCTAssertNotEqual(before, after, "fixture pins no collapse")
            XCTAssertEqual(Disfluency.destutter(before), after, before)
        }
    }
}
