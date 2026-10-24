"""
Per-user contextual vocabulary booster.

Seeds each user's transcription context from what we already know about them:
their company, role, tech stack, product names, and common phrase patterns.
For super-admin accounts this goes further: every technical term, tool name,
framework, and domain-specific phrase that the build environment and account
profile expose is promoted immediately — no counting-from-zero required.

This sits ABOVE phrase_learning (which learns FROM dictation) and vocab_store
(which is hand-curated): those are reactive, this is PROACTIVE.  A new install
or a fresh machine still transcribes \"Supabase\", \"Vercel\", and
\"BrightLink\" correctly on the very first dictation because the context was
already there.

Integration points:
  - PhraseStore seeding on load  (phrase_learning.py)
  - ASR hotwords               (asr_engine.py / stream_session.py)
  - AI refiner system prompt   (ai_refiner.py)

Storage: nothing new.  Terms are written INTO phrase_learning's PhraseStore
and/or vocab_store, so they survive the existing flush/sync/clear flows.
"""

import json
import os
import re
import threading
from datetime import datetime, timezone

import brand
import data_paths
from phrase_learning import (
    PhraseStore,
    MAX_HOTWORDS,
    RESCUE_CONF,
    _now,
)


# ── Role labels matched against account metadata ───────────────────────────────

ROLE_SUPER_ADMIN = "super_admin"
_ROLE_KEYS = {
    ROLE_SUPER_ADMIN,
    "admin",
    "user",
    "owner",
}


# ── Static context dictionaries ────────────────────────────────────────────────
#
# These are NOT user-editable vocab entries; they are the seed material that
# user_context folds into each account's PhraseStore on first load (or when
# refreshed).  Editing a term here changes what NEW installs get; it does NOT
# retroactively edit an existing store (the store owns its own counts).

# Domain-agnostic SaaS / tech terms that almost any power user says.
_COMMON_TECH = [
    # Platforms & infra
    "API", "REST", "GraphQL", "webhook", "endpoint", "SDK", "CLI",
    "deployment", "serverless", "container", "microservice", "monolith",
    "repository", "commit", "push", "pull request", "branch", "merge",
    "CI/CD", "pipeline", "build", "artifact",
    # Data
    "database", "PostgreSQL", "SQL", "NoSQL", "vector", "embedding",
    "index", "query", "row", "column", "schema", "migration",
    # Auth & security
    "OAuth", "SSO", "SAML", "MFA", "two-factor", "JWT", "token",
    "encryption", "GDPR", "compliance", "audit",
    # Payments
    "Stripe", "subscription", "billing", "invoice", "credit", "proration",
    # General dev
    "Python", "TypeScript", "JavaScript", "React", "Node.js", "npm",
    "framework", "library", "package", "dependency", "module",
    "function", "async", "callback", "Promise", "enum", "interface",
    # Product-y words
    "onboarding", "churn", "retention", "funnel", "cohort", "segment",
    "feature flag", "A/B test", "rollout", "canary", "dark launch",
    "roadmap", "sprint", "backlog", "standup", "retro",
]

# Multi-word phrases that carry meaning as units.
_COMMON_PHRASES = [
    "push to production",
    "pull request",
    "code review",
    "unit test",
    "integration test",
    "end-to-end",
    "proof of concept",
    "minimum viable product",
    "single sign-on",
    "source code",
    "version control",
    "hot fix",
    "tech debt",
    "user story",
    "acceptance criteria",
    "definition of done",
]

# BrightLink-specific terms — the product, companies, and ecosystem.
_BRIGHTLINK_TERMS = [
    # Company & product names (casing matters)
    "BrightLink", "Brightlink",
    "FTC Safety Solutions", "FTC Safety", "FTC",
    brand.PRODUCT_NAME,  # e.g. "BrightLink Echo"
    "BrightLink Notetaker",
    # Internal project codenames / repos
    "ClaudeOS", "Claude OS",
    # Platform names
    "Supabase", "Vercel",
    "OpenRouter",
    "Anthropic", "OpenAI", "Groq",
    "Google Gemini", "Gemini",
    "HuggingFace", "Hugging Face",
    # Tools Ryan uses daily
    "Claude Code",
    "PyInstaller",
    "n8n", "Resend", "Apify", "Firecrawl",
    "Companies House", "HMRC",
    "Twilio", "Pinecone",
    "Obsidian",
    "Inno Setup", "GitHub Actions",
    "Azure Artifact Signing",
    "Parakeet", "faster-whisper",
    "ONNX", "onnx-asr",
    "NVIDIA",
    # Product modules (capitalised as proper nouns)
    "Recall",
    "Document Studio",
    "Lead Scraper",
    "Knowledge Base",
    "Super Admin",
    # Domain terms
    "multi-tenant", "multi-module",
    "credit-based",
    "push-to-talk",
    "dictation",
    "transcription",
    "ASR",
    "automatic speech recognition",
    "voice training",
    "phrase learning",
    "text expansion",
    "homophone",
]

