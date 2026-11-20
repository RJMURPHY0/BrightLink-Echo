"""
Words people in each line of work say, so Echo writes them right first time.

The user ticks what they do (Settings > Vocabulary > Your work). Each pack is a
reviewed list of that job's terms. A pack is used two ways, and never more:

* Casing: a term spelt with capitals that is never an ordinary English word
  ("RIDDOR", "COSHH", "EBITDA", "HubSpot") is written that way wherever it is
  said. Everything else in a pack is never rewritten by a rule.
* The AI accuracy check: the whole pack, plus what the user says they do, is
  given to the check so it can pick the right word from the sentence
  ("the risk assessment and method statement" over "the risk assessment and
  method statements" is not its job; "rams" -> "RAMS" in a site context is).

Packs never reach a decoder prompt (only human-typed vocabulary may; see
.claude/rules/transcription-pipeline.md) and never the phonetic fuzzy pass,
whose false matches grow with list size.
"""

import re

import brand

# id -> (label, terms). Order is the order shown in Settings.
PACKS = {
    "software": ("Software and IT", [
        "API", "APIs", "SDK", "CLI", "UI", "UX", "SaaS", "PaaS", "IaaS", "DevOps",
        "CI/CD", "GitHub", "GitLab", "Bitbucket", "Jira", "Confluence", "Docker",
        "Kubernetes", "AWS", "Azure", "GCP", "Supabase", "Vercel", "Netlify",
        "Cloudflare", "PostgreSQL", "MySQL", "MongoDB", "Redis", "GraphQL",
        "REST", "JSON", "YAML", "OAuth", "SSO", "JWT", "MFA", "TypeScript",
        "JavaScript", "Python", "React", "Next.js", "Node.js", "Tailwind",
        "localhost", "repo", "pull request", "merge conflict", "staging",
        "production", "deploy", "rollback", "hotfix", "regression", "endpoint",
        "webhook", "middleware", "backend", "frontend", "full stack", "refactor",
        "linting", "unit test", "end-to-end test", "Playwright", "Vitest",
        "npm", "pnpm", "Bun", "Vite", "ESLint", "VS Code", "Cursor", "Claude Code",
        "Codex", "ChatGPT", "Claude", "Anthropic", "OpenAI", "Gemini", "LLM",
        "RAG", "embedding", "vector database", "MCP", "prompt", "token",
        "context window", "agent", "subagent", "n8n", "Zapier", "Make.com",
        "RLS", "SQL", "migration", "schema", "cron job", "Sentry", "uptime",
        "latency", "SLA", "GDPR", "ISO 27001", "SOC 2", "penetration test",
    ]),
    "sales": ("Sales and CRM", [
        "CRM", "HubSpot", "Salesforce", "Pipedrive", "LinkedIn", "Sales Navigator",
        "Apollo.io", "Lusha", "ZoomInfo", "Gong", "Outreach", "Calendly",
        "pipeline", "deal stage", "lead", "prospect", "MQL", "SQL", "SDR", "BDR",
        "AE", "account executive", "ICP", "persona", "cold call", "cold email",
        "follow-up", "sequence", "cadence", "discovery call", "demo", "proposal",
        "quote", "RFP", "RFQ", "tender", "procurement", "decision maker",
        "champion", "objection", "upsell", "cross-sell", "renewal", "churn",
        "MRR", "ARR", "ACV", "LTV", "CAC", "quota", "forecast", "win rate",
        "close rate", "conversion rate", "commission", "B2B", "B2C", "KPI",
        "KPIs", "ROI", "USP", "value proposition", "case study", "testimonial",
        "warm intro", "referral", "account-based marketing", "ABM", "NDA",
        "MSA", "SOW", "T&Cs", "onboarding", "handover", "QBR",
    ]),
    "marketing": ("Marketing", [
        "SEO", "SEM", "PPC", "CPC", "CPM", "CTR", "CPA", "ROAS", "CRO", "UTM",
        "Google Ads", "Google Analytics", "GA4", "Search Console", "Meta Ads",
        "LinkedIn Ads", "TikTok", "Instagram", "Facebook", "YouTube", "X",
        "Mailchimp", "Klaviyo", "HubSpot", "Canva", "Figma", "Hootsuite",
        "Buffer", "Later", "Semrush", "Ahrefs", "WordPress", "Webflow", "Wix",
        "Shopify", "landing page", "lead magnet", "funnel", "top of funnel",
        "retargeting", "lookalike audience", "A/B test", "copywriting",
        "call to action", "CTA", "brand guidelines", "tone of voice",
        "content calendar", "evergreen content", "thought leadership",
        "influencer", "UGC", "engagement rate", "impressions", "reach",
        "open rate", "click-through rate", "unsubscribe", "newsletter",
        "press release", "PR", "go-to-market", "GTM", "positioning",
        "persona", "B2B", "B2C", "KPI", "ROI", "omnichannel", "attribution",
    ]),
    "safety": ("Health and safety", [
        "HSE", "RIDDOR", "COSHH", "PUWER", "LOLER", "DSE", "PPE", "RPE",
        "LEV", "RAMS", "risk assessment", "method statement", "permit to work",
        "toolbox talk", "near miss", "safety observation", "incident report",
        "root cause", "CDM", "principal designer", "principal contractor",
        "F10", "CSCS", "CPCS", "IPAF", "PASMA", "SSSTS", "SMSTS", "NEBOSH",
        "IOSH", "ISO 45001", "ISO 14001", "ISO 9001", "SafeContractor",
        "CHAS", "Constructionline", "SSIP", "fire risk assessment", "PAT testing",
        "EICR", "asbestos survey", "legionella", "HAVS", "noise assessment",
        "manual handling", "working at height", "confined space", "hot works",
        "lone working", "first aider", "AED", "fire marshal", "evacuation",
        "audit", "inspection", "competent person", "safe system of work",
        "hierarchy of control", "Health and Safety at Work Act",
        "Management Regulations", "enforcement notice", "improvement notice",
        "prohibition notice", "HSG65", "CAA", "accident book",
    ]),
    "finance": ("Finance and accounting", [
        "HMRC", "VAT", "PAYE", "NI", "national insurance", "corporation tax",
        "self assessment", "Making Tax Digital", "MTD", "Companies House",
        "confirmation statement", "Xero", "QuickBooks", "Sage", "FreeAgent",
        "Dext", "Stripe", "GoCardless", "invoice", "credit note", "purchase order",
        "PO", "accounts payable", "accounts receivable", "AP", "AR",
        "balance sheet", "P&L", "profit and loss", "cash flow", "EBITDA",
        "gross margin", "net margin", "accruals", "prepayments", "depreciation",
        "amortisation", "reconciliation", "bank rec", "month end", "year end",
        "audit", "budget", "forecast", "variance", "CFO", "FD", "ACCA", "ACA",
        "CIMA", "IFRS", "FRS 102", "R&D tax credits", "dividends", "director's loan",
        "payroll", "pension", "auto-enrolment", "P60", "P45", "P11D", "BACS",
        "CHAPS", "IBAN", "sort code", "cost centre", "capex", "opex", "ROI",
        "KPI", "working capital", "aged debtors", "write-off",
    ]),
    "legal": ("Legal", [
        "solicitor", "barrister", "counsel", "KC", "paralegal", "SRA",
        "contract", "clause", "schedule", "addendum", "indemnity", "liability",
        "warranty", "force majeure", "termination", "NDA", "MSA", "SLA", "DPA",
        "GDPR", "UK GDPR", "ICO", "data subject", "subject access request",
        "SAR", "lawful basis", "legitimate interest", "consent", "processor",
        "controller", "sub-processor", "IP", "intellectual property",
        "trade mark", "copyright", "patent", "IPO", "licence", "litigation",
        "claimant", "defendant", "tribunal", "employment tribunal", "ACAS",
        "settlement agreement", "without prejudice", "disclosure", "witness statement",
        "conveyancing", "completion", "exchange of contracts", "Land Registry",
        "lease", "heads of terms", "due diligence", "shareholders' agreement",
        "articles of association", "Companies House", "director", "PSC",
        "power of attorney", "probate", "executor", "affidavit", "statutory declaration",
        "precedent", "jurisdiction", "governing law", "arbitration", "mediation",
    ]),
    "healthcare": ("Healthcare", [
        "NHS", "GP", "A&E", "ICU", "ITU", "CQC", "NICE", "ICB", "PCN", "HCA",
        "ANP", "ACP", "consultant", "registrar", "FY1", "FY2", "SHO", "ward round",
        "handover", "discharge summary", "referral", "triage", "obs", "NEWS2",
        "blood pressure", "BP", "ECG", "MRI", "CT scan", "X-ray", "ultrasound",
        "FBC", "U&Es", "LFTs", "CRP", "HbA1c", "eGFR", "INR", "prescription",
        "BNF", "dose", "mg", "mcg", "IV", "IM", "PRN", "BD", "TDS", "QDS",
        "safeguarding", "DoLS", "capacity assessment", "care plan", "EMIS",
        "SystmOne", "EPR", "SNOMED", "clinic", "outpatient", "inpatient",
        "comorbidity", "diagnosis", "differential diagnosis", "prognosis",
        "palliative", "physiotherapy", "occupational therapy", "mental health",
        "CAMHS", "IAPT", "dementia", "diabetes", "hypertension", "COPD", "asthma",
        "sepsis", "Datix", "clinical governance", "audit",
    ]),
    "recruitment": ("Recruitment and HR", [
        "CV", "candidate", "job spec", "job description", "shortlist",
        "interview", "first stage", "second stage", "offer letter",
        "counter-offer", "notice period", "start date", "onboarding",
        "probation", "right to work", "DBS check", "references", "contract of employment",
        "permanent", "contract", "temp", "temp to perm", "day rate", "IR35",
        "umbrella company", "PAYE", "agency worker", "AWR", "placement fee",
        "retained search", "contingent", "headhunting", "talent pool",
        "LinkedIn Recruiter", "Indeed", "Reed", "Totaljobs", "CV-Library",
        "ATS", "Bullhorn", "Workable", "Greenhouse", "BambooHR", "HiBob",
        "Personio", "HRIS", "payroll", "holiday entitlement", "sick pay", "SSP",
        "maternity leave", "paternity leave", "flexible working", "appraisal",
        "performance review", "PIP", "disciplinary", "grievance", "ACAS",
        "redundancy", "TUPE", "employee engagement", "retention", "attrition",
        "L&D", "EDI", "DEI", "CIPD",
    ]),
    "property": ("Property and lettings", [
        "Rightmove", "Zoopla", "OnTheMarket", "EPC", "valuation", "viewing",
        "offer", "sale agreed", "under offer", "chain", "completion",
        "exchange", "conveyancer", "solicitor", "survey", "HomeBuyer Report",
        "RICS", "mortgage", "mortgage in principle", "LTV", "remortgage",
        "buy-to-let", "freehold", "leasehold", "ground rent", "service charge",
        "stamp duty", "SDLT", "Land Registry", "title deeds", "lettings",
        "tenancy agreement", "AST", "deposit", "deposit protection", "DPS",
        "TDS", "inventory", "check-in", "check-out", "landlord", "tenant",
        "HMO", "Section 21", "Section 8", "gas safety certificate", "EICR",
        "Right to Rent", "rental yield", "void period", "block management",
        "planning permission", "permitted development", "building regs",
        "new build", "off-plan", "auction", "probate sale", "detached",
        "semi-detached", "terraced", "bungalow", "maisonette",
    ]),
    "construction": ("Construction and trades", [
        "RAMS", "CDM", "CSCS", "site induction", "toolbox talk", "permit to work",
        "principal contractor", "subcontractor", "main contractor", "QS",
        "quantity surveyor", "bill of quantities", "BoQ", "variation",
        "valuation", "retention", "practical completion", "snagging",
        "JCT", "NEC", "NEC4", "CIS", "scope of works", "spec", "drawings",
        "RFI", "programme", "critical path", "Gantt chart", "groundworks",
        "foundations", "steelwork", "scaffolding", "MEWP", "IPAF", "PASMA",
        "first fix", "second fix", "plasterboard", "screed", "DPC", "DPM",
        "joists", "lintel", "RSJ", "load-bearing", "Part L", "Part P",
        "building control", "building regs", "planning", "NICEIC", "Gas Safe",
        "18th Edition", "consumer unit", "EICR", "BIM", "CAD", "AutoCAD",
        "Revit", "site manager", "foreman", "labourer", "plant hire",
        "skip hire", "make good", "handover", "O&M manual",
    ]),
    "education": ("Education and training", [
        "Ofsted", "SLT", "SENCO", "SEN", "SEND", "EHCP", "DSL", "safeguarding",
        "KS1", "KS2", "KS3", "KS4", "GCSE", "A level", "BTEC", "T Level",
        "NVQ", "apprenticeship", "end-point assessment", "EPA", "EPAO",
        "Ofqual", "ESFA", "Skills England", "functional skills", "portfolio",
        "evidence", "assessor", "IQA", "EQA", "learning outcomes",
        "scheme of work", "lesson plan", "differentiation", "formative assessment",
        "summative assessment", "CPD", "INSET", "PGCE", "QTS", "ECT",
        "pastoral", "attendance", "exclusion", "Pupil Premium", "MAT",
        "academy trust", "governors", "curriculum", "Bloom's taxonomy",
        "Google Classroom", "Microsoft Teams", "Moodle", "LMS", "e-learning",
        "blended learning", "learner", "cohort", "induction",
        "sixth form", "mock exams", "parents' evening", "teaching assistant",
        "Head of Year", "behaviour policy", "marking", "UCAS",
    ]),
    "business": ("Business and operations", [
        "Ltd", "PLC", "LLP", "director", "shareholder", "co-founder", "CEO",
        "COO", "CFO", "CTO", "MD", "board meeting", "AGM", "Companies House",
        "HMRC", "VAT", "PAYE", "corporation tax", "cash flow", "P&L",
        "budget", "forecast", "KPI", "KPIs", "OKR", "OKRs", "ROI", "USP",
        "B2B", "B2C", "SaaS", "SLA", "NDA", "GDPR", "ISO 9001", "trade mark",
        "supplier", "invoice", "purchase order", "procurement", "tender",
        "stakeholder", "roadmap", "strategy", "operations", "SOP", "process",
        "workflow", "automation", "CRM", "ERP", "Xero", "QuickBooks",
        "Microsoft 365", "Microsoft Teams", "SharePoint", "OneDrive", "Outlook",
        "Google Workspace", "Gmail", "Slack", "Zoom", "Notion", "Asana",
        "Trello", "Monday.com", "ChatGPT", "Claude", "Copilot", "LinkedIn",
        "Canva", "Stripe", "Shopify", "headcount", "hiring", "onboarding",
        "pricing", "margin", "turnover", "revenue", "profit", "growth",
    ]),
}

