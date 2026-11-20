"""
Everyday tool and brand names, written the way the companies spell them.

    "chat gbt"            -> "ChatGPT"
    "microsoft teams"     -> "Microsoft Teams"
    "share point"         -> "SharePoint"
    "local host"          -> "localhost"
    "localhost 8080"      -> "localhost:8080"
    "whisper flow"        -> "Wispr Flow"
    "clawed code"         -> "Claude Code"

The rule that keeps this safe in ordinary prose: a spelling is only rewritten
when it can't be an ordinary English phrase. A word that is also English
("teams", "zoom", "slack", "outlook", "power point" for a socket, "sales force"
for a sales team, "cloud", "claw") is cased only next to a word that makes it
the product ("a Teams call", "on Slack", "a PowerPoint deck"), or not at all.
The sound-alikes that need the meaning of the sentence ("clawed" for Claude,
"homies" for Hermes) are the AI accuracy check's job, which is given the same
names (see `names_for_prompt`).

Runs inside apply_spoken_commands after the AI model names (tech_terms), so
every path (inject, upgrade, history) sees the same text. Never touches a word
glued to a dot, slash or @, so "brightlink.io" and "github.com/x" stay as typed.
"""

import re

import brand

_S = r"[ \t]+"
_SP = r"[ \t]?"            # optional space: "share point" and "sharepoint"
# Not part of a domain, path, handle or longer word on either side.
_PRE = r"(?<![\w./@\\-])"
_POST = r"(?![\w@]|[./\\-]\w)"

