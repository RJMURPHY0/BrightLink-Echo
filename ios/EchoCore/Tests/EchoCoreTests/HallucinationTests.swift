import XCTest
@testable import EchoCore

/// Degenerate-repetition guard (ported from tests/test_hallucination.py).
/// Both directions are pinned: a loop that survives is the reported bug; real
/// speech being rewritten is the worse regression.
final class HallucinationTests: XCTestCase {

    private func occurrences(of needle: String, in haystack: String) -> Int {
        return haystack.components(separatedBy: needle).count - 1
    }

    private func rep(_ s: String, _ n: Int) -> String {
        return String(repeating: s, count: n)
    }

    // MARK: pure-loop suppression

    func testTheReportedFailure() {
        let text = "No, " + rep("no, ", 38) + "no."
        XCTAssertEqual(Hallucination.clean(text), "")
    }

    func testPureLoopOfAPhrase() {
        let text = [String](repeating: "I don't know.", count: 8).joined(separator: " ")
        XCTAssertEqual(Hallucination.clean(text), "")
    }

    func testPureLoopNeedsSixRepeats() {
        // Five is trimmed but NOT wiped.
        XCTAssertNotEqual(Hallucination.clean("No, no, no, no, no."), "")
    }

    func testIsPureLoopIgnoresPunctuationAndCase() {
        XCTAssertTrue(Hallucination.isPureLoop("No, no. NO no, no, no, no"))
    }

    func testPunctuationOnlyInputIsNotALoop() {
        XCTAssertFalse(Hallucination.isPureLoop(". . . . . . . ."))
    }

    // MARK: collapse

    func testEmbeddedLoopIsCollapsedAndSpeechSurvives() {
        let text = "I said " + rep("no, ", 20) + "and then I left."
        let out = Hallucination.clean(text)
        XCTAssertTrue(out.contains("I said"))
        XCTAssertTrue(out.contains("and then I left."))
        XCTAssertEqual(occurrences(of: "no", in: out.lowercased()), 3)
    }

    func testCollapseKeepsTerminalPunctuationOfTheRun() {
        let out = Hallucination.clean("Well " + rep("no, ", 9) + "no. Then we left.")
        XCTAssertTrue(out.contains("no."))
        XCTAssertTrue(out.contains("Then we left."))
    }

    func testPhraseLoopCollapsedWithinRealSpeech() {
        let text = "Honestly " + rep("I don't know. ", 9) + "But we should ask."
        let out = Hallucination.clean(text)
        XCTAssertTrue(out.contains("Honestly"))
        XCTAssertTrue(out.contains("But we should ask."))
        XCTAssertEqual(occurrences(of: "I don't know", in: out), 3)
    }

    func testLeadingCapitalIsPreserved() {
        let out = Hallucination.clean("No, " + rep("no, ", 10) + "yes it is.")
        XCTAssertTrue(out.hasPrefix("No,"))
    }

    // MARK: real speech untouched

    func testOrdinarySentenceIsUnchanged() {
        let text = "The site inspection is booked for Tuesday and I need the "
            + "risk assessment signed off before anyone goes on site."
        XCTAssertEqual(Hallucination.clean(text), text)
    }

    func testEmphaticTripleIsLeftAlone() {
        let text = "No, no, no, that is not what I meant."
        XCTAssertEqual(Hallucination.clean(text), text)
    }

    func testLegitimatelyRepeatedWordsSurvive() {
        let text = "It is very very good and that that clause needs redrafting."
        XCTAssertEqual(Hallucination.clean(text), text)
    }

    func testRepeatedWordNotAdjacentIsUntouched() {
        let text = "No I said no and he said no and then she said no as well."
        XCTAssertEqual(Hallucination.clean(text), text)
    }

    func testShortInputIsUntouched() {
        XCTAssertEqual(Hallucination.clean("No, no."), "No, no.")
    }

    func testEmptyIsSafe() {
        XCTAssertEqual(Hallucination.clean(""), "")
        XCTAssertFalse(Hallucination.isPureLoop(""))
    }
}
