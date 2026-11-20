import XCTest
@testable import EchoCore

/// Ported from the Python suite: every call below is a (input, output) pair taken from the Python tests
/// (outputs recorded from the Python implementation while its own tests passed).
final class SpokenCommandsTests: XCTestCase {
    // tests/test_tech_terms.py::ModelVersionTests::test_fixes
    func test_tech_terms_ModelVersionTests_test_fixes() {
        XCTAssertEqual(SpokenCommands.apply("claude opus five point five"), "Claude Opus 5.5")
        XCTAssertEqual(SpokenCommands.apply("Claude Sonnet four point five is fast"), "Claude Sonnet 4.5 is fast")
        XCTAssertEqual(SpokenCommands.apply("try haiku four point five"), "try Haiku 4.5")
        XCTAssertEqual(SpokenCommands.apply("Fable 5 point 1"), "Fable 5.1")
        XCTAssertEqual(SpokenCommands.apply("claude three point seven"), "Claude 3.7")
        XCTAssertEqual(SpokenCommands.apply("gpt five"), "GPT-5")
        XCTAssertEqual(SpokenCommands.apply("GPT 4.1 mini"), "GPT-4.1 mini")
        XCTAssertEqual(SpokenCommands.apply("gpt four o"), "GPT-4o")
        XCTAssertEqual(SpokenCommands.apply("gemini two point five pro"), "Gemini 2.5 Pro")
        XCTAssertEqual(SpokenCommands.apply("gemini 2.5 flash"), "Gemini 2.5 Flash")
        XCTAssertEqual(SpokenCommands.apply("llama three point one"), "Llama 3.1")
        XCTAssertEqual(SpokenCommands.apply("deep seek v three"), "DeepSeek V3")
        XCTAssertEqual(SpokenCommands.apply("grok four"), "Grok 4")
        XCTAssertEqual(SpokenCommands.apply("chat gpt is down"), "ChatGPT is down")
        XCTAssertEqual(SpokenCommands.apply("open ai and anthropic"), "OpenAI and Anthropic")
        XCTAssertEqual(SpokenCommands.apply("check lm arena for the rankings"), "check LMArena for the rankings")
        XCTAssertEqual(SpokenCommands.apply("Opus 5.5"), "Opus 5.5")
    }

    // tests/test_tech_terms.py::ModelVersionTests::test_prose_left_alone
    func test_tech_terms_ModelVersionTests_test_prose_left_alone() {
        XCTAssertEqual(SpokenCommands.apply("at one point five people left"), "at one point five people left")
        XCTAssertEqual(SpokenCommands.apply("she wrote a haiku about spring"), "she wrote a haiku about spring")
        XCTAssertEqual(SpokenCommands.apply("the llama farm is open"), "the llama farm is open")
        XCTAssertEqual(SpokenCommands.apply("his magnum opus. Two days later he left"), "his magnum opus. Two days later he left")
        XCTAssertEqual(SpokenCommands.apply("I gave Claude four tasks"), "I gave Claude four tasks")
        XCTAssertEqual(SpokenCommands.apply("a sonnet and a haiku"), "a sonnet and a haiku")
        XCTAssertEqual(SpokenCommands.apply("I used Opus 5. 5 people agreed"), "I used Opus 5. 5 people agreed")
        XCTAssertEqual(SpokenCommands.apply("GPT or Gemini, either is fine"), "GPT or Gemini, either is fine")
    }

    // tests/test_tech_terms.py::ModelVersionTests::test_reported_case
    func test_tech_terms_ModelVersionTests_test_reported_case() {
        XCTAssertEqual(SpokenCommands.apply("I used opus five point five today"), "I used Opus 5.5 today")
    }

    // tests/test_spoken_symbols.py::AddressTests::test_bare_domain
    func test_spoken_symbols_AddressTests_test_bare_domain() {
        XCTAssertEqual(SpokenCommands.apply("go to ftc dash ss dot com"), "go to ftc-ss.com")
    }