ROLE_IDS = tuple(PACKS)

# Stored when the user unticks every job (an empty list means "never chose").
NONE_CHOSEN = "none"

# What a BrightLink team account gets until they tick their own.
BRIGHTLINK_TEAM_DEFAULT = ("software", "sales", "safety", "business")

# Our own product and company names, given to every BrightLink team account.
BRIGHTLINK_NAMES = [
    "BrightLink", brand.PRODUCT_NAME, "BrightLink Notetaker", "BrightLink Design",
    "BrightLink CRM", "FTC Safety Solutions", "FTC", "ClaudeOS", "Agentic OS",
    "Toolbox", "Key Drop", "Hermes", "OmniRoute", "Pinecone", "Obsidian",
    "Supabase", "Vercel", "OpenRouter", "Higgsfield", "Lovable", "Skywork",
    "Apify", "Firecrawl", "Resend", "Twilio", "Recall", "Parakeet",
    "Wispr Flow", "Glaido",
]


def label(role_id: str) -> str:
    return PACKS.get(role_id, (role_id, []))[0]


def _team_account(email: str) -> bool:
    e = (email or "").strip().lower()
    return e.endswith("@brightlink.io") or e.endswith("@ftc-ss.com")


def _account(email: str) -> str:
    import vocab_store
    return vocab_store.account_key(email)


