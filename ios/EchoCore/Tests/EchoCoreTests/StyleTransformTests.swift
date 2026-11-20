import XCTest
@testable import EchoCore

final class StyleTransformTests: XCTestCase {
    private let sample = "Hey, are you free for lunch tomorrow? Let's do 12 if that works for you."

    func testFormalLeavesTextAlone() {
        XCTAssertEqual(StyleTransform.apply(sample, style: .formal), sample)
    }

    func testCasualDropsOnlyTheFinalFullStop() {
        XCTAssertEqual(
            StyleTransform.apply(sample, style: .casual),
            "Hey, are you free for lunch tomorrow? Let's do 12 if that works for you"
        )
        XCTAssertEqual(StyleTransform.apply("Are you coming?", style: .casual), "Are you coming?")
        XCTAssertEqual(StyleTransform.apply("Well...", style: .casual), "Well...")
    }

    func testVeryCasualLowercasesAndStripsSentencePunctuation() {
        XCTAssertEqual(
            StyleTransform.apply(sample, style: .veryCasual),
            "hey are you free for lunch tomorrow let's do 12 if that works for you"
        )
    }

    func testVeryCasualKeepsAcronymsNumbersAndAddresses() {
        XCTAssertEqual(
            StyleTransform.apply("The API costs 3.5 pounds at 12:30, email a.b@c.com.", style: .veryCasual),
            "the API costs 3.5 pounds at 12:30 email a.b@c.com"
        )
    }

    func testExcitedEndsWithExclamation() {
        XCTAssertEqual(StyleTransform.apply("That is great news.", style: .excited), "That is great news!")
        XCTAssertEqual(StyleTransform.apply("Is it done?", style: .excited), "Is it done?")
        XCTAssertEqual(StyleTransform.apply("See you soon", style: .excited), "See you soon!")
    }

    func testMultiLineTextIsNeverRestyled() {
        let list = "Shopping:\n1. Milk.\n2. Bread."
        for style in DictationStyle.allCases {
            XCTAssertEqual(StyleTransform.apply(list, style: style), list)
        }
    }

    func testEmptyStaysEmpty() {
        for style in DictationStyle.allCases {
            XCTAssertEqual(StyleTransform.apply("", style: style), "")
        }
    }
}