    // tests/test_spoken_symbols.py::AddressTests::test_email_inside_a_sentence
    func test_spoken_symbols_AddressTests_test_email_inside_a_sentence() {
        XCTAssertEqual(SpokenCommands.apply("Send it to ryan dot murphy at ftc dash ss dot com today"), "Send it to ryan.murphy@ftc-ss.com today")
    }

    // tests/test_spoken_symbols.py::AddressTests::test_filename
    func test_spoken_symbols_AddressTests_test_filename() {
        XCTAssertEqual(SpokenCommands.apply("open the report dot pdf"), "open the report.pdf")
    }

    // tests/test_spoken_symbols.py::AddressTests::test_multi_label_domain
    func test_spoken_symbols_AddressTests_test_multi_label_domain() {
        XCTAssertEqual(SpokenCommands.apply("see example dot co dot uk"), "see example.co.uk")
    }

    // tests/test_spoken_symbols.py::AddressTests::test_prose_at_before_the_address
    func test_spoken_symbols_AddressTests_test_prose_at_before_the_address() {
        XCTAssertEqual(SpokenCommands.apply("email me at ryan dot murphy at example dot com"), "email me at ryan.murphy@example.com")
    }

    // tests/test_spoken_symbols.py::AddressTests::test_the_reported_email
    func test_spoken_symbols_AddressTests_test_the_reported_email() {
        XCTAssertEqual(SpokenCommands.apply("Ryan dot murphy at ftc dash ss dot com"), "ryan.murphy@ftc-ss.com")
    }

    // tests/test_spoken_symbols.py::AddressTests::test_trailing_sentence_stop_is_kept
    func test_spoken_symbols_AddressTests_test_trailing_sentence_stop_is_kept() {
        XCTAssertEqual(SpokenCommands.apply("Mail ryan at example dot com."), "Mail ryan@example.com.")
    }

    // tests/test_spoken_symbols.py::AddressTests::test_underscore_local_part
    func test_spoken_symbols_AddressTests_test_underscore_local_part() {
        XCTAssertEqual(SpokenCommands.apply("ryan underscore murphy at example dot org"), "ryan_murphy@example.org")
    }

    // tests/test_spoken_symbols.py::AddressFalsePositiveTests::test_dash_alone_is_untouched
    func test_spoken_symbols_AddressFalsePositiveTests_test_dash_alone_is_untouched() {
        XCTAssertEqual(SpokenCommands.apply("a dash of colour"), "a dash of colour")
    }

    // tests/test_spoken_symbols.py::AddressFalsePositiveTests::test_dot_without_a_tld
    func test_spoken_symbols_AddressFalsePositiveTests_test_dot_without_a_tld() {
        XCTAssertEqual(SpokenCommands.apply("version one dot two"), "version one dot two")
    }

    // tests/test_spoken_symbols.py::AddressFalsePositiveTests::test_plain_at
    func test_spoken_symbols_AddressFalsePositiveTests_test_plain_at() {
        XCTAssertEqual(SpokenCommands.apply("I looked at the numbers"), "I looked at the numbers")
        XCTAssertEqual(SpokenCommands.apply("meet me at the office"), "meet me at the office")
        XCTAssertEqual(SpokenCommands.apply("have a look at this"), "have a look at this")
        XCTAssertEqual(SpokenCommands.apply("back at it again"), "back at it again")
    }

    // tests/test_spoken_symbols.py::AddressFalsePositiveTests::test_single_letter_label_is_not_a_domain
    func test_spoken_symbols_AddressFalsePositiveTests_test_single_letter_label_is_not_a_domain() {
        XCTAssertEqual(SpokenCommands.apply("put a dot in the box"), "put a dot in the box")
        XCTAssertEqual(SpokenCommands.apply("we looked at it"), "we looked at it")
        XCTAssertEqual(SpokenCommands.apply("leave it to me"), "leave it to me")
    }

    // tests/test_spoken_symbols.py::AddressFalsePositiveTests::test_verb_before_at_is_not_an_email
    func test_spoken_symbols_AddressFalsePositiveTests_test_verb_before_at_is_not_an_email() {
        XCTAssertEqual(SpokenCommands.apply("I looked at report dot pdf"), "I looked at report.pdf")
    }

