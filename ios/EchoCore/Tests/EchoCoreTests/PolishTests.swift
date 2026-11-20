import XCTest
@testable import EchoCore

/// Pause-punctuation cleanup, lone-adverb merge, post-processing and polish
/// (ported from tests/test_pause_punctuation.py and
/// tests/test_lone_adverb_punctuation.py, plus the engine post-process cases).
final class PolishTests: XCTestCase {

    private func fix(_ s: String) -> String { Polish.fixPausePunctuation(s) }

    // MARK: pause punctuation

    func testStopBeforeConjunctionBecomesComma() {
        XCTAssertEqual(fix("I did it. And then we left"), "I did it, and then we left")
        XCTAssertEqual(fix("It works. But slowly"), "It works, but slowly")
        XCTAssertEqual(fix("Turn it on. Or off"), "Turn it on, or off")
    }

    func testStopBeforeLowercaseIsDropped() {
        XCTAssertEqual(fix("would actually be. inserted here"), "would actually be inserted here")
    }

    func testRealSentenceBoundaryIsKept() {
        let s = "I went home. She stayed behind."
        XCTAssertEqual(fix(s), s)
    }

    func testBecauseIsNotMerged() {
        let s = "I left. Because it was late"
        XCTAssertEqual(fix(s), s)
    }

    func testSingleLetterAbbreviationsAreSafe() {
        XCTAssertEqual(fix("meet at 9 a.m. and leave"), "meet at 9 a.m. and leave")
    }

    func testEllipsisIsUntouched() {
        let s = "wait... okay then"
        XCTAssertEqual(fix(s), s)
    }

    func testNoWordsAreAddedOrRemoved() {
        let src = "I want a crown. And it can be turned on. Or off. that is the idea"
        let out = fix(src)
        func words(_ t: String) -> [String] {
            return t.pySplit.map { $0.pyStrip(".,").lowercased() }
        }
        XCTAssertEqual(words(src), words(out))
    }

    func testEmptyIsSafe() {
        XCTAssertEqual(fix(""), "")
    }

    // MARK: lone adverb (the reported failure)

    func testTheExactReportedText() {
        XCTAssertEqual(fix("My Claude OS is set up 100%. Correctly. Everything works."),
                       "My Claude OS is set up 100% correctly. Everything works.")
    }

    func testStopAfterANumberThenLowercase() {
        XCTAssertEqual(fix("It is set up 100. correctly."), "It is set up 100 correctly.")
    }

    func testStopAfterAPercentageThenLowercase() {
        XCTAssertEqual(fix("It is set up 100%. correctly."), "It is set up 100% correctly.")
    }

    func testLoneAdverbAtTheVeryEnd() {
        XCTAssertEqual(fix("The whole thing is working. Properly."),
                       "The whole thing is working properly.")
    }

    // MARK: real sentences survive

    func testAdverbOpenerWithACommaIsUntouched() {
        let t = "That is done. Obviously, we should still check it."
        XCTAssertEqual(fix(t), t)
    }

    func testAdverbStartingALongerSentenceIsUntouched() {
        let t = "It failed. Basically the whole pipeline needs a rewrite."
        XCTAssertEqual(fix(t), t)
    }

    func testOrdinarySentenceBoundaryIsUntouched() {
        let t = "The scaffold is up. Inspection is booked for Tuesday."
        XCTAssertEqual(fix(t), t)
    }

    func testARealNumberSentenceEndIsUntouched() {
        let t = "The total came to 100. Then we went home."
        XCTAssertEqual(fix(t), t)
    }

    func testAbbreviationsAreUntouched() {
        let t = "Meet at 9 a.m. tomorrow."
        XCTAssertEqual(fix(t), t)
    }

    func testANounSentenceOfOneWordIsUntouched() {
        let t = "I asked him twice. Nothing."
        XCTAssertEqual(fix(t), t)
    }

    // MARK: no interaction with the existing rules

    func testConjunctionRuleStillApplies() {
        XCTAssertEqual(fix("I did it. And then I left."), "I did it, and then I left.")
    }

    func testLowercaseContinuationRuleStillApplies() {
        XCTAssertEqual(fix("would actually be. inserted"), "would actually be inserted")
    }

    func testBothArtefactsInOneUtterance() {
        XCTAssertEqual(fix("It is set up 100%. Correctly. And then we shipped it."),
                       "It is set up 100% correctly, and then we shipped it.")
    }

    // MARK: polish

    func testPolishFixesPauseThenCapitalises() {
        XCTAssertEqual(Polish.polish("would actually be. inserted here"),
                       "Would actually be inserted here.")
    }

    func testPolishFixesConjunction() {
        XCTAssertEqual(Polish.polish("i did it. And then we left"),
                       "I did it, and then we left.")
    }

    func testPolishOffWhenAutoPunctuateDisabled() {
        // The leading capital is always applied, but the de-pause pass and the
        // terminal stop are skipped.
        XCTAssertEqual(Polish.polish("i did it. And then", autoPunctuate: false),
                       "I did it. And then")
    }

    func testPolishRespectsEndPunctuationMode() {
        XCTAssertEqual(Polish.polish("this is a finished sentence", endPunctuation: .never),
                       "This is a finished sentence")
        XCTAssertEqual(Polish.polish("one moment", endPunctuation: .always), "One moment.")
    }

    func testPolishEmpty() {
        XCTAssertEqual(Polish.polish("   "), "")
    }

    // MARK: post-process (engine wiring)

    func testPostProcessSuppressesALoop() {
        let text = "No, " + String(repeating: "no, ", count: 38) + "no."
        XCTAssertEqual(Polish.postProcess(text), "")
    }

    func testPostProcessKeepsRealSpeech() {
        let out = Polish.postProcess("The scaffold inspection is due on Friday.")
        XCTAssertTrue(out.contains("scaffold inspection"))
    }

    func testPostProcessSuppressesFillerOnlyResults() {
        for s in ["Mm-hmm.", "um uh", "Hmm, hmm."] {
            XCTAssertEqual(Polish.postProcess(s), "", s)
        }
    }

    func testPostProcessStripsFillersAndTidiesCommas() {
        XCTAssertEqual(Polish.postProcess("So, um, I think"), "So, I think")
        XCTAssertEqual(Polish.postProcess("hello  world , ok"), "hello world, ok")
    }

    func testPostProcessCollapsesStutters() {
        XCTAssertEqual(Polish.postProcess("Um, push all most rec recent changes."),
                       "push all most recent changes.")
    }

    func testPostProcessVocabularyCasing() {
        XCTAssertEqual(Polish.postProcess("check the ftc whisper app", hotwords: ["FTC Whisper"]),
                       "check the FTC Whisper app")
        // A term on the function-word stoplist never forces casing.
        XCTAssertEqual(Polish.postProcess("the it team, it is a test", hotwords: ["IT"]),
                       "the it team, it is a test")
    }

    func testPostProcessEmpty() {
        XCTAssertEqual(Polish.postProcess(""), "")
        XCTAssertEqual(Polish.postProcess("   "), "")
    }
}