_BRIGHTLINK_PHRASES = [
    # Things Ryan actually says repeatedly (sampled from real transcripts)
    "BrightLink pipeline",
    "scrape anything",
    "lead finder",
    "prospect intel",
    "contact record",
    "email sequence",
    "outreach campaign",
    "meeting notes",
    "voice memo",
    "dictation accuracy",
    "one-shot",
    "best result",
    "cost effective",
    "apprenticeship evidence",
    "Laura assessor",
    "Jason CEO",
    "FTC Safety",
    "new venture",
    "SaaS subscription",
    "business OS",
    "operating system",
    "credit model",
    "per-customer context",
    "memory engine",
    "context ingestion",
    "vectorise",
    "enterprise readiness",
    "cybersecurity hardening",
    "GDPR compliance",
    "billing guard",
    "debit credits",
    "rate limit",
    "auto-update",
    "CI pipeline",
    "release asset",
    "signed build",
    "VirusTotal scan",
    "false positive",
    "branding-naming",
    "product name",
    "working name",
    "rebrand imminent",
    "neutral strings",
    "hardcoded",
    "silent failure",
    "force push",
    "pre-commit hook",
    "deep work window",
    "evening build",
    "weekend rule",
    "daily review",
    "energy curve",
    "challenger brand",
    "commercial voice",
    "no fluff",
    "direct confident",
    "receipts",
    "clickable links",
    "one question at a time",
    "act first",
    "pragmatic iteration",
    "big-bang refactoring",
    "federated repos",
    "not a monorepo",
    "free-first waterfall",
    "paid enrichment",
    "RLS policy",
    "row level security",
    "job queue",
    "browser-resident",
    "tab close",
    "metered route",
    "usage race",
    "tenancy model",
    "separately sellable",
    "share one DB",
    "PascalCase tables",
    "snake_case columns",
    "null userId",
    "org-scoped",
    "user-scoped",
    "core differentiator",
    "first paying client",
    "land first clients",
    "register the new venture",
    "legal entity not yet registered",
    "co-founder with Jason",
    "marketing executive",
    "apprenticeship evidence",
    "submit professionally to Laura",
    # Technical patterns Ryan references
    "LLM", "large language model",
    "token budget",
    "context window",
    "prompt engineering",
    "system prompt",
    "temperature setting",
    "top-p sampling",
    "fine-tuning", "finetuning",
    "RAG", "retrieval augmented generation",
    "vector database",
    "embedding model",
    "semantic search",
    "chunking strategy",
    "cross-encoder",
    "bi-encoder",
    "knowledge graph",
    "double metaphone",
    "Jaro-Winkler",
    "phonetic matching",
    "fuzzy match",
    "Levenshtein",
    "edit distance",
    "sentence piece",
    "log probability",
    "softmax",
    "decoder prompt",
    "encoder padding",
    "WER", "word error rate",
    "realtime factor",
    "latency budget",
    "stop latency",
    "injection",
    "clipboard restore",
    "focus capture",
    "global hotkey",
    "daemon thread",
    "debounced write",
    "atomic rename",
    "tombstone approach",
    "soft delete",
    "last-write-wins",
    "idempotent",
    "fire-and-forget",
    "opt-in default",
    "fail closed",
    "graceful degradation",
    # Hermes / agent terminology
    "Hermes Agent",
    "Nous Research",
    "subagent delegation",
    "tool use",
    "function calling",
    "MoA", "mixture of agents",
    "vision model",
    "multimodal",
    "GLM", "glm-5v-turbo",
    "session memory",
    "holographic memory",
    "fact store",
    "skill system",
    "kanban board",
    "cron job",
    "webhook trigger",
    "desktop app",
    "tray icon",
    "floating popup",
    "toast notification",
]


def _is_super_admin(email: str = "", role: str = "") -> bool:
    """Whether this account gets the full BrightLink builder context."""
    e = (email or "").strip().lower()
    r = (role or "").strip().lower()
    if ROLE_SUPER_ADMIN in r or "superadmin" in r or "super_admin" in r:
        return True
    # Known super-admin addresses.
    if e.endswith("@ftc.co.uk") or e.endswith("ryan.murphy") or e == "rjmurphy0":
        return True
    return False


def _base_terms() -> list:
    """Terms every power user gets."""
    return list(_COMMON_TECH)


def _base_phrases() -> list:
    """Phrases every power user gets."""
    return list(_COMMON_PHRASES)


def _brightlink_terms() -> list:
    return list(_BRIGHTLINK_TERMS)


def _brightlink_phrases() -> list:
    return list(_BRIGHTLINK_PHRASES)


# ── Seeder ────────────────────────────────────────────────────────────────────