# (pattern, canonical). The pattern matches the name only; a context word it
# needs goes in a `ctx` group (kept as spoken) before or after it.
_NAMES = [
    # AI tools the model-name table (tech_terms) doesn't spell yet.
    (r"chat[ \t-]?g[ \t]?[bp][ \t]?t", "ChatGPT"),     # "chat GBT", "ChatGBT", "chat g p t"
    (r"(?:claude|clawed|clawd|claud)[ \t]code", "Claude Code"),
    (r"claude[ \t]ai", "Claude AI"),
    (r"(?:wispr|whisper)[ \t]?flow", "Wispr Flow"),
    (r"notebook[ \t]?lm", "NotebookLM"),
    (r"openrouter", "OpenRouter"),        # "open router settings"
    (r"perplexity[ \t]ai", "Perplexity AI"),
    (r"(?:github|git[ \t]hub)[ \t]co[ \t-]?pilot", "GitHub Copilot"),
    (r"microsoft[ \t]co[ \t-]?pilot", "Microsoft Copilot"),
    (r"n[ \t]eight[ \t]n|n8n", "n8n"),
    # Microsoft.
    (r"microsoft[ \t]teams", "Microsoft Teams"),
    (r"ms[ \t]teams", "MS Teams"),
    (r"teams(?=[ \t](?:call|calls|meeting|meetings|chat|chats|channel|channels|message|messages|link|invite|app))", "Teams"),
    (r"(?P<ctx>\b(?:on|via|over|through)[ \t])teams(?=[ \t]*(?:[.,!?;:]|$))", "Teams"),
    (r"share[ \t]?point", "SharePoint"),
    (r"onedrive", "OneDrive"),
    (r"(?P<ctx>\b(?:my|our|your|their|microsoft)[ \t])one[ \t]drive", "OneDrive"),
    (r"powerpoint", "PowerPoint"),
    (r"power[ \t]point(?=[ \t](?:presentation|presentations|slide|slides|deck|decks|file|template))", "PowerPoint"),
    (r"microsoft[ \t]outlook", "Microsoft Outlook"),
    (r"outlook(?=[ \t](?:inbox|calendar|email|emails|account|invite|signature|folder))", "Outlook"),
    (r"microsoft[ \t]excel", "Microsoft Excel"),
    (r"excel(?=[ \t](?:spreadsheet|spreadsheets|sheet|sheets|file|files|formula|formulas|workbook|template))", "Excel"),
    (r"microsoft[ \t]word", "Microsoft Word"),
    (r"word(?=[ \t](?:doc|docs|document|documents)\b)", "Word"),
    (r"microsoft[ \t](?:three[ \t]sixty[ \t]five|365)", "Microsoft 365"),
    (r"office[ \t](?:three[ \t]sixty[ \t]five|365)", "Office 365"),
    # Google.
    (r"g[ \t]?mail", "Gmail"),
    (r"google[ \t](?P<g>meet|drive|docs|doc|sheets|sheet|slides|calendar|analytics|ads|maps|workspace|chrome|cloud|forms|search[ \t]console|tag[ \t]manager|business[ \t]profile)", None),
    (r"you[ \t]?tube", "YouTube"),
    # Social and messaging.
    (r"linkedin", "LinkedIn"),
    (r"(?P<ctx>\b(?:on|via|from|my|our|your|his|her|their)[ \t])linked[ \t]in(?![ \t]+(?:to|with|by)\b)", "LinkedIn"),
    (r"linked[ \t]in(?=[ \t](?:post|posts|profile|profiles|message|messages|connection|connections|page|account|ads|premium|inbox|sales[ \t]navigator|learning))", "LinkedIn"),
    (r"whats[ \t]?app|what's[ \t]app(?=[ \t](?:group|message|messages|chat|call))", "WhatsApp"),
    (r"tik[ \t]?tok", "TikTok"),
    (r"facebook", "Facebook"),
    (r"instagram", "Instagram"),
    (r"(?P<ctx>\b(?:on|via|in)[ \t])slack(?=[ \t]*(?:[.,!?;:]|$))", "Slack"),
    (r"slack(?=[ \t](?:channel|channels|message|messages|workspace|thread|threads|huddle|dm|dms))", "Slack"),
    (r"zoom(?=[ \t](?:call|calls|meeting|meetings|link|invite|webinar))", "Zoom"),
    (r"(?P<ctx>\b(?:on|via|over)[ \t])zoom(?=[ \t]*(?:[.,!?;:]|$))", "Zoom"),
    (r"facetime", "FaceTime"),
    (r"imessage", "iMessage"),
    # Business software.
    (r"hub[ \t]?spot", "HubSpot"),
    (r"salesforce", "Salesforce"),
    (r"pipe[ \t]?drive", "Pipedrive"),
    (r"quickbooks", "QuickBooks"),        # "quick books to read"
    (r"xero", "Xero"),
    (r"docu[ \t]?sign", "DocuSign"),
    (r"mail[ \t]?chimp", "Mailchimp"),
    (r"zapier", "Zapier"),
    (r"air[ \t]?table", "Airtable"),
    (r"zen[ \t]?desk", "Zendesk"),
    (r"freshdesk", "Freshdesk"),          # "a fresh desk"
    (r"survey[ \t]?monkey", "SurveyMonkey"),
    (r"typeform", "Typeform"),            # "type form A" is a sentence
    (r"calendly", "Calendly"),
    (r"canva", "Canva"),
    (r"figma", "Figma"),
    (r"trello", "Trello"),
    (r"jira", "Jira"),
    (r"miro(?=[ \t](?:board|boards))", "Miro"),
    (r"dropbox", "Dropbox"),
    (r"shopify", "Shopify"),
    (r"word[ \t]?press", "WordPress"),
    (r"pay[ \t]?pal", "PayPal"),
    (r"monday\.com|monday[ \t]dot[ \t]com", "monday.com"),
    (r"event[ \t]?brite", "Eventbrite"),
    (r"intercom(?=[ \t](?:chat|inbox|message|messages))", "Intercom"),
    (r"apollo\.io|apollo[ \t]dot[ \t]io", "Apollo.io"),
    (r"companies[ \t]house", "Companies House"),
    (r"hmrc", "HMRC"),
    # Devices.
    (r"iphone", "iPhone"),
    (r"i[ \t]phone(?=[ \t](?:pro|max|mini|plus|app|apps|screen))", "iPhone"),
    (r"ipad", "iPad"),
    (r"mac[ \t]?book", "MacBook"),
    (r"airpods|air[ \t]pods", "AirPods"),
    # Developer terms people say aloud.
    (r"git[ \t]?hub", "GitHub"),
    (r"git[ \t]?lab", "GitLab"),
    (r"java[ \t]?script", "JavaScript"),
    (r"type[ \t]?script", "TypeScript"),
    (r"postgres(?:ql)?", None),
    (r"supabase|supa[ \t]base", "Supabase"),
    (r"vercel", "Vercel"),
    # "local host" is also a person ("our local host welcomed us"): only next
    # to a word that makes it the address. The AI check has the rest.
    (r"local[ \t]host(?=[ \t]*(?:[:?!,]|\.(?!\w)|$)|[ \t]+(?:or|and|so|that|which|server|url|address|page|link|port|instance|preview|build|site|app|\d|(?:zero|one|two|three|four|five|six|seven|eight|nine)\b))", "localhost"),
    (r"node[ \t]?js|node[ \t]dot[ \t]js", "Node.js"),
    (r"next[ \t]?js|next[ \t]dot[ \t]js", "Next.js"),
    (r"vs[ \t]code|v[ \t]s[ \t]code", "VS Code"),
    # Letters said one by one.
    (r"a[ \t]p[ \t]i", "API"),
    (r"c[ \t]r[ \t]m", "CRM"),
    (r"u[ \t]r[ \t]l", "URL"),
    (r"s[ \t]e[ \t]o", "SEO"),
    (r"k[ \t]p[ \t]i", "KPI"),
    (r"kpis", "KPIs"),
    (r"saas", "SaaS"),
    (r"b2b|b[ \t]two[ \t]b", "B2B"),
    (r"b2c|b[ \t]two[ \t]c", "B2C"),
    # Our own products: written "BrightLink" (capital L) by brand rule.
    (r"brightlink", "BrightLink"),
    (r"bright[ \t]link", "BrightLink"),
]


