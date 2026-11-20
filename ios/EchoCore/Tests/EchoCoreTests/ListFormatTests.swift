import XCTest
@testable import EchoCore

/// Ported from the Python suite: every call below is a (input, output) pair taken from the Python tests
/// (outputs recorded from the Python implementation while its own tests passed).
final class ListFormatTests: XCTestCase {
    // tests/test_list_format.py::NumberedTests::test_a_marker_that_is_part_of_the_sentence_is_kept
    func test_list_format_NumberedTests_test_a_marker_that_is_part_of_the_sentence_is_kept() {
        XCTAssertEqual(ListFormat.format("Here are the two things. first is the colour of the box, second is the size of it."), "Here are the two things:\n\n1. First is the colour of the box.\n2. Second is the size of it.")
    }

    // tests/test_list_format.py::NumberedTests::test_a_slot_said_twice_counts_once
    func test_list_format_NumberedTests_test_a_slot_said_twice_counts_once() {
        XCTAssertEqual(ListFormat.format("So, I want to have a list, so, first, so like number one, I want to have a few different things. Number two, I want to have a few other things."), "So, I want to have a list:\n\n1. I want to have a few different things.\n2. I want to have a few other things.")
    }

    // tests/test_list_format.py::NumberedTests::test_bare_discourse_markers_are_absorbed_by_the_number
    func test_list_format_NumberedTests_test_bare_discourse_markers_are_absorbed_by_the_number() {
        XCTAssertEqual(ListFormat.format("There are three things I need to do. First, push the release. Second, update the docs. Third, tell Ryan."), "There are three things I need to do:\n\n1. Push the release\n2. Update the docs\n3. Tell Ryan")
    }

    // tests/test_list_format.py::NumberedTests::test_bare_space_markers_need_an_announcement
    func test_list_format_NumberedTests_test_bare_space_markers_need_an_announcement() {
        XCTAssertEqual(ListFormat.format("We scored number one in the league and number two in the cup this year."), "We scored number one in the league and number two in the cup this year.")
        XCTAssertEqual(ListFormat.format("The first thing I noticed was the colour, and the second thing I noticed was the size of it."), "The first thing I noticed was the colour, and the second thing I noticed was the size of it.")
        XCTAssertEqual(ListFormat.format("I came first and second in the two races this year, which was great."), "I came first and second in the two races this year, which was great.")
    }

    // tests/test_list_format.py::NumberedTests::test_finally_closes_a_run_but_never_starts_one
    func test_list_format_NumberedTests_test_finally_closes_a_run_but_never_starts_one() {
        XCTAssertEqual(ListFormat.format("There are three steps. First, open it. Second, edit it. Finally, save it."), "There are three steps:\n\n1. Open it\n2. Edit it\n3. Save it")
        XCTAssertEqual(ListFormat.format("Finally I got the thing working after all that effort."), "Finally I got the thing working after all that effort.")
    }

    // tests/test_list_format.py::NumberedTests::test_for_number_two_leaves_no_dangling_for
    func test_list_format_NumberedTests_test_for_number_two_leaves_no_dangling_for() {
        XCTAssertEqual(ListFormat.format("So, I just want to list a few things, so, firstly, I want to have this one thing, you know, for number two I want to have the second thing"), "So, I just want to list a few things:\n\n1. I want to have this one thing, you know.\n2. I want to have the second thing.")
    }

    // tests/test_list_format.py::NumberedTests::test_ly_forms
    func test_list_format_NumberedTests_test_ly_forms() {
        XCTAssertEqual(ListFormat.format("There are three reasons. Firstly, it is faster. Secondly, it is cheaper. Thirdly, it is simpler."), "There are three reasons:\n\n1. It is faster.\n2. It is cheaper.\n3. It is simpler.")
    }

    // tests/test_list_format.py::NumberedTests::test_number_markers_written_as_digits
    func test_list_format_NumberedTests_test_number_markers_written_as_digits() {
        XCTAssertEqual(ListFormat.format("Here are the jobs, number 1, fix the login page. Number 2, update the search bar."), "Here are the jobs:\n\n1. Fix the login page\n2. Update the search bar")
    }

    // tests/test_list_format.py::NumberedTests::test_number_one_inside_a_sentence_is_prose
    func test_list_format_NumberedTests_test_number_one_inside_a_sentence_is_prose() {
        XCTAssertEqual(ListFormat.format("My number one priority is the release. Then number two on the list is docs."), "My number one priority is the release. Then number two on the list is docs.")
        XCTAssertEqual(ListFormat.format("We scored number one in the league this year and it was great."), "We scored number one in the league this year and it was great.")
    }

