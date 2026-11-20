import XCTest
@testable import EchoCore

/// Terminal punctuation (ported from tests/test_sentence_end.py). Inputs are
/// written the way the engine actually delivers them: already closed.
final class SentenceEndTests: XCTestCase {

    private func smart(_ s: String) -> String { SentenceEnd.apply(s, mode: .smart) }
    private func always(_ s: String) -> String { SentenceEnd.apply(s, mode: .always) }
    private func never(_ s: String) -> String { SentenceEnd.apply(s, mode: .never) }

    // MARK: smart adds

    func testPlainSentence() {
        XCTAssertEqual(smart("this is a finished sentence"), "this is a finished sentence.")
    }

    func testLongerProse() {
        XCTAssertEqual(smart("I have pushed the change to main"),
                       "I have pushed the change to main.")
    }

    func testAFinishedSentenceKeepsTheEnginesStop() {
        let cases: [String] = [
            "I have pushed the change to main.",
            "Do this and then run it locally so I can see it.",
            "He said \"no.\"",
        ]
        for s in cases { XCTAssertEqual(smart(s), s) }
    }

    func testQuestionAndExclamationAreUntouched() {
        for s in ["Really?", "Stop!", "What time?", "and then?"] {
            XCTAssertEqual(smart(s), s)
        }
    }

    func testAnAbbreviationDotIsNotAStop() {
        for s in ["See you at 7 p.m.", "Apples, pears, etc."] {
            XCTAssertEqual(smart(s), s)
        }
    }

    // MARK: smart leaves open

    func testHangingConjunction() {
        for s in ["and then the invoice for", "we should probably go and",
                  "put it in the", "send that over to"] {
            XCTAssertEqual(smart(s), s)
        }
    }

    func testTheEnginesStopComesOffAFragment() {
        let cases: [(String, String)] = [
            ("I also want it to not add a full stop at the.",
             "I also want it to not add a full stop at the"),
            ("We push all the most recent changes to main, so.",
             "We push all the most recent changes to main, so"),
            ("Trapezium shape.", "Trapezium shape"),
            ("ryan.murphy@ftc-ss.com.", "ryan.murphy@ftc-ss.com"),
            ("Compose.io.", "Compose.io"),
            ("Consultancy.", "Consultancy"),
        ]
        for (spoken, want) in cases {
            XCTAssertEqual(smart(spoken), want, spoken)
        }
    }

    func testShortFragments() {
        for s in ["yes", "one moment", "about half", "roughly"] {
            XCTAssertEqual(smart(s), s)
        }
        for s in ["Yes.", "One moment.", "About half."] {
            XCTAssertEqual(smart(s), String(s.dropLast()))
        }
    }

    func testTrailingCommaIsStrippedNotClosed() {
        XCTAssertEqual(smart("carry on with the next bit,"), "carry on with the next bit")
    }

    func testAddressNeverGetsAStop() {
        for s in ["ryan.murphy@ftc-ss.com", "go to ftc-ss.com", "open the report.pdf"] {
            XCTAssertEqual(smart(s), s)
        }
    }

    func testOpenBracket() {
        XCTAssertEqual(smart("the total was ("), "the total was (")
    }

    // MARK: always and never

    func testAlwaysMatchesTheOldBehaviour() {
        XCTAssertEqual(always("one moment"), "one moment.")
        XCTAssertEqual(always("and then the"), "and then the.")
        XCTAssertEqual(always("Done."), "Done.")
    }

    func testAlwaysReplacesATrailingCommaNeverStacks() {
        XCTAssertEqual(always("then,"), "then.")
    }

    func testNeverAddsNothing() {
        XCTAssertEqual(never("this is a finished sentence"), "this is a finished sentence")
    }

    func testNeverRemovesTheEnginesFullStop() {
        XCTAssertEqual(never("So think that could look good generate it."),
                       "So think that could look good generate it")
        XCTAssertEqual(never("Done."), "Done")
    }

