import XCTest
@testable import EchoCore

/// Ported from the Python suite: every call below is a (input, output) pair taken from the Python tests
/// (outputs recorded from the Python implementation while its own tests passed).
final class EmailFormatTests: XCTestCase {
    // tests/test_email_format.py::LayoutTests::test_a_sentence_starter_is_not_part_of_the_name
    func test_email_format_LayoutTests_test_a_sentence_starter_is_not_part_of_the_name() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John I wanted to check the invoice.", senderName: "Ryan Murphy"), "Hi John,\n\nI wanted to check the invoice.")
    }

    // tests/test_email_format.py::LayoutTests::test_any_close_run_on_before_the_senders_own_name
    func test_email_format_LayoutTests_test_any_close_run_on_before_the_senders_own_name() {
        XCTAssertEqual(EmailFormat.formatEmail("see you then cheers Ryan", senderName: "Ryan Murphy"), "See you then.\n\nCheers,\nRyan")
    }

    // tests/test_email_format.py::LayoutTests::test_existing_paragraphs_are_kept
    func test_email_format_LayoutTests_test_existing_paragraphs_are_kept() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John,\n\nThanks for this.\n\nSecond point.\n\nKind regards, Ryan"), "Hi John,\n\nThanks for this.\n\nSecond point.\n\nKind regards,\nRyan")
    }

    // tests/test_email_format.py::LayoutTests::test_greeting_forms
    func test_email_format_LayoutTests_test_greeting_forms() {
        XCTAssertEqual(EmailFormat.formatEmail("Hello, I want to ask about the quote."), "Hello,\n\nI want to ask about the quote.")
    }

    // tests/test_email_format.py::LayoutTests::test_greeting_straight_into_sign_off
    func test_email_format_LayoutTests_test_greeting_straight_into_sign_off() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John, kind regards, Ryan"), "Hi John,\n\nKind regards,\nRyan")
    }

    // tests/test_email_format.py::LayoutTests::test_just_the_greeting_leaves_the_caret_on_the_body_line
    func test_email_format_LayoutTests_test_just_the_greeting_leaves_the_caret_on_the_body_line() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John."), "Hi John,\n\n")
        XCTAssertEqual(EmailFormat.formatEmail("Hey John"), "Hey John,\n\n")
    }

    // tests/test_email_format.py::LayoutTests::test_no_punctuation_after_the_greeting
    func test_email_format_LayoutTests_test_no_punctuation_after_the_greeting() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John thanks for your email. Kind regards Ryan"), "Hi John,\n\nThanks for your email.\n\nKind regards,\nRyan")
    }

    // tests/test_email_format.py::LayoutTests::test_sign_off_after_a_comma_closes_the_sentence
    func test_email_format_LayoutTests_test_sign_off_after_a_comma_closes_the_sentence() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John, hope you're well, kind regards, Ryan."), "Hi John,\n\nHope you're well.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatEmail("Let me know, thanks, Ryan.", senderName: "Ryan Murphy"), "Let me know.\n\nThanks,\nRyan")
    }

    // tests/test_email_format.py::LayoutTests::test_sign_off_forms
    func test_email_format_LayoutTests_test_sign_off_forms() {
        XCTAssertEqual(EmailFormat.formatEmail("Can you send the invoice? Thanks.", senderName: "Ryan Murphy"), "Can you send the invoice?\n\nThanks")
    }

    // tests/test_email_format.py::LayoutTests::test_sign_off_run_straight_on_from_the_body
    func test_email_format_LayoutTests_test_sign_off_run_straight_on_from_the_body() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John, thanks for getting back to me so soon and I just wanted to say thank you kind regards Ryan", senderName: "Ryan Murphy"), "Hi John,\n\nThanks for getting back to me so soon and I just wanted to say thank you.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatEmail("we'll sort it next week kind regards Ryan", senderName: "Ryan Murphy"), "We'll sort it next week.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatEmail("thanks for this yours sincerely Ryan Murphy", senderName: "Ryan Murphy"), "Thanks for this.\n\nYours sincerely,\nRyan Murphy")
    }

    // tests/test_email_format.py::LayoutTests::test_the_reported_shape
    func test_email_format_LayoutTests_test_the_reported_shape() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John, thanks for your email. I'll have a look at the quote and get back to you tomorrow. Kind regards, Ryan.", senderName: "Ryan Murphy"), "Hi John,\n\nThanks for your email. I'll have a look at the quote and get back to you tomorrow.\n\nKind regards,\nRyan")
    }

    // tests/test_email_format.py::LeftAloneTests::test_a_whole_reply_of_thanks_stays
    func test_email_format_LeftAloneTests_test_a_whole_reply_of_thanks_stays() {
        XCTAssertEqual(EmailFormat.formatEmail("Thanks.", senderName: "Ryan Murphy"), "Thanks.")
        XCTAssertEqual(EmailFormat.formatEmail("Thank you!", senderName: "Ryan Murphy"), "Thank you!")
    }

    // tests/test_email_format.py::LeftAloneTests::test_already_laid_out_is_stable
    func test_email_format_LeftAloneTests_test_already_laid_out_is_stable() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John, thanks. Kind regards, Ryan.", senderName: "Ryan Murphy"), "Hi John,\n\nThanks.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatEmail("Hi John,\n\nThanks.\n\nKind regards,\nRyan", senderName: "Ryan Murphy"), "Hi John,\n\nThanks.\n\nKind regards,\nRyan")
    }

    // tests/test_email_format.py::LeftAloneTests::test_best_needs_a_name
    func test_email_format_LeftAloneTests_test_best_needs_a_name() {
        XCTAssertEqual(EmailFormat.formatEmail("That's the best."), "That's the best.")
    }

    // tests/test_email_format.py::LeftAloneTests::test_empty
    func test_email_format_LeftAloneTests_test_empty() {
        XCTAssertEqual(EmailFormat.formatEmail(""), "")
        XCTAssertEqual(EmailFormat.formatEmail("   "), "   ")
    }

    // tests/test_email_format.py::LeftAloneTests::test_lower_case_names_are_not_guessed
    func test_email_format_LeftAloneTests_test_lower_case_names_are_not_guessed() {
        XCTAssertEqual(EmailFormat.formatEmail("hi john thanks for your email"), "hi john thanks for your email")
    }

    // tests/test_email_format.py::LeftAloneTests::test_no_greeting_and_no_sign_off
    func test_email_format_LeftAloneTests_test_no_greeting_and_no_sign_off() {
        XCTAssertEqual(EmailFormat.formatEmail("Can you send the updated quote over by Friday?", senderName: "Ryan Murphy"), "Can you send the updated quote over by Friday?")
    }

    // tests/test_email_format.py::LeftAloneTests::test_run_on_sign_off_that_is_part_of_the_sentence
    func test_email_format_LeftAloneTests_test_run_on_sign_off_that_is_part_of_the_sentence() {
        XCTAssertEqual(EmailFormat.formatEmail("please give him my kind regards", senderName: "Ryan Murphy"), "please give him my kind regards")
    }

    // tests/test_email_format.py::LeftAloneTests::test_thanking_the_recipient_by_name_is_not_a_signature
    func test_email_format_LeftAloneTests_test_thanking_the_recipient_by_name_is_not_a_signature() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John, can you send it over? Thanks John.", senderName: "Ryan Murphy"), "Hi John,\n\nCan you send it over? Thanks John.")
        XCTAssertEqual(EmailFormat.formatEmail("Hi John, can you send it over? Thanks John."), "Hi John,\n\nCan you send it over? Thanks John.")
        XCTAssertEqual(EmailFormat.formatEmail("Thanks John."), "Thanks John.")
    }

    // tests/test_email_format.py::LeftAloneTests::test_thanks_inside_the_last_sentence_is_not_a_sign_off
    func test_email_format_LeftAloneTests_test_thanks_inside_the_last_sentence_is_not_a_sign_off() {
        XCTAssertEqual(EmailFormat.formatEmail("Let me know, thanks.", senderName: "Ryan Murphy"), "Let me know, thanks.")
        XCTAssertEqual(EmailFormat.formatEmail("Thanks for your help today.", senderName: "Ryan Murphy"), "Thanks for your help today.")
    }

    // tests/test_email_format.py::AnyAppSignOffTests::test_everything_else_is_byte_identical
    func test_email_format_AnyAppSignOffTests_test_everything_else_is_byte_identical() {
        XCTAssertEqual(EmailFormat.formatSignoff("Hi John, thanks for your email.", senderName: "Ryan Murphy"), "Hi John, thanks for your email.")
    }

    // tests/test_email_format.py::AnyAppSignOffTests::test_regards_close_with_a_name_moves
    func test_email_format_AnyAppSignOffTests_test_regards_close_with_a_name_moves() {
        XCTAssertEqual(EmailFormat.formatSignoff("Hi John, thanks for getting back to me and I just wanted to say thank you kind regards Ryan", senderName: "Ryan Murphy"), "Hi John, thanks for getting back to me and I just wanted to say thank you.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatSignoff("Thanks. Best regards, Ryan.", senderName: "Ryan Murphy"), "Thanks.\n\nBest regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatSignoff("Kind regards Ryan", senderName: "Ryan Murphy"), "Kind regards,\nRyan")
    }

    // tests/test_email_format.py::AnyAppSignOffTests::test_stable
    func test_email_format_AnyAppSignOffTests_test_stable() {
        XCTAssertEqual(EmailFormat.formatSignoff("thanks for this kind regards Ryan", senderName: "Ryan Murphy"), "thanks for this.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatSignoff("thanks for this.\n\nKind regards,\nRyan", senderName: "Ryan Murphy"), "thanks for this.\n\nKind regards,\nRyan")
    }

    // tests/test_email_format.py::WordsKeptTests::test_same_words_in_the_same_order
    func test_email_format_WordsKeptTests_test_same_words_in_the_same_order() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi John, thanks for your email. I'll look. Kind regards, Ryan.", senderName: "Ryan Murphy"), "Hi John,\n\nThanks for your email. I'll look.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatSignoff("Hi John, thanks for your email. I'll look. Kind regards, Ryan.", senderName: "Ryan Murphy"), "Hi John, thanks for your email. I'll look.\n\nKind regards,\nRyan")
    }

    // tests/test_email_format.py::MisheardCloseTests::test_other_sound_alikes
    func test_email_format_MisheardCloseTests_test_other_sound_alikes() {
        XCTAssertEqual(EmailFormat.formatEmail("Thanks for this. Kind of regards, Ryan.", senderName: "Ryan Murphy"), "Thanks for this.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatEmail("Thanks for this. Kinder regards, Ryan.", senderName: "Ryan Murphy"), "Thanks for this.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatEmail("Thanks for this. Kind regard, Ryan.", senderName: "Ryan Murphy"), "Thanks for this.\n\nKind regards,\nRyan")
        XCTAssertEqual(EmailFormat.formatEmail("Thanks for this. Camera regards, Ryan.", senderName: "Ryan Murphy"), "Thanks for this.\n\nKind regards,\nRyan")
    }

    // tests/test_email_format.py::MisheardCloseTests::test_outside_email_with_a_name
    func test_email_format_MisheardCloseTests_test_outside_email_with_a_name() {
        XCTAssertEqual(EmailFormat.formatSignoff("Thanks for that. Camera guards Ryan.", senderName: "Ryan Murphy"), "Thanks for that.\n\nKind regards,\nRyan")
    }

    // tests/test_email_format.py::MisheardCloseTests::test_the_kit_itself_is_left_alone
    func test_email_format_MisheardCloseTests_test_the_kit_itself_is_left_alone() {
        XCTAssertEqual(EmailFormat.formatEmail("We need camera guards for the site.", senderName: "Ryan Murphy"), "We need camera guards for the site.")
        XCTAssertEqual(EmailFormat.formatSignoff("We need camera guards for the site.", senderName: "Ryan Murphy"), "We need camera guards for the site.")
        XCTAssertEqual(EmailFormat.formatEmail("Fit the camera guards, then call me.", senderName: "Ryan Murphy"), "Fit the camera guards, then call me.")
        XCTAssertEqual(EmailFormat.formatSignoff("Fit the camera guards, then call me.", senderName: "Ryan Murphy"), "Fit the camera guards, then call me.")
        XCTAssertEqual(EmailFormat.formatEmail("Camera guards are in stock.", senderName: "Ryan Murphy"), "Camera guards are in stock.")
        XCTAssertEqual(EmailFormat.formatSignoff("Camera guards are in stock.", senderName: "Ryan Murphy"), "Camera guards are in stock.")
        XCTAssertEqual(EmailFormat.formatEmail("Please order more. Camera guards.", senderName: "Ryan Murphy"), "Please order more. Camera guards.")
        XCTAssertEqual(EmailFormat.formatSignoff("Please order more. Camera guards.", senderName: "Ryan Murphy"), "Please order more. Camera guards.")
    }

    // tests/test_email_format.py::MisheardCloseTests::test_the_reported_email
    func test_email_format_MisheardCloseTests_test_the_reported_email() {
        XCTAssertEqual(EmailFormat.formatEmail("Hi Ryan, do you think it's best to meet in person or over Teams. Camera guards, Ryan.", senderName: "Ryan Murphy"), "Hi Ryan,\n\nDo you think it's best to meet in person or over Teams.\n\nKind regards,\nRyan")
    }

}
