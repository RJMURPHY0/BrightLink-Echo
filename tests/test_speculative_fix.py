"""The AI check that runs while the user talks (speculative_fix.py), the
names it is given (vocab_context.py), job words (job_vocab.py) and the local
paragraph rules (paragraphs.py)."""

import os
import sys
import threading
import time
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import job_vocab  # noqa: E402
import paragraphs  # noqa: E402
import speculative_fix as sf  # noqa: E402
import vocab_context  # noqa: E402


class Swaps(unittest.TestCase):
    def test_a_sound_alike_becomes_the_name_where_its_neighbours_still_are(self):
        swaps = sf.derive_swaps("Short-term memory and clawed or whatever.",
                                "Short-term memory and Claude or whatever.")
        self.assertEqual(len(swaps), 1)
        # The final decode punctuates differently: the swap still lands.
        out, n = sf.apply_swaps("Maybe short-term memory and clawed, or whatever", swaps)
        self.assertEqual(n, 1)
        self.assertEqual(out, "Maybe short-term memory and Claude, or whatever")

    def test_a_swap_whose_neighbours_changed_is_not_applied(self):
        swaps = sf.derive_swaps("memory and clawed or", "memory and Claude or")
        out, n = sf.apply_swaps("the cat clawed the sofa", swaps)
        self.assertEqual((out, n), ("the cat clawed the sofa", 0))

    def test_two_words_join_into_one_name(self):
        swaps = sf.derive_swaps("how chat GBT works", "how ChatGPT works")
        out, _ = sf.apply_swaps("I like how chat GBT works.", swaps)
        self.assertEqual(out, "I like how ChatGPT works.")

    def test_words_join_only_when_they_spell_the_name(self):
        # Real-model output, 2026-11-20: these two dropped a word Ryan said.
        self.assertEqual(sf.derive_swaps("like clawed cloud.", "like Claude."), [])
        self.assertEqual(sf.derive_swaps("my has cloud agent", "my Claude agent"), [])
        self.assertEqual(sf.derive_swaps("like clawed cloud.", "like Claude Code."), [])
        self.assertEqual(len(sf.derive_swaps("use whisper flow now", "use Wispr Flow now")), 1)
        self.assertEqual(len(sf.derive_swaps("or pine cone for", "or Pinecone for")), 1)

    def test_numbers_and_added_words_never_come_through(self):
        self.assertEqual(sf.derive_swaps("pay 50 now", "pay 15 now"), [])
        self.assertEqual(sf.derive_swaps("send it", "please send it now"), [])

    def test_line_breaks_are_kept(self):
        swaps = sf.derive_swaps("and clawed or", "and Claude or")
        out, _ = sf.apply_swaps("Hi Jo,\n\nmemory and clawed or not", swaps)
        self.assertEqual(out, "Hi Jo,\n\nmemory and Claude or not")

    def test_sentence_opening_capital_is_kept(self):
        swaps = sf.derive_swaps("ok. clawed is great", "ok. Claude is great")
        swaps2 = sf.derive_swaps("then wright the note", "then write the note")
        out, _ = sf.apply_swaps("Wright the note", swaps2 + swaps)
        self.assertEqual(out, "Wright the note")   # no left neighbour: not applied
        out, _ = sf.apply_swaps("then Wright the note", swaps2)
        self.assertEqual(out, "then Write the note")


class _FakeRefiner:
    def __init__(self, delay=0.0):
        self.delay = delay
        self.fix_calls = []
        self.plan_calls = []
        self.last_relay_error = ""
        self.is_available = True

    def context_fix(self, text, names=""):
        self.fix_calls.append((text, names))
        time.sleep(self.delay)
        return text.replace("clawed", "Claude")

    def plan_paragraphs(self, sents):
        self.plan_calls.append(list(sents))
        return [i for i, s in enumerate(sents) if s.startswith("Another")]