    func testNeverOnlyTouchesTheEnd() {
        XCTAssertEqual(never("One thing. Then another."), "One thing. Then another")
        XCTAssertEqual(never("First paragraph.\n\nSecond paragraph."),
                       "First paragraph.\n\nSecond paragraph")
    }

    func testNeverKeepsQuestionAndExclamation() {
        for s in ["Can you do that?", "Stop!"] {
            XCTAssertEqual(never(s), s)
        }
    }

    func testNeverKeepsEllipsesAndAbbreviations() {
        for s in ["and then...", "and then\u{2026}", "meet at 7 p.m.",
                  "the U.S.", "apples, pears, etc."] {
            XCTAssertEqual(never(s), s)
        }
    }

    func testNeverStripsInsideAClosingQuote() {
        XCTAssertEqual(never("He said \"no.\""), "He said \"no\"")
        XCTAssertEqual(never("(see the notes.)"), "(see the notes)")
    }

    func testNeverStillStripsThePauseArtefact() {
        XCTAssertEqual(never("finished up here,"), "finished up here")
    }

    func testALoneStopIsNotEmptied() {
        XCTAssertEqual(never("."), ".")
    }

    func testUnknownModeFallsBackToSmart() {
        let mode: EndPunctuation = EndPunctuation(rawValue: "nonsense") ?? .smart
        XCTAssertEqual(SentenceEnd.apply("one moment", mode: mode), "one moment")
        XCTAssertEqual(SentenceEnd.apply("One moment.", mode: mode), "One moment")
    }

    func testDefaultModeIsSmart() {
        XCTAssertEqual(SentenceEnd.apply("one moment"), "one moment")
        XCTAssertEqual(SentenceEnd.apply("this is a finished sentence"),
                       "this is a finished sentence.")
    }

    func testEmpty() {
        XCTAssertEqual(smart(""), "")
        XCTAssertEqual(always("   "), "")
    }

    func testModesRoundTripThroughRawValues() {
        XCTAssertEqual(EndPunctuation.allCases.map { $0.rawValue }, ["smart", "always", "never"])
    }

    // MARK: match ending

    func testAStopTheSettingRemovedStaysRemoved() {
        XCTAssertEqual(SentenceEnd.matchEnding(candidate: "Generate it.", reference: "generate it"),
                       "Generate it")
    }

    func testAStopThatWasInsertedIsKept() {
        XCTAssertEqual(SentenceEnd.matchEnding(candidate: "It is done", reference: "It is done."),
                       "It is done.")
        XCTAssertEqual(SentenceEnd.matchEnding(candidate: "Fine, done.", reference: "fine done."),
                       "Fine, done.")
    }

    func testQuestionMarksAreTheCorrectionsCall() {
        XCTAssertEqual(SentenceEnd.matchEnding(candidate: "Is it done?", reference: "is it done"),
                       "Is it done?")
    }

    func testEmptyInputsPassThrough() {
        XCTAssertEqual(SentenceEnd.matchEnding(candidate: "", reference: "x"), "")
        XCTAssertEqual(SentenceEnd.matchEnding(candidate: "Text.", reference: ""), "Text.")
    }

    // MARK: predicates

    func testPredicates() {
        XCTAssertTrue(SentenceEnd.alreadyTerminated("He said \"no.\""))
        XCTAssertFalse(SentenceEnd.alreadyTerminated("and then"))
        XCTAssertTrue(SentenceEnd.endsWithFullStop("Done."))
        XCTAssertFalse(SentenceEnd.endsWithFullStop("Done..."))
        XCTAssertFalse(SentenceEnd.endsWithFullStop("the U.S."))
        XCTAssertEqual(SentenceEnd.stripFullStop("He said \"no.\""), "He said \"no\"")
        XCTAssertFalse(SentenceEnd.looksFinished("one moment"))
        XCTAssertTrue(SentenceEnd.looksFinished("this is a finished sentence"))
    }
}