def _mine(config, field_name: str, email: str):
    """This account's value of a per-account work field, or None."""
    v = getattr(config, field_name, None)
    if isinstance(v, dict):
        return v.get(_account(email))
    return None


def with_mine(config, field_name: str, email: str, value) -> dict:
    """A copy of the field's per-account dict with this account's value set,
    ready to hand to the settings change handler."""
    v = getattr(config, field_name, None)
    out = dict(v) if isinstance(v, dict) else {}
    out[_account(email)] = value
    return out


def effective_roles(config, email: str = "") -> list:
    """The user's ticked jobs; a BrightLink team account that ticked none gets
    the team default, everyone else nothing."""
    raw = list(_mine(config, "work_roles", email) or [])
    if raw:
        # Anything stored means the user chose; NONE_CHOSEN is "I ticked
        # nothing", which must not bring the team default back.
        return [r for r in raw if r in PACKS]
    if _team_account(email):
        return list(BRIGHTLINK_TEAM_DEFAULT)
    return []


def terms_for(roles, email: str = "") -> list:
    """Every term in the given packs, deduplicated, first spelling wins."""
    seen, out = set(), []
    extra = BRIGHTLINK_NAMES if _team_account(email) else []
    for r in list(roles or []):
        for t in PACKS.get(r, ("", []))[1]:
            k = t.lower()
            if k not in seen:
                seen.add(k)
                out.append(t)
    for t in extra:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