def _wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class Fixer(unittest.TestCase):
    def _fixer(self, ref, **kw):
        f = sf.SpeculativeFixer(ref, lambda t: vocab_context.LIST_MARK + "Claude.", **kw)
        f.MIN_GAP = 0.0
        self.addCleanup(f.stop)
        return f

    def test_checks_finished_sentences_while_talking_and_applies_at_release(self):
        ref = _FakeRefiner()
        f = self._fixer(ref, paragraphs=False)
        f.feed("I used clawed for the code. It was quick. And then")
        self.assertTrue(_wait(lambda: ref.fix_calls))
        self.assertTrue(_wait(lambda: f.apply_fixes("x")[2] == 0 and f._swaps))
        f.stop()
        out, n, hit, total = f.apply_fixes("I used clawed for the code. It was quick. And then we left.")
        self.assertEqual(out, "I used Claude for the code. It was quick. And then we left.")
        self.assertEqual((n, hit, total), (1, 2, 3))
        # The unfinished last sentence was never sent.
        self.assertNotIn("And then", ref.fix_calls[0][0])
        self.assertEqual(ref.fix_calls[0][1], vocab_context.LIST_MARK + "Claude.")

    def test_only_swaps_into_a_listed_name_are_applied(self):
        class _Wild(_FakeRefiner):
            def context_fix(self, text, names=""):
                self.fix_calls.append((text, names))
                return text.replace("clawed", "Claude").replace("moon", "mood")
        ref = _Wild()
        f = sf.SpeculativeFixer(ref, lambda t: vocab_context.LIST_MARK + "Claude; ChatGPT.",
                                paragraphs=False)
        f.MIN_GAP = 0.0
        self.addCleanup(f.stop)
        f.feed("I asked clawed about the moon tonight. Then")
        self.assertTrue(_wait(lambda: f._swaps))
        time.sleep(0.1)
        out, n, _h, _t = f.apply_fixes("I asked clawed about the moon tonight. Then we left.")
        self.assertEqual(out, "I asked Claude about the moon tonight. Then we left.")
        self.assertEqual(n, 1)

    def test_words_in_the_blocks_own_wording_are_not_names(self):
        # Review 2026-11-20: "there" -> "here" passed because the header says
        # "written here".
        block = vocab_context.block("memory and clawed put it there")
        self.assertTrue(sf._is_listed(["Claude"], block))
        self.assertFalse(sf._is_listed(["here"], block))
        self.assertFalse(sf._is_listed(["exactly"], block))

    def test_release_never_waits_for_a_call_in_flight(self):
        ref = _FakeRefiner(delay=1.5)
        f = self._fixer(ref, paragraphs=False)
        f.feed("I used clawed today. More words")
        self.assertTrue(_wait(lambda: ref.fix_calls))
        t0 = time.monotonic()
        f.stop()
        out, n, hit, total = f.apply_fixes("I used clawed today. More words.")
        self.assertLess(time.monotonic() - t0, 0.05)
        self.assertEqual(n, 0)          # not back yet: engine text stands
        self.assertEqual(out, "I used clawed today. More words.")

    def test_calls_are_capped_per_dictation(self):
        ref = _FakeRefiner()
        f = self._fixer(ref, paragraphs=False)
        f.MAX_CALLS = 2
        for i in range(6):
            f.feed(" ".join(f"Sentence number {j} here." for j in range(i + 2)) + " tail")
            time.sleep(0.05)
        time.sleep(0.3)
        self.assertLessEqual(len(ref.fix_calls), 2)

    def test_paragraph_plan_while_talking(self):
        ref = _FakeRefiner()
        f = self._fixer(ref, fixes=False)
        text = ("We met the client on Monday. They liked the demo. They asked about price. "
                "Another thing is the office move. It happens in March. Then")
        f.feed(text)
        self.assertTrue(_wait(lambda: ref.plan_calls))
        self.assertTrue(_wait(lambda: f.paragraph_plan()[0]))
        keys, covered = f.paragraph_plan()
        out = sf.apply_paragraphs(text.replace(" Then", " Then we left."), keys, covered)
        self.assertIn("price.\n\nAnother thing", out)


class Paragraphs(unittest.TestCase):
    LONG = ("We need to sort the invoices for October before Friday because the "
            "accountant wants them early this year and there are a few missing. "
            "I think three of them are from the same supplier so that should be "
            "quick to chase up with one email. ")

    def test_topic_shift_opener_starts_a_paragraph(self):
        text = self.LONG + "Also, can you book the van for Tuesday?"
        out = paragraphs.split_local(text)
        self.assertIn("email.\n\nAlso, can you", out)

    def test_short_text_is_never_split(self):
        text = "Thanks for that. Also, see you Tuesday."
        self.assertEqual(paragraphs.split_local(text), text)

    def test_a_wall_of_text_breaks_at_a_sentence(self):
        text = " ".join(["This is a sentence with exactly ten words in it."] * 16)
        out = paragraphs.split_local(text)
        self.assertGreaterEqual(out.count("\n\n"), 1)
        for para in out.split("\n\n"):
            self.assertTrue(para.endswith("."))

    def test_lists_and_email_layouts_are_left_alone(self):
        text = "Hi Sam,\n" + self.LONG + "Also, one more.\nThanks,\nRyan"
        self.assertEqual(paragraphs.split_local(text), text)
        self.assertEqual(sf.apply_paragraphs(text, {"also one more"}, set()), text)

    def test_ai_judged_sentences_are_not_split_again(self):
        text = self.LONG + "Also, can you book the van?"
        key = sf.sentence_key("Also, can you book the van?")
        self.assertEqual(paragraphs.split_local(text, {key}, sf.sentence_key), text)


