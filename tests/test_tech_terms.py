"""AI model names and versions (tech_terms.py), through apply_spoken_commands."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spoken_commands import apply_spoken_commands as sc


class ModelVersionTests(unittest.TestCase):
    def test_reported_case(self):
        self.assertEqual(sc("I used opus five point five today"),
                         "I used Opus 5.5 today")

    def test_fixes(self):
        cases = [
            ("claude opus five point five", "Claude Opus 5.5"),
            ("Claude Sonnet four point five is fast", "Claude Sonnet 4.5 is fast"),
            ("try haiku four point five", "try Haiku 4.5"),
            ("Fable 5 point 1", "Fable 5.1"),
            ("claude three point seven", "Claude 3.7"),
            ("gpt five", "GPT-5"),
            ("GPT 4.1 mini", "GPT-4.1 mini"),
            ("gpt four o", "GPT-4o"),
            ("gemini two point five pro", "Gemini 2.5 Pro"),
            ("gemini 2.5 flash", "Gemini 2.5 Flash"),
            ("llama three point one", "Llama 3.1"),
            ("deep seek v three", "DeepSeek V3"),
            ("grok four", "Grok 4"),
            ("chat gpt is down", "ChatGPT is down"),
            ("open ai and anthropic", "OpenAI and Anthropic"),
            ("check lm arena for the rankings", "check LMArena for the rankings"),
            ("Opus 5.5", "Opus 5.5"),
        ]
        for src, want in cases:
            self.assertEqual(sc(src), want, src)

    def test_prose_left_alone(self):
        keeps = [
            "at one point five people left",
            "she wrote a haiku about spring",
            "the llama farm is open",
            "his magnum opus. Two days later he left",
            "I gave Claude four tasks",
            "a sonnet and a haiku",
            "I used Opus 5. 5 people agreed",
            "GPT or Gemini, either is fine",
        ]
        for src in keeps:
            want = src.replace("GPT or", "GPT or")
            self.assertEqual(sc(src), want, src)


if __name__ == "__main__":
    unittest.main()