# ── Casing ───────────────────────────────────────────────────────────────────
#
# Only single words written with capitals that are not themselves an English
# word in lower case. "Sage", "Reed", "Later", "Buffer", "Outreach", "Cursor",
# "Recall", "Toolbox" are real words: casing them would rewrite prose. Acronyms
# that spell a common word ("PIP", "MAT", "CAD", "PO", "AR", "AP", "IP", "PR",
# "AE", "IM", "IV", "BD", "NI", "X", "EPA", "ICO", "GP", "BP", "KC") are left
# to the AI check, which can read the sentence.
_NOT_CASED = {
    "sage", "reed", "later", "buffer", "outreach", "cursor", "recall", "toolbox",
    "gong", "indeed", "chain", "survey", "offer", "audit", "spec", "process",
    "hermes", "obsidian", "pinecone", "codex", "claude", "gemini", "lovable",
    "bun", "react", "python", "rest", "agent", "x", "pip", "mat", "cad", "po",
    "ar", "ap", "ip", "pr", "ae", "im", "iv", "bd", "ni", "epa", "ico", "gp",
    "bp", "kc", "md", "obs", "tds", "aws", "it", "ui", "ux", "ma", "mg",
    "ast", "dps", "qs", "ssp", "ats", "lms", "dsl", "ect", "sen",
    "send", "nice", "chas", "ids", "lev", "glaido",
    "parakeet", "resend", "ftc",
    # Brands that are also English words.
    "azure", "tailwind", "sentry", "bullhorn", "workable", "greenhouse",
    "stripe", "notion", "copilot", "slack", "zoom", "outlook", "confluence",
    "playwright", "chaps", "inset", "sow", "rag", "rams", "vat", "cis",
    "docker", "later", "make.com",
}