class UserContext:
    """Generates and maintains per-user context boosts.

    One instance per signed-in account, created by app.py on login and handed
    to every component that needs context (ASR engine, refiner, phrase learner).
    Thread-safe: reads are lock-free, writes (seed/refresh) take the lock.
    """

    def __init__(self, email: str = "", role: str = "",
                 phrase_store: PhraseStore = None):
        self.email = (email or "").strip().lower()
        self.role = role.strip()
        self._store = phrase_store  # may be None before auth
        self._lock = threading.Lock()
        self._sealed = False       # True after first seed prevents re-seed
        self._seeded_at = None     # ISO timestamp or None
        self._term_count = 0
        self._phrase_count = 0

        # Cached lists — rebuilt on refresh().
        self._all_terms = []
        self._all_phrases = []

    # -- public API -----------------------------------------------------------

    def seed(self, phrase_store: PhraseStore | None = None) -> int:
        """Push static context into the phrase store. Returns count seeded.

        Idempotent: runs once per instance unless ``force=True`` is passed.
        Call with the live PhraseStore once auth has produced one.
        """
        store: PhraseStore | None = phrase_store or self._store
        if store is None:
            return 0
        with self._lock:
            if self._sealed:
                return self._term_count + self._phrase_count
            total = self._do_seed(store)
            self._sealed = True
            self._seeded_at = _now()
            return total

    def force_reseed(self, phrase_store: PhraseStore | None = None) -> int:
        """Re-seed even if already sealed (e.g. role upgrade)."""
        store: PhraseStore | None = phrase_store or self._store
        if store is None:
            return 0
        with self._lock:
            self._sealed = False
            total = self._do_seed(store)
            self._sealed = True
            self._seeded_at = _now()
            return total

    def refresh(self) -> None:
        """Rebuild the cached term/phrase lists from current store state."""
        store = self._store
        if store is None:
            return
        with self._lock:
            phrases = store.phrases()
            terms = [p["phrase"] for p in phrases]
            self._all_terms = terms
            self._all_phrases = [t for t in terms if " " in t]

    def terms(self) -> list:
        """Single-word boosted terms."""
        with self._lock:
            return list(self._all_terms)

    def phrases(self) -> list:
        """Multi-word boosted phrases."""
        with self._lock:
            return list(self._all_phrases)

    def hotwords(self, limit: int = MAX_HOTWORDS) -> str:
        """Comma-joined string for ASR decoder hotwords= parameter."""
        from phrase_learning import hotwords as _hw
        return _hw(self.phrases(), limit=limit)

    def context_for_refiner(self) -> str:
        """A short paragraph for the AI refiner's system prompt.

        Lists the user's domain so the model knows which capitalisations
        and spellings are correct and never 'fixes' them.
        """
        parts = []
        if self._is_bl:
            parts.append(
                "User works at BrightLink (BRIGHTLINK OS LTD), building a "
                "multi-module SaaS business OS. Key terms that must NEVER be "
                "changed by the refiner:"
            )
            bl_sorted = sorted(set(
                _brightlink_terms() + _brightlink_phrases()
            ))
            parts.append(", ".join(bl_sorted[:80]))
            if len(bl_sorted) > 80:
                parts.append(f"  (+{len(bl_sorted) - 80} more)")
        else:
            parts.append(
                "User is a tech-literate professional. Preserve proper nouns "
                "and technical terms."
            )
        return "\n".join(parts)

    @property
    def _is_bl(self) -> bool:
        return _is_super_admin(self.email, self.role)

    @property
    def sealed(self) -> bool:
        with self._lock:
            return self._sealed

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "seeded_at": self._seeded_at,
                "term_count": self._term_count,
                "phrase_count": self._phrase_count,
                "total_cached": len(self._all_terms),
                "is_super_admin": self._is_bl,
            }

    # -- internals ------------------------------------------------------------

    def _do_seed(self, store: PhraseStore) -> int:
        """Write context into the store. MUST hold self._lock."""
        is_bl = self._is_bl
        terms = _base_terms()
        phrases = _base_phrases()
        if is_bl:
            terms.extend(_brightlink_terms())
            phrases.extend(_brightlink_phrases())

        t_count, p_count = 0, 0
        now_iso = _now()

        # Single words go into the phrase store as single-word promoted entries
        # with a high initial count so they sort above learned-but-rare phrases.
        for term in terms:
            norm = term.lower()
            # Skip if already present (don't overwrite counts).
            if norm in store._phrases:
                continue
            store._phrases[norm] = {
                "phrase": term,
                "count": 50,          # high seed weight beats ordinary learned
                "learned_at": now_iso,
            }
            t_count += 1

        # Multi-word phrases same treatment.
        for phrase in phrases:
            words = phrase.lower().split()
            norm = " ".join(words)
            if norm in store._phrases:
                continue
            store._phrases[norm] = {
                "phrase": phrase,
                "count": 40,
                "learned_at": now_iso,
            }
            p_count += 1

        store._prune()
        store._touch(urgent=True)

        self._term_count = t_count
        self._phrase_count = p_count

        # Rebuild caches.
        raw = store.phrases()
        self._all_terms = [r["phrase"] for r in raw]
        self._all_phrases = [r["phrase"] for r in raw if " " in r["phrase"]]

        return t_count + p_count


# ── Convenience: build context for a given account ────────────────────────────

def build_for(email: str = "", role: str = "",
              phrase_store: PhraseStore = None) -> UserContext:
    """Factory. Creates, optionally seeds, returns."""
    ctx = UserContext(email=email, role=role, phrase_store=phrase_store)
    if phrase_store is not None:
        ctx.seed()
    return ctx
