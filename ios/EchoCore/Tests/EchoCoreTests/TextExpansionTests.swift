import XCTest
@testable import EchoCore

/// Ported from the Python suite: every call below is a (input, output) pair taken from the Python tests
/// (outputs recorded from the Python implementation while its own tests passed).
final class TextExpansionTests: XCTestCase {
    // tests/test_text_expansion.py::VocabularyTests::test_a_replacement_is_never_re_matched
    func test_text_expansion_VocabularyTests_test_a_replacement_is_never_re_matched() {
        XCTAssertEqual(TextExpansion.applyVocabulary("Say alpha now.", entries: [VocabularyEntry(term: "beta", soundsLike: ["alpha"]), VocabularyEntry(term: "gamma", soundsLike: ["beta"])]), "Say beta now.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_a_variant_equal_to_the_term_is_a_no_op
    func test_text_expansion_VocabularyTests_test_a_variant_equal_to_the_term_is_a_no_op() {
        XCTAssertEqual(TextExpansion.applyVocabulary("Open Pipedrive.", entries: [VocabularyEntry(term: "Pipedrive", soundsLike: ["Pipedrive"])]), "Open Pipedrive.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_deliberate_casing_survives_a_sentence_start
    func test_text_expansion_VocabularyTests_test_deliberate_casing_survives_a_sentence_start() {
        XCTAssertEqual(TextExpansion.applyVocabulary("I phone is charged.", entries: [VocabularyEntry(term: "iPhone", soundsLike: ["i phone"]), VocabularyEntry(term: "FTC", soundsLike: ["f t c"])]), "iPhone is charged.")
        XCTAssertEqual(TextExpansion.applyVocabulary("F t c won the tender.", entries: [VocabularyEntry(term: "iPhone", soundsLike: ["i phone"]), VocabularyEntry(term: "FTC", soundsLike: ["f t c"])]), "FTC won the tender.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_empty_and_malformed_input_is_safe
    func test_text_expansion_VocabularyTests_test_empty_and_malformed_input_is_safe() {
        XCTAssertEqual(TextExpansion.applyVocabulary("", entries: [VocabularyEntry(term: "A", soundsLike: ["aaa"])]), "")
        XCTAssertEqual(TextExpansion.applyVocabulary("hi", entries: []), "hi")
        XCTAssertEqual(TextExpansion.applyVocabulary("hi", entries: [VocabularyEntry(term: "")]), "hi")
        XCTAssertEqual(TextExpansion.applyVocabulary("hi", entries: [VocabularyEntry(term: "", soundsLike: ["aaa"])]), "hi")
        XCTAssertEqual(TextExpansion.applyVocabulary("hi", entries: [VocabularyEntry(term: "X")]), "hi")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_longest_variant_wins
    func test_text_expansion_VocabularyTests_test_longest_variant_wins() {
        XCTAssertEqual(TextExpansion.applyVocabulary("Invoice ftc safety solutions limited please.", entries: [VocabularyEntry(term: "FTC Safety Solutions", soundsLike: ["ftc safety solutions limited"]), VocabularyEntry(term: "FTC", soundsLike: ["ftc safety"])]), "Invoice FTC Safety Solutions please.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_lower_case_term_is_capitalised_only_at_a_sentence_start
    func test_text_expansion_VocabularyTests_test_lower_case_term_is_capitalised_only_at_a_sentence_start() {
        XCTAssertEqual(TextExpansion.applyVocabulary("For example the roof survey.", entries: [VocabularyEntry(term: "e.g.", soundsLike: ["for example"])]), "E.g. the roof survey.")
        XCTAssertEqual(TextExpansion.applyVocabulary("Take for example the roof survey.", entries: [VocabularyEntry(term: "e.g.", soundsLike: ["for example"])]), "Take e.g. the roof survey.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_match_is_case_insensitive_but_the_term_keeps_its_casing
    func test_text_expansion_VocabularyTests_test_match_is_case_insensitive_but_the_term_keeps_its_casing() {
        XCTAssertEqual(TextExpansion.applyVocabulary("Open pipe drive now.", entries: [VocabularyEntry(term: "Pipedrive", soundsLike: ["pipe drive"])]), "Open Pipedrive now.")
        XCTAssertEqual(TextExpansion.applyVocabulary("Open Pipe Drive now.", entries: [VocabularyEntry(term: "Pipedrive", soundsLike: ["pipe drive"])]), "Open Pipedrive now.")
        XCTAssertEqual(TextExpansion.applyVocabulary("Open PIPE DRIVE now.", entries: [VocabularyEntry(term: "Pipedrive", soundsLike: ["pipe drive"])]), "Open Pipedrive now.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_matches_across_irregular_whitespace
    func test_text_expansion_VocabularyTests_test_matches_across_irregular_whitespace() {
        XCTAssertEqual(TextExpansion.applyVocabulary("Use pipe   drive.", entries: [VocabularyEntry(term: "Pipedrive", soundsLike: ["pipe drive"])]), "Use Pipedrive.")
        XCTAssertEqual(TextExpansion.applyVocabulary("Use pipe\ndrive.", entries: [VocabularyEntry(term: "Pipedrive", soundsLike: ["pipe drive"])]), "Use Pipedrive.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_never_matches_inside_a_word
    func test_text_expansion_VocabularyTests_test_never_matches_inside_a_word() {
        XCTAssertEqual(TextExpansion.applyVocabulary("He scrapes the data.", entries: [VocabularyEntry(term: "CRM", soundsLike: ["cra"])]), "He scrapes the data.")
        XCTAssertEqual(TextExpansion.applyVocabulary("A crate of parts.", entries: [VocabularyEntry(term: "CRM", soundsLike: ["cra"])]), "A crate of parts.")
        XCTAssertEqual(TextExpansion.applyVocabulary("cracker", entries: [VocabularyEntry(term: "CRM", soundsLike: ["cra"])]), "cracker")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_regex_metacharacters_in_a_variant_are_literal
    func test_text_expansion_VocabularyTests_test_regex_metacharacters_in_a_variant_are_literal() {
        XCTAssertEqual(TextExpansion.applyVocabulary("I write c plus plus.", entries: [VocabularyEntry(term: "C++", soundsLike: ["c plus plus"]), VocabularyEntry(term: "query", soundsLike: ["que.ry"])]), "I write C++.")
        XCTAssertEqual(TextExpansion.applyVocabulary("Run queXry now.", entries: [VocabularyEntry(term: "C++", soundsLike: ["c plus plus"]), VocabularyEntry(term: "query", soundsLike: ["que.ry"])]), "Run queXry now.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_replaces_a_known_mishearing
    func test_text_expansion_VocabularyTests_test_replaces_a_known_mishearing() {
        XCTAssertEqual(TextExpansion.applyVocabulary("We logged it in pipe drive today.", entries: [VocabularyEntry(term: "Pipedrive", soundsLike: ["pipe drive"])]), "We logged it in Pipedrive today.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_soft_deleted_entries_do_nothing
    func test_text_expansion_VocabularyTests_test_soft_deleted_entries_do_nothing() {
        XCTAssertEqual(TextExpansion.applyVocabulary("Open pipe drive.", entries: [VocabularyEntry(term: "Pipedrive", soundsLike: ["pipe drive"], deleted: true)]), "Open pipe drive.")
    }

    // tests/test_text_expansion.py::VocabularyTests::test_variants_below_the_floor_are_ignored
    func test_text_expansion_VocabularyTests_test_variants_below_the_floor_are_ignored() {
        XCTAssertEqual(TextExpansion.applyVocabulary("Give us a call.", entries: [VocabularyEntry(term: "United States", soundsLike: ["us"])]), "Give us a call.")
    }

    // tests/test_text_expansion.py::HotwordTests::test_deduplicates_and_skips_deleted
    func test_text_expansion_HotwordTests_test_deduplicates_and_skips_deleted() {
        XCTAssertEqual(TextExpansion.hotwords([VocabularyEntry(term: "FTC"), VocabularyEntry(term: "ftc"), VocabularyEntry(term: "Gone", deleted: true)]).joined(separator: ", "), "FTC")
    }

    // tests/test_text_expansion.py::HotwordTests::test_empty
    func test_text_expansion_HotwordTests_test_empty() {
        XCTAssertEqual(TextExpansion.hotwords([]).joined(separator: ", "), "")
        XCTAssertEqual(TextExpansion.hotwords([]).joined(separator: ", "), "")
    }

    // tests/test_text_expansion.py::HotwordTests::test_terms_only_never_the_mishearings
    func test_text_expansion_HotwordTests_test_terms_only_never_the_mishearings() {
        XCTAssertEqual(TextExpansion.hotwords([VocabularyEntry(term: "Pipedrive", soundsLike: ["pipe drive"]), VocabularyEntry(term: "FTC", soundsLike: ["f t c"])]).joined(separator: ", "), "Pipedrive, FTC")
    }

    // tests/test_text_expansion.py::SnippetTests::test_a_body_is_inserted_verbatim_never_recased
    func test_text_expansion_SnippetTests_test_a_body_is_inserted_verbatim_never_recased() {
        XCTAssertEqual(TextExpansion.applySnippets("My email is the address.", snippets: [Snippet(name: "", trigger: "my email", body: "ryan@ftc.co.uk")]), "ryan@ftc.co.uk is the address.")
    }

    // tests/test_text_expansion.py::SnippetTests::test_body_is_not_rescanned
    func test_text_expansion_SnippetTests_test_body_is_not_rescanned() {
        XCTAssertEqual(TextExpansion.applySnippets("Say intro now.", snippets: [Snippet(name: "", trigger: "intro", body: "my email is here"), Snippet(name: "", trigger: "my email", body: "ryan@ftc.co.uk")]), "Say my email is here now.")
    }

    // tests/test_text_expansion.py::SnippetTests::test_expands_a_trigger
    func test_text_expansion_SnippetTests_test_expands_a_trigger() {
        XCTAssertEqual(TextExpansion.applySnippets("It's my email really.", snippets: [Snippet(name: "", trigger: "my email", body: "ryan@ftc.co.uk")]), "It's ryan@ftc.co.uk really.")
    }

    // tests/test_text_expansion.py::SnippetTests::test_longest_trigger_wins
    func test_text_expansion_SnippetTests_test_longest_trigger_wins() {
        XCTAssertEqual(TextExpansion.applySnippets("Send to my work email.", snippets: [Snippet(name: "", trigger: "my email", body: "personal@x.com"), Snippet(name: "", trigger: "my work email", body: "work@ftc.co.uk")]), "Send to work@ftc.co.uk.")
    }

    // tests/test_text_expansion.py::SnippetTests::test_multi_line_body
    func test_text_expansion_SnippetTests_test_multi_line_body() {
        XCTAssertEqual(TextExpansion.applySnippets("Sign off", snippets: [Snippet(name: "", trigger: "sign off", body: "Kind regards,\nRyan Murphy\nFTC Safety")]), "Kind regards,\nRyan Murphy\nFTC Safety")
    }

    // tests/test_text_expansion.py::SnippetTests::test_never_fires_inside_a_word
    func test_text_expansion_SnippetTests_test_never_fires_inside_a_word() {
        XCTAssertEqual(TextExpansion.applySnippets("The catalogue arrived.", snippets: [Snippet(name: "", trigger: "cat", body: "Concrete Assessment Test")]), "The catalogue arrived.")
        XCTAssertEqual(TextExpansion.applySnippets("concatenate", snippets: [Snippet(name: "", trigger: "cat", body: "Concrete Assessment Test")]), "concatenate")
    }

    // tests/test_text_expansion.py::SnippetTests::test_short_trigger_or_empty_body_is_ignored
    func test_text_expansion_SnippetTests_test_short_trigger_or_empty_body_is_ignored() {
        XCTAssertEqual(TextExpansion.applySnippets("go to it", snippets: [Snippet(name: "", trigger: "to", body: "X")]), "go to it")
        XCTAssertEqual(TextExpansion.applySnippets("my email", snippets: [Snippet(name: "", trigger: "my email", body: "")]), "my email")
    }

    // tests/test_text_expansion.py::SnippetTests::test_soft_deleted_and_malformed_are_safe
    func test_text_expansion_SnippetTests_test_soft_deleted_and_malformed_are_safe() {
        XCTAssertEqual(TextExpansion.applySnippets("my email", snippets: [Snippet(name: "", trigger: "my email", body: "x", deleted: true)]), "my email")
        XCTAssertEqual(TextExpansion.applySnippets("hi", snippets: [Snippet(name: "", trigger: "", body: "")]), "hi")
        XCTAssertEqual(TextExpansion.applySnippets("", snippets: [Snippet(name: "", trigger: "my email", body: "x")]), "")
    }

    // tests/test_text_expansion.py::ValidationTests::test_every_reason_is_user_facing_text
    func test_text_expansion_ValidationTests_test_every_reason_is_user_facing_text() {
        XCTAssertEqual(TextExpansion.validateSoundsLike("a"), "Too short \u{2014} needs 3 characters or more, or it will match ordinary speech.")
        XCTAssertEqual(TextExpansion.validateTrigger(""), "Enter a trigger phrase.")
        XCTAssertEqual(TextExpansion.validateTrigger("the"), "\u{201C}the\u{201D} is too common \u{2014} it would expand every time you said it. Try a longer phrase.")
    }

    // tests/test_text_expansion.py::ValidationTests::test_sounds_like_cannot_equal_the_term
    func test_text_expansion_ValidationTests_test_sounds_like_cannot_equal_the_term() {
        XCTAssertEqual(TextExpansion.validateSoundsLike("Pipedrive", term: "pipedrive"), "That's the same as the word itself.")
    }

    // tests/test_text_expansion.py::ValidationTests::test_sounds_like_floor
    func test_text_expansion_ValidationTests_test_sounds_like_floor() {
        XCTAssertEqual(TextExpansion.validateSoundsLike("us"), "Too short \u{2014} needs 3 characters or more, or it will match ordinary speech.")
        XCTAssertEqual(TextExpansion.validateSoundsLike("pipe drive"), nil)
    }

    // tests/test_text_expansion.py::ValidationTests::test_sounds_like_rejects_blank
    func test_text_expansion_ValidationTests_test_sounds_like_rejects_blank() {
        XCTAssertEqual(TextExpansion.validateSoundsLike(""), "Enter what it sounds like.")
        XCTAssertEqual(TextExpansion.validateSoundsLike("   "), "Enter what it sounds like.")
        XCTAssertEqual(TextExpansion.validateSoundsLike(""), "Enter what it sounds like.")
    }

    // tests/test_text_expansion.py::ValidationTests::test_trigger_accepts_a_real_phrase
    func test_text_expansion_ValidationTests_test_trigger_accepts_a_real_phrase() {
        XCTAssertEqual(TextExpansion.validateTrigger("my email"), nil)
        XCTAssertEqual(TextExpansion.validateTrigger("standard sign off"), nil)
    }

    // tests/test_text_expansion.py::ValidationTests::test_trigger_rejects_common_words
    func test_text_expansion_ValidationTests_test_trigger_rejects_common_words() {
        XCTAssertEqual(TextExpansion.validateTrigger("the"), "\u{201C}the\u{201D} is too common \u{2014} it would expand every time you said it. Try a longer phrase.")
        XCTAssertEqual(TextExpansion.validateTrigger("and"), "\u{201C}and\u{201D} is too common \u{2014} it would expand every time you said it. Try a longer phrase.")
        XCTAssertEqual(TextExpansion.validateTrigger("thanks"), "\u{201C}thanks\u{201D} is too common \u{2014} it would expand every time you said it. Try a longer phrase.")
        XCTAssertEqual(TextExpansion.validateTrigger("Okay"), "\u{201C}Okay\u{201D} is too common \u{2014} it would expand every time you said it. Try a longer phrase.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_a_term_may_not_swap_one_function_word_for_another
    func test_text_expansion_FuzzyVocabularyTests_test_a_term_may_not_swap_one_function_word_for_another() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Push the usage card fixes too.", entries: [VocabularyEntry(term: "Push it")]), "Push the usage card fixes too.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Push the other ready branches as well.", entries: [VocabularyEntry(term: "Push it")]), "Push the other ready branches as well.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("push the button", entries: [VocabularyEntry(term: "Push it")]), "push the button")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("bank of irland", entries: [VocabularyEntry(term: "Bank of Ireland")]), "Bank of Ireland")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("hed of sails", entries: [VocabularyEntry(term: "Head of Sales")]), "Head of Sales")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_a_term_never_adds_a_word_nobody_said
    func test_text_expansion_FuzzyVocabularyTests_test_a_term_never_adds_a_word_nobody_said() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Make sure everything's pushed as a new install.", entries: [VocabularyEntry(term: "Push it")]), "Make sure everything's pushed as a new install.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("I pushed it to main yesterday.", entries: [VocabularyEntry(term: "Push it")]), "I pushed it to main yesterday.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Pushed.", entries: [VocabularyEntry(term: "Push it")]), "Pushed.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_a_term_with_a_function_word_still_fixes_a_span_that_has_one
    func test_text_expansion_FuzzyVocabularyTests_test_a_term_with_a_function_word_still_fixes_a_span_that_has_one() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Pay bank of irland now.", entries: [VocabularyEntry(term: "Bank of Ireland")]), "Pay Bank of Ireland now.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Ask the hed of sails.", entries: [VocabularyEntry(term: "Head of Sales")]), "Ask the Head of Sales.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_catches_a_split_multiword_mishearing
    func test_text_expansion_FuzzyVocabularyTests_test_catches_a_split_multiword_mishearing() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Log it in pipe drife.", entries: [VocabularyEntry(term: "Pipedrive")]), "Log it in Pipedrive.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_catches_close_mishearings_of_a_term
    func test_text_expansion_FuzzyVocabularyTests_test_catches_close_mishearings_of_a_term() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Deploy to vercell now.", entries: [VocabularyEntry(term: "Vercel")]), "Deploy to Vercel now.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Deploy to ver cell now.", entries: [VocabularyEntry(term: "Vercel")]), "Deploy to Vercel now.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Deploy to versel now.", entries: [VocabularyEntry(term: "Vercel")]), "Deploy to Vercel now.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Deploy to versaille now.", entries: [VocabularyEntry(term: "Vercel")]), "Deploy to Vercel now.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Deploy to Vercell now.", entries: [VocabularyEntry(term: "Vercel")]), "Deploy to Vercel now.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_corrected_term_keeps_its_casing
    func test_text_expansion_FuzzyVocabularyTests_test_corrected_term_keeps_its_casing() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Use vercell.", entries: [VocabularyEntry(term: "Vercel")]), "Use Vercel.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_leaves_ordinary_english_alone
    func test_text_expansion_FuzzyVocabularyTests_test_leaves_ordinary_english_alone() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Click the cell to edit it.", entries: [VocabularyEntry(term: "Vercel")]), "Click the cell to edit it.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Open it in excel please.", entries: [VocabularyEntry(term: "Vercel")]), "Open it in excel please.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Ring the bell when ready.", entries: [VocabularyEntry(term: "Vercel")]), "Ring the bell when ready.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("That is the sell side desk.", entries: [VocabularyEntry(term: "Vercel")]), "That is the sell side desk.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("My cell rang twice.", entries: [VocabularyEntry(term: "Vercel")]), "My cell rang twice.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("We should sell the shares.", entries: [VocabularyEntry(term: "Vercel")]), "We should sell the shares.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("A crate of parts arrived.", entries: [VocabularyEntry(term: "Vercel")]), "A crate of parts arrived.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_lowercase_term_capitalised_only_at_sentence_start
    func test_text_expansion_FuzzyVocabularyTests_test_lowercase_term_capitalised_only_at_sentence_start() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Kubecuttle applies it.", entries: [VocabularyEntry(term: "kubectl")]), "Kubectl applies it.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_no_cascade_single_pass
    func test_text_expansion_FuzzyVocabularyTests_test_no_cascade_single_pass() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Ship on vercell.", entries: [VocabularyEntry(term: "Vercel"), VocabularyEntry(term: "Marcel")]), "Ship on Vercel.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_no_metaphone_is_a_clean_noop
    // is not ported: it patches the Python `metaphone` import out, and EchoCore
    // always carries its own encoder (the same input is pinned to "Deploy to
    // Vercel now." in test_fuzzy_extra_cases_from_python).

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_short_terms_do_not_fuzzy_match
    func test_text_expansion_FuzzyVocabularyTests_test_short_terms_do_not_fuzzy_match() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("It was a test.", entries: [VocabularyEntry(term: "AWS")]), "It was a test.")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_soft_deleted_and_empty_are_safe
    func test_text_expansion_FuzzyVocabularyTests_test_soft_deleted_and_empty_are_safe() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("say vercell", entries: [VocabularyEntry(term: "Vercel", deleted: true)]), "say vercell")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("", entries: [VocabularyEntry(term: "Vercel")]), "")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("hi", entries: []), "hi")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("hi", entries: [VocabularyEntry(term: "")]), "hi")
    }

    // tests/test_text_expansion.py::FuzzyVocabularyTests::test_unrelated_words_are_never_pulled_in
    func test_text_expansion_FuzzyVocabularyTests_test_unrelated_words_are_never_pulled_in() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("The parcel is at the front desk.", entries: [VocabularyEntry(term: "Vercel")]), "The parcel is at the front desk.")
    }

    // tests/test_text_expansion.py::PipelineOrderTests::test_vocabulary_correction_can_complete_a_snippet_trigger
    func test_text_expansion_PipelineOrderTests_test_vocabulary_correction_can_complete_a_snippet_trigger() {
        XCTAssertEqual(TextExpansion.applyVocabulary("Send the pipe drive link.", entries: [VocabularyEntry(term: "Pipedrive", soundsLike: ["pipe drive"])]), "Send the Pipedrive link.")
        XCTAssertEqual(TextExpansion.applySnippets("Send the Pipedrive link.", snippets: [Snippet(name: "", trigger: "Pipedrive link", body: "https://ftc.pipedrive.com")]), "Send the https://ftc.pipedrive.com.")
    }

    // tests/test_managed_vocab.py::ManagedVariantsTests::test_a_suffix_never_becomes_a_term_on_its_own
    func test_managed_vocab_ManagedVariantsTests_test_a_suffix_never_becomes_a_term_on_its_own() {
        XCTAssertEqual(TextExpansion.managedVariants("Fosseway Freight Ltd"), ["Fosseway Freight Ltd", "Fosseway Freight"])
    }

    // tests/test_managed_vocab.py::ManagedVariantsTests::test_longest_form_comes_first
    func test_managed_vocab_ManagedVariantsTests_test_longest_form_comes_first() {
        XCTAssertEqual(TextExpansion.managedVariants("Alban Safety Limited"), ["Alban Safety Limited", "Alban Safety"])
    }

    // tests/test_managed_vocab.py::ManagedVariantsTests::test_short_junk_rows_produce_nothing
    func test_managed_vocab_ManagedVariantsTests_test_short_junk_rows_produce_nothing() {
        XCTAssertEqual(TextExpansion.managedVariants("Ltl"), [])
        XCTAssertEqual(TextExpansion.managedVariants("   "), [])
    }

    // tests/test_managed_vocab.py::ManagedVariantsTests::test_stacked_suffixes_unwind
    func test_managed_vocab_ManagedVariantsTests_test_stacked_suffixes_unwind() {
        XCTAssertEqual(TextExpansion.managedVariants("Kinetics Group"), ["Kinetics Group", "Kinetics"])
    }

    // tests/test_managed_vocab.py::ManagedVariantsTests::test_strips_a_trailing_tagline_after_a_colon
    func test_managed_vocab_ManagedVariantsTests_test_strips_a_trailing_tagline_after_a_colon() {
        XCTAssertEqual(TextExpansion.managedVariants("Boast International Ltd: Uk & International Freight Forwarder"), ["Boast International Ltd: Uk & International Freight Forwarder", "Boast International Ltd", "Boast International", "Boast"])
    }

    // tests/test_managed_vocab.py::ManagedVariantsTests::test_strips_legal_suffix_and_keeps_the_full_name
    func test_managed_vocab_ManagedVariantsTests_test_strips_legal_suffix_and_keeps_the_full_name() {
        XCTAssertEqual(TextExpansion.managedVariants("Fosseway Freight Ltd"), ["Fosseway Freight Ltd", "Fosseway Freight"])
    }

    // tests/test_managed_vocab.py::ManagedCorrectionTests::test_already_correct_text_is_left_for_the_casing_pass
    func test_managed_vocab_ManagedCorrectionTests_test_already_correct_text_is_left_for_the_casing_pass() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("chase up Wincanton about the order", entries: [VocabularyEntry(term: "Wincanton", managed: true)]), "chase up Wincanton about the order")
    }

    // tests/test_managed_vocab.py::ManagedCorrectionTests::test_corrects_a_misheard_company_name
    func test_managed_vocab_ManagedCorrectionTests_test_corrects_a_misheard_company_name() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("chase up win canton about the order", entries: [VocabularyEntry(term: "Wincanton", managed: true)]), "chase up Wincanton about the order")
    }

    // tests/test_managed_vocab.py::ManagedCorrectionTests::test_multi_word_names_are_corrected_at_the_normal_gate
    func test_managed_vocab_ManagedCorrectionTests_test_multi_word_names_are_corrected_at_the_normal_gate() {
        XCTAssertEqual(TextExpansion.managedVariants("Fosseway Freight Ltd"), ["Fosseway Freight Ltd", "Fosseway Freight"])
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the fosse way freight job", entries: [VocabularyEntry(term: "Fosseway Freight Ltd", managed: true), VocabularyEntry(term: "Fosseway Freight", managed: true)]), "the Fosseway Freight job")
    }

    // tests/test_managed_vocab.py::ManagedCorrectionTests::test_the_metaphone_gate_stays_the_primary_firewall
    func test_managed_vocab_ManagedCorrectionTests_test_the_metaphone_gate_stays_the_primary_firewall() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the storm lightning job", entries: [VocabularyEntry(term: "Storm Lighting", managed: true)]), "the storm lightning job")
    }

    // tests/test_managed_vocab.py::StrictTierTests::test_ordinary_speech_survives_a_realistic_crm
    func test_managed_vocab_StrictTierTests_test_ordinary_speech_survives_a_realistic_crm() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("michael said he would come", entries: [VocabularyEntry(term: "Michaels", managed: true), VocabularyEntry(term: "Storm", managed: true), VocabularyEntry(term: "Next", managed: true), VocabularyEntry(term: "Shell", managed: true), VocabularyEntry(term: "Wincanton", managed: true), VocabularyEntry(term: "No Letting Go", managed: true), VocabularyEntry(term: "Call Centre Ltd", managed: true)]), "michael said he would come")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("a warm welcome to everyone", entries: [VocabularyEntry(term: "Michaels", managed: true), VocabularyEntry(term: "Storm", managed: true), VocabularyEntry(term: "Next", managed: true), VocabularyEntry(term: "Shell", managed: true), VocabularyEntry(term: "Wincanton", managed: true), VocabularyEntry(term: "No Letting Go", managed: true), VocabularyEntry(term: "Call Centre Ltd", managed: true)]), "a warm welcome to everyone")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("sell the next one to them", entries: [VocabularyEntry(term: "Michaels", managed: true), VocabularyEntry(term: "Storm", managed: true), VocabularyEntry(term: "Next", managed: true), VocabularyEntry(term: "Shell", managed: true), VocabularyEntry(term: "Wincanton", managed: true), VocabularyEntry(term: "No Letting Go", managed: true), VocabularyEntry(term: "Call Centre Ltd", managed: true)]), "sell the next one to them")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("there is no letting go of that", entries: [VocabularyEntry(term: "Michaels", managed: true), VocabularyEntry(term: "Storm", managed: true), VocabularyEntry(term: "Next", managed: true), VocabularyEntry(term: "Shell", managed: true), VocabularyEntry(term: "Wincanton", managed: true), VocabularyEntry(term: "No Letting Go", managed: true), VocabularyEntry(term: "Call Centre Ltd", managed: true)]), "there is no letting go of that")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("i will take the call", entries: [VocabularyEntry(term: "Michaels", managed: true), VocabularyEntry(term: "Storm", managed: true), VocabularyEntry(term: "Next", managed: true), VocabularyEntry(term: "Shell", managed: true), VocabularyEntry(term: "Wincanton", managed: true), VocabularyEntry(term: "No Letting Go", managed: true), VocabularyEntry(term: "Call Centre Ltd", managed: true)]), "i will take the call")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("we shall look at it tomorrow", entries: [VocabularyEntry(term: "Michaels", managed: true), VocabularyEntry(term: "Storm", managed: true), VocabularyEntry(term: "Next", managed: true), VocabularyEntry(term: "Shell", managed: true), VocabularyEntry(term: "Wincanton", managed: true), VocabularyEntry(term: "No Letting Go", managed: true), VocabularyEntry(term: "Call Centre Ltd", managed: true)]), "we shall look at it tomorrow")
    }

    // tests/test_managed_vocab.py::StrictTierTests::test_short_single_word_managed_terms_are_dropped
    func test_managed_vocab_StrictTierTests_test_short_single_word_managed_terms_are_dropped() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the xxxxy thing", entries: [VocabularyEntry(term: "xxxx", managed: true)]), "the xxxxy thing")
    }

    // tests/test_managed_vocab.py::StrictTierTests::test_single_word_managed_term_that_is_ordinary_english_is_refused
    func test_managed_vocab_StrictTierTests_test_single_word_managed_term_that_is_ordinary_english_is_refused() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("we shall look at it tomorrow", entries: [VocabularyEntry(term: "Shell", managed: true)]), "we shall look at it tomorrow")
    }

    // tests/test_managed_vocab.py::StrictTierTests::test_the_same_term_typed_by_hand_is_allowed
    func test_managed_vocab_StrictTierTests_test_the_same_term_typed_by_hand_is_allowed() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("we shall look at it", entries: [VocabularyEntry(term: "Shell")]), "we Shell look at it")
    }

    // tests/test_managed_vocab.py::DigitTests::test_a_digitless_span_never_gains_a_number
    func test_managed_vocab_DigitTests_test_a_digitless_span_never_gains_a_number() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the company name is on the invoice", entries: [VocabularyEntry(term: "Company 28", managed: true)]), "the company name is on the invoice")
    }

    // tests/test_managed_vocab.py::DigitTests::test_a_hand_typed_term_is_held_to_the_same_rule
    func test_managed_vocab_DigitTests_test_a_hand_typed_term_is_held_to_the_same_rule() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("open ticket 4471 for them", entries: [VocabularyEntry(term: "Ticket 4472")]), "open ticket 4471 for them")
    }

    // tests/test_managed_vocab.py::DigitTests::test_a_span_never_loses_its_number
    func test_managed_vocab_DigitTests_test_a_span_never_loses_its_number() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("send it to Company 23 today", entries: [VocabularyEntry(term: "Company", managed: true)]), "send it to Company 23 today")
    }

    // tests/test_managed_vocab.py::DigitTests::test_a_term_differing_only_in_digits_is_refused
    func test_managed_vocab_DigitTests_test_a_term_differing_only_in_digits_is_refused() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("give like Company 23 context and stuff", entries: [VocabularyEntry(term: "Company 342", managed: true)]), "give like Company 23 context and stuff")
    }

    // tests/test_managed_vocab.py::DigitTests::test_the_same_number_still_corrects
    func test_managed_vocab_DigitTests_test_the_same_number_still_corrects() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("give like Companie 342 context", entries: [VocabularyEntry(term: "Company 342", managed: true)]), "give like Company 342 context")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_a_function_word_the_name_carries_is_not_padding
    func test_managed_vocab_FunctionWordTests_test_a_function_word_the_name_carries_is_not_padding() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the bank of ingland rate", entries: [VocabularyEntry(term: "Bank of England", managed: true)]), "the Bank of England rate")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_a_name_never_swallows_the_word_after_it
    func test_managed_vocab_FunctionWordTests_test_a_name_never_swallows_the_word_after_it() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("send Wincanton a letter", entries: [VocabularyEntry(term: "Wincanton", managed: true)]), "send Wincanton a letter")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_a_near_identical_one_word_merge_still_corrects
    func test_managed_vocab_FunctionWordTests_test_a_near_identical_one_word_merge_still_corrects() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("ship it with fosseway today", entries: [VocabularyEntry(term: "Fosse Way", managed: true)]), "ship it with Fosse Way today")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_half_function_words_is_refused_even_when_the_name_shares_them
    func test_managed_vocab_FunctionWordTests_test_half_function_words_is_refused_even_when_the_name_shares_them() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("put on the hat", entries: [VocabularyEntry(term: "The Hut", managed: true)]), "put on the hat")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_like_is_padding_not_part_of_a_name
    func test_managed_vocab_FunctionWordTests_test_like_is_padding_not_part_of_a_name() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("have to press like the show more", entries: [VocabularyEntry(term: "Proseal UK", managed: true)]), "have to press like the show more")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_mostly_function_words_can_never_become_a_managed_name
    func test_managed_vocab_FunctionWordTests_test_mostly_function_words_can_never_become_a_managed_name() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("we said in tune yesterday", entries: [VocabularyEntry(term: "Intune", managed: true)]), "we said in tune yesterday")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_one_function_word_in_three_is_still_padding
    func test_managed_vocab_FunctionWordTests_test_one_function_word_in_three_is_still_padding() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the room and wood floor", entries: [VocabularyEntry(term: "Raymond Wood", managed: true)]), "the room and wood floor")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_one_spoken_word_takes_the_strict_tier
    func test_managed_vocab_FunctionWordTests_test_one_spoken_word_takes_the_strict_tier() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("it's going dark on the right", entries: [VocabularyEntry(term: "The Ark", managed: true)]), "it's going dark on the right")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_ordinary_phrases_do_not_become_company_names
    func test_managed_vocab_FunctionWordTests_test_ordinary_phrases_do_not_become_company_names() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("please keep in touch", entries: [VocabularyEntry(term: "Intouch", managed: true)]), "please keep in touch")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_the_correction_still_lands_and_keeps_the_next_word
    func test_managed_vocab_FunctionWordTests_test_the_correction_still_lands_and_keeps_the_next_word() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("send wincantun a letter", entries: [VocabularyEntry(term: "Wincanton", managed: true)]), "send Wincanton a letter")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_the_real_dictation_is_left_alone
    func test_managed_vocab_FunctionWordTests_test_the_real_dictation_is_left_alone() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Display in their room and it should only ever affect my crochet 5.", entries: [VocabularyEntry(term: "Raymond Wood", managed: true)]), "Display in their room and it should only ever affect my crochet 5.")
    }

    // tests/test_managed_vocab.py::FunctionWordTests::test_the_report_is_not_a_contact
    func test_managed_vocab_FunctionWordTests_test_the_report_is_not_a_contact() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("send me the report today", entries: [VocabularyEntry(term: "Theo Rupert", managed: true)]), "send me the report today")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_a_hand_typed_term_is_held_to_the_same_rule
    func test_managed_vocab_SilentWordTests_test_a_hand_typed_term_is_held_to_the_same_rule() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the forklift is here", entries: [VocabularyEntry(term: "H & W Forklift")]), "the forklift is here")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_a_name_never_swallows_a_different_word_beside_it
    func test_managed_vocab_SilentWordTests_test_a_name_never_swallows_a_different_word_beside_it() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Can you check the artisans again today?", entries: [VocabularyEntry(term: "Artisans Way", managed: true)]), "Can you check the artisans again today?")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_a_slip_in_each_word_still_corrects
    func test_managed_vocab_SilentWordTests_test_a_slip_in_each_word_still_corrects() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("book the visit with Van Waal Lifts", entries: [VocabularyEntry(term: "Van Wall Lifts", managed: true)]), "book the visit with Van Wall Lifts")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_a_stored_full_stop_never_lands_mid_sentence
    func test_managed_vocab_SilentWordTests_test_a_stored_full_stop_never_lands_mid_sentence() {
        XCTAssertEqual(TextExpansion.managedVariants("Hinansho."), ["Hinansho"])
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("check the hinanshow order", entries: [VocabularyEntry(term: "Hinansho", managed: true)]), "check the Hinansho order")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_a_word_inside_a_name_never_becomes_the_whole_name
    func test_managed_vocab_SilentWordTests_test_a_word_inside_a_name_never_becomes_the_whole_name() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("We need a new forklift for the warehouse.", entries: [VocabularyEntry(term: "H & W Forklift Inc", managed: true), VocabularyEntry(term: "H & W Forklift", managed: true)]), "We need a new forklift for the warehouse.")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_an_ampersand_name_corrects_when_said_with_and
    func test_managed_vocab_SilentWordTests_test_an_ampersand_name_corrects_when_said_with_and() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("send it to Fagan and Wally by Friday", entries: [VocabularyEntry(term: "Fagan & Whalley", managed: true)]), "send it to Fagan & Whalley by Friday")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("add short and tall to the meeting", entries: [VocabularyEntry(term: "Short & Tall", managed: true)]), "add Short & Tall to the meeting")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_and_on_its_own_never_becomes_an_ampersand_name
    func test_managed_vocab_SilentWordTests_test_and_on_its_own_never_becomes_an_ampersand_name() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Short and simple, please.", entries: [VocabularyEntry(term: "Short & Tall", managed: true)]), "Short and simple, please.")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_four_and_five_word_names_correct
    func test_managed_vocab_SilentWordTests_test_four_and_five_word_names_correct() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("call Kennycott Glacier Lodge today", entries: [VocabularyEntry(term: "Kennicott Glacier Lodge", managed: true)]), "call Kennicott Glacier Lodge today")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("visit Orphila Vineyards and Winery soon", entries: [VocabularyEntry(term: "Orfila Vineyards & Winery", managed: true)]), "visit Orfila Vineyards & Winery soon")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_names_without_silent_words_still_merge
    func test_managed_vocab_SilentWordTests_test_names_without_silent_words_still_merge() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the brightlink rollout", entries: [VocabularyEntry(term: "Bright Link")]), "the Bright Link rollout")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Call fossway freight today", entries: [VocabularyEntry(term: "Fosseway Freight", managed: true)]), "Call Fosseway Freight today")
    }

    // tests/test_managed_vocab.py::SilentWordTests::test_one_word_never_grows_into_a_longer_name
    func test_managed_vocab_SilentWordTests_test_one_word_never_grows_into_a_longer_name() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Can you check the artisans today?", entries: [VocabularyEntry(term: "Artisans Way", managed: true)]), "Can you check the artisans today?")
    }

    // tests/test_managed_vocab.py::PrecedenceTests::test_user_entry_wins_when_it_collides_with_a_managed_one
    func test_managed_vocab_PrecedenceTests_test_user_entry_wins_when_it_collides_with_a_managed_one() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the bright link rollout", entries: [VocabularyEntry(term: "BrightLink"), VocabularyEntry(term: "Brightlink Ltd", managed: true)]), "the BrightLink rollout")
    }

    func test_double_metaphone_matches_python() {
        let cases: [(String, String, String)] = [
            ("Vercel", "FRSL", ""),
            ("vercell", "FRSL", ""),
            ("ver cell", "FRSL", ""),
            ("versel", "FRSL", ""),
            ("versaille", "FRSL", ""),
            ("Pipedrive", "PPTRF", ""),
            ("pipe drife", "PPTRF", ""),
            ("kubectl", "KPKTL", ""),
            ("Kubecuttle", "KPKTL", ""),
            ("Marcel", "MRSL", ""),
            ("excel", "AKSL", ""),
            ("the cell", "0SL", "TSL"),
            ("Smith", "SM0", "XMT"),
            ("Schmidt", "XMT", "SMT"),
            ("Xavier", "SF", "SFR"),
            ("Knight", "NT", ""),
            ("Wright", "RT", ""),
            ("Psychology", "SXLJ", "SKLK"),
            ("Caesar", "SSR", ""),
            ("Michael", "MKL", "MXL"),
            ("church", "XRX", "XRK"),
            ("chianti", "KNT", ""),
            ("bacher", "PKR", ""),
            ("mccormick", "MKRMK", ""),
            ("accident", "AKSTNT", ""),
            ("bacci", "PX", ""),
            ("focaccia", "FKX", ""),
            ("czerny", "SRN", "XRN"),
            ("dodge", "TJ", ""),
            ("edge", "AJ", ""),
            ("laugh", "LF", ""),
            ("cough", "KF", ""),
            ("hugh", "HH", ""),
            ("ghislane", "JLN", ""),
            ("Gnome", "NM", ""),
            ("agnes", "AKNS", "ANS"),
            ("cagney", "KKN", ""),
            ("tagliaro", "TKLR", "TLR"),
            ("gerald", "KRLT", "JRLT"),
            ("biaggi", "PJ", "PK"),
            ("Jose", "JS", "HS"),
            ("San Jacinto", "SNHSNT", ""),
            ("bajador", "PJTR", "PHTR"),
            ("Yankelovich", "ANKLFX", "ANKLFK"),
            ("cabrillo", "KPRL", "KPR"),
            ("gallegos", "KLKS", "KKS"),
            ("dumb", "TMP", ""),
            ("thumb", "0MP", "TMP"),
            ("number", "NMPR", ""),
            ("campbell", "KMPL", ""),
            ("raspberry", "RSPR", ""),
            ("rogier", "RJ", "RKR"),
            ("hochmeier", "HKMR", ""),
            ("sugar", "XKR", "SKR"),
            ("school", "SKL", ""),
            ("schermerhorn", "XRMRRN", "SKRMRRN"),
            ("sion", "SN", "XN"),
            ("Asia", "AS", "AX"),
            ("artois", "ART", "ARTS"),
            ("resnais", "RSN", "RSNS"),
            ("Thomas", "TMS", ""),
            ("Thames", "TMS", ""),
            ("nation", "NXN", ""),
            ("match", "MX", ""),
            ("wasserman", "ASRMN", "FSRMN"),
            ("Arnow", "ARN", "ARNF"),
            ("filipowicz", "FLPTS", "FLPFX"),
            ("breaux", "PR", ""),
            ("zhao", "J", ""),
            ("Mozzi", "MS", "MTS"),
            ("Fagan and Whalley", "FKNNTL", ""),
            ("H & W Forklift", "FRKLFT", ""),
            ("company23", "KMPN", ""),
            ("company342", "KMPN", ""),
            ("it's", "ATTS", ""),
            ("don't", "TNNT", ""),
            ("Acme, Inc.", "AKMNKK", ""),
            ("Bank of Ireland", "PNKFRLNT", ""),
            ("hed of sails", "HTFSLS", ""),
            ("Push it", "PXT", ""),
            ("Wincanton", "ANKNTN", "FNKNTN"),
            ("Fosseway Freight", "FSFRT", ""),
            ("Brightlink", "PRTLNK", ""),
            ("BrightLink Solutions", "PRTLNKSLXNS", ""),
            ("\u{C7}a va", "SF", ""),
            ("na\u{EF}ve", "NF", ""),
            ("Zo\u{EB}", "S", ""),
            ("stra\u{DF}e", "STRS", ""),
            ("a", "A", ""),
            ("I", "A", ""),
            ("", "", ""),
            ("x1y2", "S", ""),
            ("abc-1", "APKKK", ""),
            ("rock'n'roll", "RKKKL", ""),
            ("phone", "FN", ""),
            ("knee", "N", ""),
            ("wrap", "RP", ""),
            ("pshaw", "X", "XF"),
            ("Ghent", "KNT", ""),
            ("tough", "TF", ""),
            ("island", "ALNT", ""),
            ("isle", "AL", ""),
            ("carlisle", "KRLL", ""),
            ("aggie", "AJ", "AK"),
            ("bough", "P", ""),
            ("sought", "SKT", ""),
            ("hajj", "HJ", ""),
            ("Jaworski", "JRSK", "ARSK"),
            ("Gallagher", "KLKR", ""),
            ("Eugene", "AJN", "AKN"),
            ("Stephen", "STFN", ""),
            ("Whitney", "ATN", ""),
            ("Wu", "A", "F"),
            ("Xi", "S", ""),
            ("mcclellan", "MKLLN", ""),
            ("accede", "AKST", ""),
            ("succeed", "SKST", ""),
            ("bellocchio", "PLX", ""),
            ("chorus", "KRS", ""),
            ("character", "KRKTR", ""),
            ("orchestra", "ARKSTR", ""),
            ("architect", "ARKTKT", ""),
            ("orchid", "ARKT", ""),
            ("van gogh", "FNKK", ""),
        ]
        for (word, primary, secondary) in cases {
            let got: (String, String) = TextExpansion.doubleMetaphone(word)
            XCTAssertEqual(got.0, primary, "primary code of \(word)")
            XCTAssertEqual(got.1, secondary, "secondary code of \(word)")
        }
    }

    func test_fuzzy_extra_cases_from_python() {
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Deploy to vercell now.", entries: [VocabularyEntry(term: "Vercel")]), "Deploy to Vercel now.")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("We met Wincanton yesterday and talked with winkanton", entries: [VocabularyEntry(term: "Wincanton", managed: true)]), "We met Wincanton yesterday and talked with Wincanton")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("send wincantun a letter", entries: [VocabularyEntry(term: "Wincanton", managed: true)], wordConfidence: [nil, 0.5, nil, nil]), "send Wincanton a letter")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("send wincantun a letter", entries: [VocabularyEntry(term: "Wincanton", managed: true)], wordConfidence: [nil, 0.99, nil, nil]), "send wincantun a letter")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("fagan and whalley rang", entries: [VocabularyEntry(term: "Fagan & Whalley", managed: true)], wordConfidence: [0.4, 0.4, 0.4, nil]), "Fagan & Whalley rang")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("fagan and whaley rang", entries: [VocabularyEntry(term: "Fagan & Whalley")]), "Fagan & Whalley rang")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Company 23 is fine", entries: [VocabularyEntry(term: "Company 342")]), "Company 23 is fine")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("the hat is here", entries: [VocabularyEntry(term: "The Hut", managed: true)], wordConfidence: [0.2, 0.2, nil, nil]), "the hat is here")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Say vercell ver sel and kubecuttle", entries: [VocabularyEntry(term: "Vercel"), VocabularyEntry(term: "kubectl")]), "Say Vercel Vercel and kubectl")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("brightlink solutions called", entries: [VocabularyEntry(term: "Bright Link Solutions", managed: true)], wordConfidence: [0.3, 0.3, nil]), "Bright Link Solutions called")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("Hello vercell\nVercell again. vercell", entries: [VocabularyEntry(term: "Vercel")]), "Hello Vercel\nVercel again. Vercel")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("caf\u{E9} vercell \u{1F600} vercell", entries: [VocabularyEntry(term: "Vercel")]), "caf\u{E9} Vercel \u{1F600} Vercel")
        XCTAssertEqual(TextExpansion.applyVocabularyFuzzy("again it's ali's again", entries: [VocabularyEntry(term: "Ali's Wagon", managed: true)], wordConfidence: [0.3, 0.3, 0.3, 0.3]), "again it's ali's again")
    }

    func test_managed_variants_extra() {
        XCTAssertEqual(TextExpansion.managedVariants("Fosseway Freight Ltd"), ["Fosseway Freight Ltd", "Fosseway Freight"])
        XCTAssertEqual(TextExpansion.managedVariants("Boast International Ltd: Uk & International Freight Forwarder"), ["Boast International Ltd: Uk & International Freight Forwarder", "Boast International Ltd", "Boast International", "Boast"])
        XCTAssertEqual(TextExpansion.managedVariants("hinansho."), ["hinansho"])
        XCTAssertEqual(TextExpansion.managedVariants("Ltd"), [])
        XCTAssertEqual(TextExpansion.managedVariants("A B Ltd Co"), ["A B Ltd Co", "A B Ltd", "A B"])
        XCTAssertEqual(TextExpansion.managedVariants("  Acme   Holdings Group  "), ["Acme Holdings Group", "Acme Holdings"])
        XCTAssertEqual(TextExpansion.managedVariants("Storm"), ["Storm"])
        XCTAssertEqual(TextExpansion.managedVariants("Michaels Inc."), ["Michaels Inc", "Michaels"])
        XCTAssertEqual(TextExpansion.managedVariants(""), [])
        XCTAssertEqual(TextExpansion.managedVariants("X: Y"), ["X: Y"])
    }

    func test_vocabulary_entry_codable_matches_supabase_shape() throws {
        let json: String = "{\"term\":\"Pipedrive\",\"sounds_like\":[\"pipe drive\",\"pipe drift\"]}"
        let entry: VocabularyEntry = try JSONDecoder().decode(VocabularyEntry.self, from: Data(json.utf8))
        XCTAssertEqual(entry.term, "Pipedrive")
        XCTAssertEqual(entry.soundsLike, ["pipe drive", "pipe drift"])
        XCTAssertFalse(entry.deleted)
        XCTAssertFalse(entry.managed)
        let again: VocabularyEntry = try JSONDecoder().decode(VocabularyEntry.self, from: JSONEncoder().encode(entry))
        XCTAssertEqual(entry, again)
        let bare: VocabularyEntry = try JSONDecoder().decode(VocabularyEntry.self, from: Data("{\"term\":\"X\"}".utf8))
        XCTAssertEqual(bare.soundsLike, [])
    }

}