def _casing_pairs(terms) -> list:
    out = []
    for t in terms:
        if " " in t or not re.search(r"[A-Z]", t):
            continue
        if t.lower() in _NOT_CASED or len(t) < 3:
            continue
        if t == t.capitalize() and t.isalpha():
            # "Rightmove", "Zoopla": a plain capitalised word. Safe only when it
            # is not an English word; the packs list brands only, and the list
            # above holds the ones that are also words.
            pass
        out.append(t)
    return out


_CASE_CACHE: dict = {}


def apply_job_casing(text: str, roles, email: str = "") -> str:
    """Write the packs' distinctive terms with their own capitals."""
    if not text or not roles and not _team_account(email):
        return text
    key = (tuple(roles or ()), _team_account(email))
    rx = _CASE_CACHE.get(key)
    if rx is None:
        pairs = _casing_pairs(terms_for(roles, email))
        canon = {p.lower(): p for p in pairs}
        if not canon:
            _CASE_CACHE[key] = False
            return text
        alt = "|".join(re.escape(k) for k in sorted(canon, key=len, reverse=True))
        rx = (re.compile(rf"(?<![\w./@\\-])(?:{alt})(?![\w@]|[./\\-]\w)",
                         re.IGNORECASE), canon)
        _CASE_CACHE[key] = rx
    if rx is False:
        return text
    pattern, canon = rx
    return pattern.sub(lambda m: canon.get(m.group(0).lower(), m.group(0)), text)


def job_line(config, email: str = "") -> str:
    """One line for the AI accuracy check saying what the speaker does, or ""
    when nothing is known. The pack's words go in vocab_context.block, which
    keeps only the ones that bear on the text."""
    roles = effective_roles(config, email)
    desc = " ".join(str(_mine(config, "work_description", email) or "").split())[:300]
    parts = []
    if roles:
        parts.append("The speaker works in: " + ", ".join(label(r) for r in roles) + ".")
    if desc:
        parts.append(f"In their own words: {desc}")
    return " ".join(parts)
