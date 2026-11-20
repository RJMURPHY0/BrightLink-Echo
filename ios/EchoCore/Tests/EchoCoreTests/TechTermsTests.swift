import XCTest
@testable import EchoCore

/// Ported from the Python suite: every call below is a (input, output) pair taken from the Python tests
/// (outputs recorded from the Python implementation while its own tests passed).
final class TechTermsTests: XCTestCase {
    func test_model_names_and_versions() {
        XCTAssertEqual(TechTerms.apply("gemini 2 point 5 pro"), "Gemini 2.5 Pro")
        XCTAssertEqual(TechTerms.apply("claude sonnet four point five"), "Claude Sonnet 4.5")
        XCTAssertEqual(TechTerms.apply("gpt five"), "GPT-5")
        XCTAssertEqual(TechTerms.apply("gpt four o"), "GPT-4o")
        XCTAssertEqual(TechTerms.apply("deep seek v three"), "DeepSeek V3")
        XCTAssertEqual(TechTerms.apply("opus twenty five"), "Opus 25")
        XCTAssertEqual(TechTerms.apply("claude four"), "claude four")
        XCTAssertEqual(TechTerms.apply("I like llms and an LLM"), "I like LLMs and an LLM")
        XCTAssertEqual(TechTerms.apply("hugging face and eleven labs"), "Hugging Face and ElevenLabs")
        XCTAssertEqual(TechTerms.apply("mid journey v six"), "Midjourney v six")
        XCTAssertEqual(TechTerms.apply("kimi k two"), "Kimi k two")
        XCTAssertEqual(TechTerms.apply("chat-gpt"), "ChatGPT")
        XCTAssertEqual(TechTerms.apply("gemini  two\tpoint\tfive   flash"), "Gemini 2.5 Flash")
        XCTAssertEqual(TechTerms.apply("Claude Opus four point one preview"), "Claude Opus 4.1 Preview")
        XCTAssertEqual(TechTerms.apply("qwen three max"), "Qwen 3 Max")
        XCTAssertEqual(TechTerms.apply("gpt 4 turbo"), "GPT-4 Turbo")
        XCTAssertEqual(TechTerms.apply("sora two"), "Sora 2")
        XCTAssertEqual(TechTerms.apply("a haiku"), "a haiku")
        XCTAssertEqual(TechTerms.apply(""), "")
        XCTAssertEqual(TechTerms.apply("grok"), "Grok")
        XCTAssertEqual(TechTerms.apply("phi four mini"), "Phi 4 mini")
        XCTAssertEqual(TechTerms.apply("veo three point one"), "Veo 3.1")
        XCTAssertEqual(TechTerms.apply("gemma two"), "Gemma 2")
        XCTAssertEqual(TechTerms.apply("mistral seven"), "Mistral 7")
        XCTAssertEqual(TechTerms.apply("codex five point one nano"), "Codex 5.1 nano")
    }

    // tests/test_tech_terms.py inputs, applied to TechTerms directly
    func test_tech_terms_python_cases() {
        XCTAssertEqual(TechTerms.apply("claude opus five point five"), "Claude Opus 5.5")
        XCTAssertEqual(TechTerms.apply("Claude Sonnet four point five is fast"), "Claude Sonnet 4.5 is fast")
        XCTAssertEqual(TechTerms.apply("try haiku four point five"), "try Haiku 4.5")
        XCTAssertEqual(TechTerms.apply("Fable 5 point 1"), "Fable 5.1")
        XCTAssertEqual(TechTerms.apply("claude three point seven"), "Claude 3.7")
        XCTAssertEqual(TechTerms.apply("gpt five"), "GPT-5")
        XCTAssertEqual(TechTerms.apply("GPT 4.1 mini"), "GPT-4.1 mini")
        XCTAssertEqual(TechTerms.apply("gpt four o"), "GPT-4o")
        XCTAssertEqual(TechTerms.apply("gemini two point five pro"), "Gemini 2.5 Pro")
        XCTAssertEqual(TechTerms.apply("gemini 2.5 flash"), "Gemini 2.5 Flash")
        XCTAssertEqual(TechTerms.apply("llama three point one"), "Llama 3.1")
        XCTAssertEqual(TechTerms.apply("deep seek v three"), "DeepSeek V3")
        XCTAssertEqual(TechTerms.apply("grok four"), "Grok 4")
        XCTAssertEqual(TechTerms.apply("chat gpt is down"), "ChatGPT is down")
        XCTAssertEqual(TechTerms.apply("open ai and anthropic"), "OpenAI and Anthropic")
        XCTAssertEqual(TechTerms.apply("check lm arena for the rankings"), "check LMArena for the rankings")
        XCTAssertEqual(TechTerms.apply("Opus 5.5"), "Opus 5.5")
        XCTAssertEqual(TechTerms.apply("I used opus five point five today"), "I used Opus 5.5 today")
        XCTAssertEqual(TechTerms.apply("at one point five people left"), "at one point five people left")
        XCTAssertEqual(TechTerms.apply("she wrote a haiku about spring"), "she wrote a haiku about spring")
        XCTAssertEqual(TechTerms.apply("the llama farm is open"), "the llama farm is open")
        XCTAssertEqual(TechTerms.apply("his magnum opus. Two days later he left"), "his magnum opus. Two days later he left")
        XCTAssertEqual(TechTerms.apply("I gave Claude four tasks"), "I gave Claude four tasks")
        XCTAssertEqual(TechTerms.apply("a sonnet and a haiku"), "a sonnet and a haiku")
        XCTAssertEqual(TechTerms.apply("I used Opus 5. 5 people agreed"), "I used Opus 5. 5 people agreed")
        XCTAssertEqual(TechTerms.apply("GPT or Gemini, either is fine"), "GPT or Gemini, either is fine")
    }
}