    // tests/test_spoken_symbols.py::PercentTests::test_bare_scale_word_is_prose
    func test_spoken_symbols_PercentTests_test_bare_scale_word_is_prose() {
        XCTAssertEqual(SpokenCommands.apply("a hundred percent sure"), "a hundred percent sure")
    }

    // tests/test_spoken_symbols.py::PercentTests::test_currency_words
    func test_spoken_symbols_PercentTests_test_currency_words() {
        XCTAssertEqual(SpokenCommands.apply("dollar sign fifty"), "$50")
    }

    // tests/test_spoken_symbols.py::PercentTests::test_digits_already
    func test_spoken_symbols_PercentTests_test_digits_already() {
        XCTAssertEqual(SpokenCommands.apply("up 54 percent this year"), "up 54% this year")
    }

    // tests/test_spoken_symbols.py::PercentTests::test_hundred
    func test_spoken_symbols_PercentTests_test_hundred() {
        XCTAssertEqual(SpokenCommands.apply("one hundred percent sure"), "100% sure")
    }

    // tests/test_spoken_symbols.py::PercentTests::test_hyphenated_number
    func test_spoken_symbols_PercentTests_test_hyphenated_number() {
        XCTAssertEqual(SpokenCommands.apply("fifty-four percent"), "54%")
    }

    // tests/test_spoken_symbols.py::PercentTests::test_percentage_is_not_a_symbol
    func test_spoken_symbols_PercentTests_test_percentage_is_not_a_symbol() {
        XCTAssertEqual(SpokenCommands.apply("the percentage of users"), "the percentage of users")
    }

    // tests/test_spoken_symbols.py::PercentTests::test_the_reported_example
    func test_spoken_symbols_PercentTests_test_the_reported_example() {
        XCTAssertEqual(SpokenCommands.apply("a rise of fifty four percent"), "a rise of 54%")
    }

    // tests/test_spoken_symbols.py::TimesTests::test_decimal_multiplier_at_sentence_end
    func test_spoken_symbols_TimesTests_test_decimal_multiplier_at_sentence_end() {
        XCTAssertEqual(SpokenCommands.apply("Set it to 1.5 times."), "Set it to 1.5x.")
    }

    // tests/test_spoken_symbols.py::TimesTests::test_number_times_number
    func test_spoken_symbols_TimesTests_test_number_times_number() {
        XCTAssertEqual(SpokenCommands.apply("so 1.2 times 50 is 60"), "so 1.2 x 50 is 60")
        XCTAssertEqual(SpokenCommands.apply("3 times 4"), "3 x 4")
    }

    // tests/test_spoken_symbols.py::TimesTests::test_ordinary_times_stays_prose
    func test_spoken_symbols_TimesTests_test_ordinary_times_stays_prose() {
        XCTAssertEqual(SpokenCommands.apply("a couple times I've said it"), "a couple times I've said it")
        XCTAssertEqual(SpokenCommands.apply("I called 3 times a day"), "I called 3 times a day")
        XCTAssertEqual(SpokenCommands.apply("three times faster"), "three times faster")
        XCTAssertEqual(SpokenCommands.apply("times it by 2"), "times it by 2")
        XCTAssertEqual(SpokenCommands.apply("most of the time"), "most of the time")
        XCTAssertEqual(SpokenCommands.apply("times are hard"), "times are hard")
        XCTAssertEqual(SpokenCommands.apply("at times by the river"), "at times by the river")
        XCTAssertEqual(SpokenCommands.apply("I went 3 times last week"), "I went 3 times last week")
        XCTAssertEqual(SpokenCommands.apply("version 1.2 is out"), "version 1.2 is out")
    }

    // tests/test_spoken_symbols.py::TimesTests::test_the_reported_dictation
    func test_spoken_symbols_TimesTests_test_the_reported_dictation() {
        XCTAssertEqual(SpokenCommands.apply("You know, like 1.2 times speed and stuff"), "You know, like 1.2x speed and stuff")
    }