    // tests/test_list_format.py::NumberedTests::test_number_one_style
    func test_list_format_NumberedTests_test_number_one_style() {
        XCTAssertEqual(ListFormat.format("There are three things to fix. Number one, the login page. Number two, the search bar. Number three, the footer."), "There are three things to fix:\n\n1. The login page\n2. The search bar\n3. The footer")
    }

    // tests/test_list_format.py::NumberedTests::test_text_after_the_list_becomes_its_own_paragraph
    func test_list_format_NumberedTests_test_text_after_the_list_becomes_its_own_paragraph() {
        XCTAssertEqual(ListFormat.format("There are two reasons for this. First, it is faster. Second, it is cheaper. Then we can move on to the next bit."), "There are two reasons for this:\n\n1. It is faster.\n2. It is cheaper.\n\nThen we can move on to the next bit.")
    }

    // tests/test_list_format.py::NumberedTests::test_the_2026_09_21_and_number_two_example
    func test_list_format_NumberedTests_test_the_2026_09_21_and_number_two_example() {
        XCTAssertEqual(ListFormat.format("So I just want to list a few things, so number one, I want to just think about one thing and number two i want to think about another thing"), "So I just want to list a few things:\n\n1. I want to just think about one thing.\n2. I want to think about another thing.")
    }

    // tests/test_list_format.py::NumberedTests::test_the_2026_09_21_number_one_example
    func test_list_format_NumberedTests_test_the_2026_09_21_number_one_example() {
        XCTAssertEqual(ListFormat.format("So, I want to start a list for a few things that I want to do, so, number one, I want to have good CPU energy. Number two, I want to have good GPU energy."), "So, I want to start a list for a few things that I want to do:\n\n1. I want to have good CPU energy.\n2. I want to have good GPU energy.")
    }

    // tests/test_list_format.py::NumberedTests::test_the_first_thing_is_the_second_thing_is
    func test_list_format_NumberedTests_test_the_first_thing_is_the_second_thing_is() {
        XCTAssertEqual(ListFormat.format("There are two things to check, the first thing is the login page and the second thing is the search bar."), "There are two things to check:\n\n1. The login page\n2. The search bar")
    }

    // tests/test_list_format.py::NumberedTests::test_the_reported_example
    func test_list_format_NumberedTests_test_the_reported_example() {
        XCTAssertEqual(ListFormat.format("Right, so here's a list of three things. first is like the first thing, second is the second thing."), "Right, so here's a list of three things:\n\n1. First is like the first thing.\n2. Second is the second thing.")
    }

    // tests/test_list_format.py::NumberedTests::test_three_markers_need_no_announcement
    func test_list_format_NumberedTests_test_three_markers_need_no_announcement() {
        XCTAssertEqual(ListFormat.format("First, wake up. Second, get dressed. Third, leave the house."), "1. Wake up\n2. Get dressed\n3. Leave the house")
    }

    // tests/test_list_format.py::NumberedTests::test_two_explicit_number_markers_need_no_announcement
    func test_list_format_NumberedTests_test_two_explicit_number_markers_need_no_announcement() {
        XCTAssertEqual(ListFormat.format("Number one, fix the login page. Number two, update the search bar."), "1. Fix the login page\n2. Update the search bar")
    }

    // tests/test_list_format.py::NumberedTests::test_two_markers_without_an_announcement_are_left_alone
    func test_list_format_NumberedTests_test_two_markers_without_an_announcement_are_left_alone() {
        XCTAssertEqual(ListFormat.format("First of all, thanks very much for coming along today. Second, let us make a start on the agenda."), "First of all, thanks very much for coming along today. Second, let us make a start on the agenda.")
    }

    // tests/test_list_format.py::SpokenBulletTests::test_bare_and_next_bullet_point
    func test_list_format_SpokenBulletTests_test_bare_and_next_bullet_point() {
        XCTAssertEqual(ListFormat.format("Here is what I need, bullet point, the new laptop charger. Next bullet point, a spare mouse for the office."), "Here is what I need:\n\n- The new laptop charger\n- A spare mouse for the office")
    }

    // tests/test_list_format.py::SpokenBulletTests::test_bullet_point_one_two_three
    func test_list_format_SpokenBulletTests_test_bullet_point_one_two_three() {
        XCTAssertEqual(ListFormat.format("Things to pack for the trip. Bullet point one, a warm coat. Bullet point two, some walking boots. Bullet point three, the travel adapters."), "Things to pack for the trip.\n\n- A warm coat\n- Some walking boots\n- The travel adapters")
    }

    // tests/test_list_format.py::SpokenBulletTests::test_bullets_and_numbers_never_mix
    func test_list_format_SpokenBulletTests_test_bullets_and_numbers_never_mix() {
        XCTAssertEqual(ListFormat.format("Here are two things. Bullet point one, a warm coat. Number two, some walking boots."), "Here are two things. Bullet point one, a warm coat. Number two, some walking boots.")
    }