class NamesBlock(unittest.TestCase):
    def test_only_names_bearing_on_the_text(self):
        b = vocab_context.block("short-term memory and clawed", ["Pipedrive"],
                                ["Raymond Wood", "Clare Smith"], ["RIDDOR"])
        self.assertIn("Claude", b)
        self.assertIn("Pipedrive", b)          # the user's own words always go
        self.assertIn("Clare Smith", b)        # "cla" like "clawed"
        self.assertNotIn("Raymond Wood", b)
        self.assertNotIn("RIDDOR", b)

    def test_sound_alike_list_pulls_its_name_in(self):
        self.assertIn("Hermes", vocab_context.block("the homies cloud agent"))

    def test_part_of_a_longer_name_counts_when_the_rest_is_beside_it(self):
        b = vocab_context.block("john smit", ["John Smith"])
        (sw,) = sf.derive_swaps("I called John Smit yesterday", "I called John Smith yesterday")
        self.assertTrue(sf._is_listed(sw.new, b, sw.left, sw.right))
        self.assertFalse(sf._is_listed(["Smith"], b, "the", "said"))

    def test_a_name_with_a_comma_stays_one_name(self):
        # Review 2026-11-20: "Smith, Jones & Co" became two listed names.
        b = vocab_context.block("smith jones", ["Smith, Jones & Co"])
        self.assertIn("Smith, Jones & Co", vocab_context.listed_names(b))
        self.assertFalse(sf._is_listed(["Smith"], b))

    def test_block_fits_the_relay(self):
        many = [f"Name{i} Person{i}" for i in range(3000)]
        b = vocab_context.block("name person " * 50, crm_names=many)
        self.assertLessEqual(len(b), vocab_context.MAX_CHARS + 50)


class JobWords(unittest.TestCase):
    def test_casing_for_ticked_jobs_only(self):
        self.assertEqual(job_vocab.apply_job_casing("fill in the riddor and coshh forms", ["safety"]),
                         "fill in the RIDDOR and COSHH forms")
        self.assertEqual(job_vocab.apply_job_casing("fill in the riddor form", []),
                         "fill in the riddor form")

    def test_english_words_are_never_cased(self):
        prose = ("add some sage, the stripe on the wall, cut them some slack, "
                 "the outlook is good, we need a notion of it, the rams in the field")
        self.assertEqual(job_vocab.apply_job_casing(prose, list(job_vocab.PACKS)), prose)

    def test_team_default_and_an_explicit_none(self):
        cfg = SimpleNamespace(work_roles={}, work_description={})
        self.assertEqual(job_vocab.effective_roles(cfg, "a@brightlink.io"),
                         list(job_vocab.BRIGHTLINK_TEAM_DEFAULT))
        self.assertEqual(job_vocab.effective_roles(cfg, "a@gmail.com"), [])
        cfg.work_roles = job_vocab.with_mine(cfg, "work_roles", "a@brightlink.io",
                                             [job_vocab.NONE_CHOSEN])
        self.assertEqual(job_vocab.effective_roles(cfg, "a@brightlink.io"), [])

    def test_work_details_belong_to_one_account(self):
        # Review 2026-11-20: one account's description reached another's prompts.
        cfg = SimpleNamespace(work_roles={}, work_description={})
        cfg.work_roles = job_vocab.with_mine(cfg, "work_roles", "a@x.com", ["legal"])
        cfg.work_description = job_vocab.with_mine(cfg, "work_description", "a@x.com",
                                                   "Partner at a law firm")
        self.assertEqual(job_vocab.effective_roles(cfg, "b@y.com"), [])
        self.assertEqual(job_vocab.job_line(cfg, "b@y.com"), "")
        self.assertIn("law firm", job_vocab.job_line(cfg, "A@X.com"))
        import cloud_sync
        self.assertNotIn("work_roles", cloud_sync.SYNCED_SETTINGS)
        self.assertNotIn("work_description", cloud_sync.SYNCED_SETTINGS)

    def test_every_pack_is_sizeable_and_labelled(self):
        for rid, (label, terms) in job_vocab.PACKS.items():
            self.assertTrue(label)
            self.assertGreaterEqual(len(terms), 60, rid)

    def test_config_defaults_exist(self):
        from config import Config
        c = Config()
        self.assertEqual(c.work_roles, {})
        self.assertEqual(c.work_description, {})


if __name__ == "__main__":
    unittest.main()
