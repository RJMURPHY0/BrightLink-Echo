import XCTest
@testable import Echo

final class BridgeTests: XCTestCase {
    func testDeadAppReadsAsOff() {
        var state = BridgeState()
        state.phase = .ready
        state.heartbeat = Date().addingTimeInterval(-10)
        XCTAssertEqual(state.effectivePhase(), .off)
        state.heartbeat = Date()
        XCTAssertEqual(state.effectivePhase(), .ready)
    }

    func testCommandRoundTripsThroughJSON() throws {
        let command = BridgeCommand(kind: .start, style: .excited)
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .millisecondsSince1970
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .millisecondsSince1970
        let back = try decoder.decode(BridgeCommand.self, from: encoder.encode(command))
        XCTAssertEqual(back.id, command.id)
        XCTAssertEqual(back.style, .excited)
        XCTAssertEqual(back.kind, .start)
    }

    @MainActor
    func testSilenceIsNeverTranscribed() {
        XCTAssertFalse(DictationController.hasSpeech([Float](repeating: 0, count: 16_000)))
        XCTAssertFalse(DictationController.hasSpeech([Float](repeating: 0.5, count: 100)))
        let tone = (0..<16_000).map { Float(sin(Double($0) * 0.05) * 0.1) }
        XCTAssertTrue(DictationController.hasSpeech(tone))
    }

    func testSecondStepCodeCleaning() {
        let app = SecondStepMethod(factorID: "f", kind: "app")
        XCTAssertEqual(app.clean("12 34-56789"), "123456")
        XCTAssertTrue(app.ready("123456"))
        let backup = SecondStepMethod(factorID: "f", kind: "backup")
        XCTAssertEqual(backup.clean("abcd-efgh!"), "ABCD-EFGH")
        XCTAssertTrue(backup.ready("ABCD-EFGH"))
    }
}