    // tests/test_list_format.py::SpokenBulletTests::test_the_2026_09_21_first_bullet_point_is_example
    func test_list_format_SpokenBulletTests_test_the_2026_09_21_first_bullet_point_is_example() {
        XCTAssertEqual(ListFormat.format("I just want to list a couple things, so the first bullet point is CPU energy and the second bullet point is GPU energy"), "I just want to list a couple things:\n\n- CPU energy\n- GPU energy")
    }

    // tests/test_list_format.py::BulletTests::test_announced_series
    func test_list_format_BulletTests_test_announced_series() {
        XCTAssertEqual(ListFormat.format("Here are the three things I need: milk, bread and eggs."), "Here are the three things I need:\n\n- Milk\n- Bread\n- Eggs")
    }

    // tests/test_list_format.py::BulletTests::test_long_items_are_prose_not_bullets
    func test_list_format_BulletTests_test_long_items_are_prose_not_bullets() {
        XCTAssertEqual(ListFormat.format("Here are the three things I need: a really long and detailed explanation of the first item, bread and eggs."), "Here are the three things I need: a really long and detailed explanation of the first item, bread and eggs.")
    }

    // tests/test_list_format.py::BulletTests::test_or_series
    func test_list_format_BulletTests_test_or_series() {
        XCTAssertEqual(ListFormat.format("There are three options here: keep it, change it or drop it."), "There are three options here:\n\n- Keep it\n- Change it\n- Drop it")
    }

    // tests/test_list_format.py::BulletTests::test_oxford_comma
    func test_list_format_BulletTests_test_oxford_comma() {
        XCTAssertEqual(ListFormat.format("We need the following. Milk, bread, and eggs."), "We need the following:\n\n- Milk\n- Bread\n- Eggs")
    }

    // tests/test_list_format.py::BulletTests::test_two_item_series_is_not_a_list
    func test_list_format_BulletTests_test_two_item_series_is_not_a_list() {
        XCTAssertEqual(ListFormat.format("Here are the two things I need: milk and bread."), "Here are the two things I need: milk and bread.")
    }

    // tests/test_list_format.py::FalsePositiveTests::test_already_formatted_text_is_left_alone
    func test_list_format_FalsePositiveTests_test_already_formatted_text_is_left_alone() {
        XCTAssertEqual(ListFormat.format("Here are three things:\n\n1. One thing\n2. Another thing"), "Here are three things:\n\n1. One thing\n2. Another thing")
        XCTAssertEqual(ListFormat.format("Here are three things:\n\n- One thing\n- Another thing"), "Here are three things:\n\n- One thing\n- Another thing")
    }

    // tests/test_list_format.py::FalsePositiveTests::test_discursive_ordinals
    func test_list_format_FalsePositiveTests_test_discursive_ordinals() {
        XCTAssertEqual(ListFormat.format("First of all I want to say thank you for everything."), "First of all I want to say thank you for everything.")
        XCTAssertEqual(ListFormat.format("The first thing I noticed was the colour, which was odd."), "The first thing I noticed was the colour, which was odd.")
        XCTAssertEqual(ListFormat.format("He came second in the race and I came third overall."), "He came second in the race and I came third overall.")
        XCTAssertEqual(ListFormat.format("That was my first attempt at doing it this way."), "That was my first attempt at doing it this way.")
    }

    // tests/test_list_format.py::FalsePositiveTests::test_empty_and_none
    func test_list_format_FalsePositiveTests_test_empty_and_none() {
        XCTAssertEqual(ListFormat.format(""), "")
    }

    // tests/test_list_format.py::FalsePositiveTests::test_items_shorter_than_two_words_block_the_list
    func test_list_format_FalsePositiveTests_test_items_shorter_than_two_words_block_the_list() {
        XCTAssertEqual(ListFormat.format("There are three things. First, no. Second, yes. Third, maybe."), "There are three things. First, no. Second, yes. Third, maybe.")
    }

    // tests/test_list_format.py::FalsePositiveTests::test_plain_comma_series
    func test_list_format_FalsePositiveTests_test_plain_comma_series() {
        XCTAssertEqual(ListFormat.format("I went to the shop, the bank and home."), "I went to the shop, the bank and home.")
        XCTAssertEqual(ListFormat.format("We use Python, tkinter and PyInstaller for this."), "We use Python, tkinter and PyInstaller for this.")
        XCTAssertEqual(ListFormat.format("It was cold, wet and windy all day."), "It was cold, wet and windy all day.")
    }

