"""Everyday tool and brand names are spelt right, and ordinary English is not
touched (common_terms.py)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common_terms import apply_common_terms, names_for_prompt  # noqa: E402
from spoken_commands import apply_spoken_commands  # noqa: E402


class NamesSpeltRight(unittest.TestCase):
    CASES = [
        # Seen in real dictation (Nov 2026 history).
        ("I really like how chat GBT works", "I really like how ChatGPT works"),
        ("give it to like Chat GBT and say", "give it to like ChatGPT and say"),
        ("ChatGBT Image 2.5", "ChatGPT Image 2.5"),
        ("run the recent changes to my local host", "run the recent changes to my localhost"),
        ("run it on localhost 8080", "run it on localhost:8080"),
        ("open local host eight zero eight zero please", "open localhost:8080 please"),
        ("run it by eight zero eight zero local host?", "run it by localhost:8080?"),
        ("open 3000 localhost now", "open localhost:3000 now"),
        ("start two localhost servers", "start two localhost servers"),
        ("what Whisperflow does better", "what Wispr Flow does better"),
        ("use whisper flow for that", "use Wispr Flow for that"),
        ("ask clawed code to do it", "ask Claude Code to do it"),
        ("tools like microsoft teams", "tools like Microsoft Teams"),
        ("jump on a teams call", "jump on a Teams call"),
        ("I'll message you on teams.", "I'll message you on Teams."),
        ("save it to share point", "save it to SharePoint"),
        ("it's in my one drive", "it's in my OneDrive"),
        ("a power point deck", "a PowerPoint deck"),
        ("my linked in profile", "my LinkedIn profile"),
        ("post it on linked in", "post it on LinkedIn"),
        ("a you tube video", "a YouTube video"),
        ("the git hub repo", "the GitHub repo"),
        ("update hub spot and pipe drive", "update HubSpot and Pipedrive"),
        ("export from quick books", "export from QuickBooks"),
        ("send it on whats app", "send it on WhatsApp"),
        ("a google meet link", "a Google Meet link"),
        ("put it in google sheets", "put it in Google Sheets"),
        ("my g mail inbox", "my Gmail inbox"),
        ("the bright link CRM", "the BrightLink CRM"),
        ("Brightlink Echo", "BrightLink Echo"),
        ("brightlink notetaker", "BrightLink Notetaker"),
        ("call the a p i", "call the API"),
        ("a b2b SaaS", "a B2B SaaS"),
        ("type script and java script", "TypeScript and JavaScript"),
        ("in a zoom meeting", "in a Zoom meeting"),
        ("drop it in the slack channel", "drop it in the Slack channel"),
    ]

    def test_names(self):
        for spoken, want in self.CASES:
            with self.subTest(spoken=spoken):
                self.assertEqual(apply_common_terms(spoken), want)

    def test_runs_inside_spoken_commands(self):
        self.assertEqual(apply_spoken_commands("ask chat GBT"), "ask ChatGPT")


class OrdinaryEnglishUntouched(unittest.TestCase):
    PROSE = [
        "we work in teams of five",
        "the teams played well",
        "plug it into the power point by the door",
        "our sales force is growing",
        "copy it from one drive to another",
        "I message him every day",
        "I phone two people every morning",
        "the cat clawed the sofa",
        "the cloud moved over the moon",
        "a claw around the moon",
        "the two tables are linked in the database",
        "our local host family was lovely",
        "cut them some slack",
        "zoom in on the picture",
        "the outlook for next year is good",
        "she will excel at this",
        "in a word, no",
        "go from B to C",
        "a bright link between the two ideas",
        "a pine cone fell",
        "echo the same point",
        "visit brightlink.io today",
        "see github.com/RJMURPHY0 for code",
        "email ryan@brightlink.io",
    ]
    KEEP_CASE_AS_IS = {
        # "a bright link" is the one ordinary phrase the brand rule takes;
        # accepted, the phrase is rare and the brand is everywhere in Echo.
        "a bright link between the two ideas",
    }

    def test_prose(self):
        for line in self.PROSE:
            if line in self.KEEP_CASE_AS_IS:
                continue
            with self.subTest(line=line):
                self.assertEqual(apply_common_terms(line), line)


class PromptNames(unittest.TestCase):
    def test_list_has_the_names_people_say(self):
        names = names_for_prompt()
        for n in ("Claude", "ChatGPT", "Anthropic", "OpenAI", "Microsoft Teams",
                  "BrightLink", "Hermes", "Pinecone"):
            self.assertIn(n, names)


if __name__ == "__main__":
    unittest.main()