def _canon_google(m: "re.Match") -> str:
    tail = re.sub(r"[ \t]+", " ", m.group("g")).split(" ")
    return "Google " + " ".join(w.capitalize() for w in tail)


def _canon_postgres(m: "re.Match") -> str:
    return "PostgreSQL" if m.group(0).lower().endswith("ql") else "Postgres"


_SPECIAL = {
    "google": _canon_google,
    "postgres": _canon_postgres,
}


def _compile():
    out = []
    for pat, canon in _NAMES:
        rx = re.compile(_PRE + "(?:" + pat + ")" + _POST, re.IGNORECASE)
        if canon is None:
            key = "google" if pat.startswith("google") else "postgres"
            fn = _SPECIAL[key]
        else:
            fn = canon
        out.append((rx, fn))
    return out


_RULES = _compile()

# "BrightLink Notetaker" is the product; "notetaker" alone is an ordinary word.
_NOTETAKER = re.compile(r"(?<=BrightLink )note[ \t]?taker\b", re.IGNORECASE)
_ECHO = re.compile(r"(?<=BrightLink )echo\b", re.IGNORECASE)

# "localhost 8080", "localhost eight zero eight zero", "localhost port 3000".
_DIGIT = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
          "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
          "nine": "9"}
_DW = "|".join(_DIGIT)
_LOCALHOST_PORT = re.compile(
    rf"\blocalhost(?:{_S}port)?{_S}(?P<port>\d{{2,5}}|(?:{_DW})(?:(?:{_S}|-)(?:{_DW})){{1,4}})\b",
    re.IGNORECASE)


# Said the other way round: "run it on eight zero eight zero localhost".
_PORT_LOCALHOST = re.compile(
    rf"\b(?P<port>\d{{4,5}}|(?:{_DW})(?:(?:{_S}|-)(?:{_DW})){{3,4}}){_S}localhost\b",
    re.IGNORECASE)


def _sub_port(m: "re.Match") -> str:
    raw = m.group("port")
    if raw.isdigit():
        return f"localhost:{raw}"
    digits = "".join(_DIGIT[w.lower()] for w in re.findall(rf"{_DW}", raw, re.IGNORECASE))
    return f"localhost:{digits}" if 2 <= len(digits) <= 5 else m.group(0)


def _replace(m: "re.Match", fn) -> str:
    ctx = m.groupdict().get("ctx") or ""
    body = fn(m) if callable(fn) else fn
    return ctx + body


def apply_common_terms(text: str) -> str:
    """Write everyday tool and brand names the way they are spelt."""
    if not text:
        return text
    out = text
    for rx, fn in _RULES:
        out = rx.sub(lambda m, f=fn: _replace(m, f), out)
    out = _NOTETAKER.sub("Notetaker", out)
    out = _ECHO.sub("Echo", out)
    out = _LOCALHOST_PORT.sub(_sub_port, out)
    out = _PORT_LOCALHOST.sub(_sub_port, out)
    return out


# Names whose mishearings need the sentence's meaning to fix. Handed to the AI
# accuracy check so it knows them; never rewritten by a rule here.
CONTEXT_NAMES = {
    "Claude": ["cloud", "claw", "clawed", "clod", "clawd"],
    "ChatGPT": ["chat GBT", "chat CPT"],
    "Anthropic": ["in tropic", "anthropik"],
    "OpenAI": ["open AI", "open I"],
    "Microsoft Teams": ["teams"],
    "Hermes": ["homies", "her means", "hermies"],
    "Pinecone": ["pine cone"],
    "Codex": ["codecs", "cortex"],
    "Gemini": ["Jemini"],
    "Wispr Flow": ["whisper flow"],
    "Slack": ["slack"],
    "Notion": ["notion"],
    "Zoom": ["zoom"],
}


def names_for_prompt() -> list:
    """Every canonical name above, for the AI accuracy check's name list."""
    names = set(CONTEXT_NAMES)
    for _pat, canon in _NAMES:
        if isinstance(canon, str):
            names.add(canon)
    names.update({"Google Meet", "Google Drive", "Google Docs", "Google Sheets",
                  "PostgreSQL", "Postgres", brand.PRODUCT_NAME, "BrightLink Notetaker"})
    return sorted(names)