    // tests/test_list_format.py::FalsePositiveTests::test_short_utterances_are_never_touched
    func test_list_format_FalsePositiveTests_test_short_utterances_are_never_touched() {
        XCTAssertEqual(ListFormat.format("First, do it."), "First, do it.")
        XCTAssertEqual(ListFormat.format("Yes please"), "Yes please")
        XCTAssertEqual(ListFormat.format("one moment"), "one moment")
    }

    // tests/test_list_format.py::NaturalSpeechTests::test_a_lead_in_cut_off_by_a_pause_is_not_an_announcement
    func test_list_format_NaturalSpeechTests_test_a_lead_in_cut_off_by_a_pause_is_not_an_announcement() {
        XCTAssertEqual(ListFormat.format("Here are the things I need for. Milk, bread and eggs."), "Here are the things I need for. Milk, bread and eggs.")
        XCTAssertEqual(ListFormat.format("Here are the things I need. Milk, bread and eggs."), "Here are the things I need:\n\n- Milk\n- Bread\n- Eggs")
    }

    // tests/test_list_format.py::NaturalSpeechTests::test_an_example_run_is_not_a_list
    func test_list_format_NaturalSpeechTests_test_an_example_run_is_not_a_list() {
        XCTAssertEqual(ListFormat.format("Okay, number one, call Jason about the pipeline, number two, sort of thing, so yeah do that."), "Okay, number one, call Jason about the pipeline, number two, sort of thing, so yeah do that.")
        XCTAssertEqual(ListFormat.format("Okay, number one, call Jason about the pipeline, number two, send the invoice."), "1. Call Jason about the pipeline\n2. Send the invoice")
    }

    // tests/test_list_format.py::NaturalSpeechTests::test_fillers_and_clause_fragments_are_not_items
    func test_list_format_NaturalSpeechTests_test_fillers_and_clause_fragments_are_not_items() {
        XCTAssertEqual(ListFormat.format("Here are the three things: the subscriptions, you know, and the tools."), "Here are the three things: the subscriptions, you know, and the tools.")
        XCTAssertEqual(ListFormat.format("Here are the three things: the subscriptions, that are, and the tools."), "Here are the three things: the subscriptions, that are, and the tools.")
        XCTAssertEqual(ListFormat.format("Here are the three things: the plan, but like the old one, and everything."), "Here are the three things: the plan, but like the old one, and everything.")
    }

    // tests/test_list_format.py::NaturalSpeechTests::test_the_2026_09_25_reported_example_stays_prose
    func test_list_format_NaturalSpeechTests_test_the_2026_09_25_reported_example_stays_prose() {
        XCTAssertEqual(ListFormat.format("None of the usage there is actually being used at all, and it would be really good if I could get the usage for. The subscriptions I'm genuinely paying for, that are, you know, like AI related, and still good. I'm actually Using those consumption limits and stuff, so, yeah."), "None of the usage there is actually being used at all, and it would be really good if I could get the usage for. The subscriptions I'm genuinely paying for, that are, you know, like AI related, and still good. I'm actually Using those consumption limits and stuff, so, yeah.")
    }

    // tests/test_list_format.py::NaturalSpeechTests::test_the_other_corpus_false_positives_stay_prose
    func test_list_format_NaturalSpeechTests_test_the_other_corpus_false_positives_stay_prose() {
        XCTAssertEqual(ListFormat.format("I feel like even if there is an admin you can like be able to see unassigned data, but if you're not an admin, Then you can just only other see like other people's data. Also, check like the tasks, and everything there. If I am selecting like Jason or like anyone else, then it should come up."), "I feel like even if there is an admin you can like be able to see unassigned data, but if you're not an admin, Then you can just only other see like other people's data. Also, check like the tasks, and everything there. If I am selecting like Jason or like anyone else, then it should come up.")
        XCTAssertEqual(ListFormat.format("Different applications, so this is kind of like a rule. If there is a different web app or anything that's opening in a different tab. That's kind of like a standalone product, but like still within the whole operating system, and everything. Then, you know, the note ticker, I think, should come first"), "Different applications, so this is kind of like a rule. If there is a different web app or anything that's opening in a different tab. That's kind of like a standalone product, but like still within the whole operating system, and everything. Then, you know, the note ticker, I think, should come first")
        XCTAssertEqual(ListFormat.format("it should be like the colon and then Like you know, number one, you know, it should be able to genuinely correctly identify where. I would, you know, the user would want it to be a list, like number one, number two, sort of thing, so yeah, do that and then Push it as a new install link"), "it should be like the colon and then Like you know, number one, you know, it should be able to genuinely correctly identify where. I would, you know, the user would want it to be a list, like number one, number two, sort of thing, so yeah, do that and then Push it as a new install link")
    }

}
