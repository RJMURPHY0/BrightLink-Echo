"""
Company vocabulary profiles: the words a whole company says that the
recogniser does not know (an industry's kit, its paperwork, its regulators).

A profile is chosen from the signed-in account's email domain, the one company
fact Echo always has offline. Its terms join the CRM names as MANAGED entries
in `app._managed_entries`, so they go only where managed terms are safe:

  * the phonetic corrector's strict tier (`text_expansion.apply_vocabulary_
    fuzzy`): single words need jw 0.86, ordinary English is refused outright,
    a name may not absorb or swap function words, digits must match, and with
    a confidence record the span must hold a word the engine was UNSURE of;
  * Parakeet's casing post-pass, which can only recase a word already there.

Never a whisper decoder prompt (`_get_prompt_hotwords` excludes the managed
set): a term list that reaches a prompt can be spoken back as text nobody
said. Every profile term is reviewed here, by hand, in the repo.

BrightLink's own product names are in every profile: every account uses the
products.

No new table. A shared company vocabulary (an admin typing terms for the whole
company) would belong to the Brightlink repo, which owns the shared schema; when
it exists, its rows join `terms_for()` here.
"""

from typing import List

import brand

# BrightLink's products, by their on-screen names. "Document Studio" and
# "Lead Scraper" are deliberately absent: made of ordinary words, they matched
# "documents", "DocumentStudio.tsx" and "Lead Scraper UI is" in the corpus run
# (2026-11-18) and rewrote them.
_BRIGHTLINK_PRODUCTS = [
    brand.CRM_NAME, brand.PRODUCT_NAME,
    brand.CRM_NAME + " Notetaker", brand.CRM_NAME + " CRM",
    brand.CRM_NAME + " Design",
]

# Workplace safety and materials handling (FTC Safety Solutions). Terms the
# recogniser splits or mangles; ordinary words ("ladder", "harness") are left
# out because the corrector refuses ordinary English anyway. "PUWER" is
# absent on purpose: it encodes exactly like "power" and rewrote every one in
# the corpus run; the casing post-pass cannot reach it either way.
_SAFETY = [
    "forklift", "forklifts", "reach truck", "pallet truck", "telehandler",
    "MEWP", "MEWPs", "LOLER", "COSHH", "RIDDOR", "HSE",
    "RAMS", "method statement", "risk assessment", "permit to work",
    "toolbox talk", "near miss", "hi-vis", "PPE", "racking inspection",
    "SEMA", "lift truck", "counterbalance", "scissor lift", "cherry picker",
    "IPAF", "PASMA", "CITB", "SMSTS", "SSSTS", "CSCS", "NEBOSH", "IOSH",
]

_PROFILES = {
    "safety": _SAFETY,
}

# Email domain -> profile. Lower case.
_DOMAINS = {
    "ftc-ss.com": "safety",
    "ftcss.co.uk": "safety",
}


def profile_for(email: str) -> str:
    """The profile name for an account email, or "" for none."""
    dom = (email or "").strip().lower().rpartition("@")[2]
    return _DOMAINS.get(dom, "")


def terms_for(email: str) -> List[str]:
    """Every profile term for this account: its company's industry terms, then
    BrightLink's product names. Empty while signed out: a profile is a company
    fact, and an anonymous install has no company."""
    if not (email or "").strip():
        return []
    out = list(_PROFILES.get(profile_for(email), []))
    out += [t for t in _BRIGHTLINK_PRODUCTS if t not in out]
    return out