    // tests/test_spoken_symbols.py::TimesTests::test_times_by
    func test_spoken_symbols_TimesTests_test_times_by() {
        XCTAssertEqual(SpokenCommands.apply("then times by 1.2"), "then x 1.2")
    }

    // tests/test_spoken_symbols.py::TimesTests::test_whole_number_with_comparison
    func test_spoken_symbols_TimesTests_test_whole_number_with_comparison() {
        XCTAssertEqual(SpokenCommands.apply("it's 3 times faster"), "it's 3x faster")
        XCTAssertEqual(SpokenCommands.apply("10 times more leads"), "10x more leads")
    }

    // tests/test_spoken_symbols.py::QuoteTests::test_apostrophe
    func test_spoken_symbols_QuoteTests_test_apostrophe() {
        XCTAssertEqual(SpokenCommands.apply("Ryan apostrophe s report"), "Ryan's report")
    }

    // tests/test_spoken_symbols.py::QuoteTests::test_bare_quotation_marks_stay_prose
    func test_spoken_symbols_QuoteTests_test_bare_quotation_marks_stay_prose() {
        XCTAssertEqual(SpokenCommands.apply("things like quotation marks, dollar signs and the rest"), "things like quotation marks, dollar signs and the rest")
    }

    // tests/test_spoken_symbols.py::QuoteTests::test_exclamation
    func test_spoken_symbols_QuoteTests_test_exclamation() {
        XCTAssertEqual(SpokenCommands.apply("well done exclamation mark"), "well done!")
    }

    // tests/test_spoken_symbols.py::QuoteTests::test_open_and_close
    func test_spoken_symbols_QuoteTests_test_open_and_close() {
        XCTAssertEqual(SpokenCommands.apply("open quote hello close quote"), "\"hello\"")
    }

    // tests/test_spoken_symbols.py::QuoteTests::test_unquote
    func test_spoken_symbols_QuoteTests_test_unquote() {
        XCTAssertEqual(SpokenCommands.apply("open quote hello unquote"), "\"hello\"")
    }

    // tests/test_spoken_symbols.py::ExistingBehaviourTests::test_brackets
    func test_spoken_symbols_ExistingBehaviourTests_test_brackets() {
        XCTAssertEqual(SpokenCommands.apply("open bracket see attached close bracket"), "(see attached)")
    }

    // tests/test_spoken_symbols.py::ExistingBehaviourTests::test_hashtag
    func test_spoken_symbols_ExistingBehaviourTests_test_hashtag() {
        XCTAssertEqual(SpokenCommands.apply("hashtag safety first"), "#safety first")
    }

    // tests/test_spoken_symbols.py::ExistingBehaviourTests::test_newlines_survive
    func test_spoken_symbols_ExistingBehaviourTests_test_newlines_survive() {
        XCTAssertEqual(SpokenCommands.apply("line one\n\nline two slash three"), "line one\n\nline two/three")
    }

    // tests/test_spoken_symbols.py::ExistingBehaviourTests::test_punctuation_words_are_never_converted
    func test_spoken_symbols_ExistingBehaviourTests_test_punctuation_words_are_never_converted() {
        XCTAssertEqual(SpokenCommands.apply("over a period of time"), "over a period of time")
        XCTAssertEqual(SpokenCommands.apply("a question mark over the plan"), "a question mark over the plan")
        XCTAssertEqual(SpokenCommands.apply("a new line of products"), "a new line of products")
        XCTAssertEqual(SpokenCommands.apply("look at sign four"), "look at sign four")
    }

    // tests/test_spoken_symbols.py::ExistingBehaviourTests::test_slash
    func test_spoken_symbols_ExistingBehaviourTests_test_slash() {
        XCTAssertEqual(SpokenCommands.apply("slash settings"), "/settings")
    }

    // tests/test_spoken_symbols.py::ExistingBehaviourTests::test_underscore
    func test_spoken_symbols_ExistingBehaviourTests_test_underscore() {
        XCTAssertEqual(SpokenCommands.apply("ryan underscore murphy"), "ryan_murphy")
    }

}
