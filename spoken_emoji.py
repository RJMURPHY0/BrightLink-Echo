"""
Spoken emoji: "<name> emoji" becomes the emoji itself.

    "that's hilarious laughing face emoji"  -> "that's hilarious 😂"
    "great work star emoji"                 -> "great work ⭐"
    "see you then thumbs up emoji"          -> "see you then 👍"

The word "emoji" is the trigger, so ordinary speech is never touched: a name
only turns into a picture when it is followed by "emoji" (or "emojis").

Names are resolved from the words just before the trigger, longest first (up
to _MAX_WORDS words), so "a big laughing face emoji" picks "laughing face" and
leaves "a big" as spoken. Each candidate is tried against:

  1. _ALIASES: the everyday names people actually say ("laughing face",
     "smiley", "heart", "star"), mapped to the emoji they mean. These win over
     the official name when the two disagree ("smiling face" is the old
     text-style U+263A officially; people mean 😊).
  2. emoji_names.py: Unicode's official emoji list (CLDR names, the ones
     Windows' emoji panel shows), every emoji including flags ("united
     kingdom flag"), skin tones ("thumbs up medium skin tone"), keycaps and
     joined emoji ("man technologist"). Also tried with " face" added
     ("thinking" -> thinking face). Loaded on the first spoken emoji only.
  3. The Unicode character name ("heavy dollar sign"), also with " face" and
     " sign" added.

Whatever is found must be on the official list, so a symbol that is not an
emoji ("letter a", U+1F5CE DOCUMENT) never comes out.

If nothing resolves, the text is left exactly as spoken ("I sent an emoji").
"""

import re
import unicodedata

_MAX_WORDS = 14   # longest official name: 13 words (mixed skin-tone couples)
_VS16 = "️"   # emoji presentation selector for BMP symbols (❤ -> ❤️)

# Everyday names -> emoji. Keys are lower case, single spaces.
_ALIASES = {
    "smiling": "😊",
    # faces
    "smiling face": "\U0001F60A", "smiley face": "\U0001F60A",
    "smiley": "\U0001F60A", "smile": "\U0001F60A", "happy face": "\U0001F60A",
    "happy": "\U0001F60A", "blushing face": "\U0001F60A", "blush": "\U0001F60A",
    "slightly smiling face": "\U0001F642",
    "grinning face": "\U0001F600", "grin": "\U0001F600", "big smile": "\U0001F603",
    "laughing face": "\U0001F602", "laughing": "\U0001F602", "laugh": "\U0001F602",
    "crying laughing": "\U0001F602", "crying laughing face": "\U0001F602",
    "tears of joy": "\U0001F602", "lol": "\U0001F602",
    "rolling on the floor laughing": "\U0001F923", "rofl": "\U0001F923",
    "wink": "\U0001F609", "winking": "\U0001F609", "winky face": "\U0001F609",
    "sad face": "\U0001F622", "sad": "\U0001F622", "crying face": "\U0001F622",
    "crying": "\U0001F622", "sobbing": "\U0001F62D", "sobbing face": "\U0001F62D",
    "angry face": "\U0001F620", "angry": "\U0001F620", "cross face": "\U0001F620",
    "furious": "\U0001F621", "rage": "\U0001F621",
    "heart eyes": "\U0001F60D", "heart eyes face": "\U0001F60D",
    "in love": "\U0001F60D", "kiss": "\U0001F618", "kissing face": "\U0001F618",
    "blowing a kiss": "\U0001F618",
    "cool": "\U0001F60E", "cool face": "\U0001F60E", "sunglasses": "\U0001F60E",
    "sunglasses face": "\U0001F60E",
    "thinking": "\U0001F914", "thinking face": "\U0001F914", "hmm": "\U0001F914",
    "shocked": "\U0001F62E", "shocked face": "\U0001F62E",
    "surprised": "\U0001F62E", "surprised face": "\U0001F62E",
    "mind blown": "\U0001F92F", "exploding head": "\U0001F92F",
    "eye roll": "\U0001F644", "rolling eyes": "\U0001F644",
    "upside down face": "\U0001F643", "upside down": "\U0001F643",
    "tongue out": "\U0001F61B", "cheeky": "\U0001F61C", "cheeky face": "\U0001F61C",
    "sweat smile": "\U0001F605", "nervous": "\U0001F605", "awkward": "\U0001F605",
    "grimace": "\U0001F62C", "grimacing": "\U0001F62C", "grimacing face": "\U0001F62C",
    "neutral face": "\U0001F610", "straight face": "\U0001F610",
    "expressionless": "\U0001F611", "unamused": "\U0001F612",
    "sleepy": "\U0001F634", "sleeping": "\U0001F634", "sleeping face": "\U0001F634",
    "tired": "\U0001F62B", "sick": "\U0001F922", "sick face": "\U0001F922",
    "vomiting": "\U0001F92E", "puke": "\U0001F92E", "hot": "\U0001F975",
    "cold": "\U0001F976", "party face": "\U0001F973", "partying face": "\U0001F973",
    "celebrate": "\U0001F973", "hug": "\U0001F917", "hugging face": "\U0001F917",
    "shush": "\U0001F92B", "shushing face": "\U0001F92B", "zipped mouth": "\U0001F910",
    "facepalm": "\U0001F926", "face palm": "\U0001F926", "shrug": "\U0001F937",
    "pleading face": "\U0001F97A", "puppy eyes": "\U0001F97A",
    "halo": "\U0001F607", "angel": "\U0001F607", "devil": "\U0001F608",
    "smiling devil": "\U0001F608", "clown": "\U0001F921", "clown face": "\U0001F921",
    "skull": "\U0001F480", "dead": "\U0001F480", "ghost": "\U0001F47B",
    "alien": "\U0001F47D", "robot": "\U0001F916", "poo": "\U0001F4A9",
    "poop": "\U0001F4A9", "monkey": "\U0001F412", "see no evil": "\U0001F648",
    "see no evil monkey": "\U0001F648",
    # hands and people
    "thumbs up": "\U0001F44D", "thumb up": "\U0001F44D",
    "thumbs down": "\U0001F44E", "thumb down": "\U0001F44E",
    "clap": "\U0001F44F", "clapping": "\U0001F44F", "clapping hands": "\U0001F44F",
    "applause": "\U0001F44F", "wave": "\U0001F44B", "waving": "\U0001F44B",
    "waving hand": "\U0001F44B", "ok": "\U0001F44C", "okay": "\U0001F44C",
    "ok hand": "\U0001F44C", "okay hand": "\U0001F44C",
    "praying hands": "\U0001F64F", "pray": "\U0001F64F", "prayer": "\U0001F64F",
    "fingers crossed": "\U0001F91E", "crossed fingers": "\U0001F91E",
    "muscle": "\U0001F4AA", "flexed biceps": "\U0001F4AA", "strong": "\U0001F4AA",
    "flex": "\U0001F4AA", "raised hands": "\U0001F64C", "hands up": "\U0001F64C",
    "handshake": "\U0001F91D", "fist bump": "\U0001F44A", "punch": "\U0001F44A",
    "pointing up": "☝", "point up": "☝", "pointing right": "\U0001F449",
    "point right": "\U0001F449", "pointing left": "\U0001F448",
    "point left": "\U0001F448", "pointing down": "\U0001F447",
    "point down": "\U0001F447", "peace": "✌", "peace sign": "✌",
    "victory": "✌", "rock on": "\U0001F918", "call me": "\U0001F919",
    "writing hand": "✍", "eyes": "\U0001F440", "eye": "\U0001F441",
    "brain": "\U0001F9E0", "running": "\U0001F3C3", "runner": "\U0001F3C3",
    "dancing": "\U0001F483", "dancer": "\U0001F483",
    # hearts and symbols
    "heart": "❤", "red heart": "❤", "love heart": "❤",
    "broken heart": "\U0001F494", "orange heart": "\U0001F9E1",
    "yellow heart": "\U0001F49B", "green heart": "\U0001F49A",
    "blue heart": "\U0001F499", "purple heart": "\U0001F49C",
    "black heart": "\U0001F5A4", "white heart": "\U0001F90D",
    "pink heart": "\U0001FA77", "sparkling heart": "\U0001F496",
    "star": "⭐", "gold star": "⭐", "stars": "✨",
    "sparkles": "✨", "sparkle": "✨", "glowing star": "\U0001F31F",
    "shooting star": "\U0001F320", "fire": "\U0001F525", "flame": "\U0001F525",
    "lit": "\U0001F525", "hundred": "\U0001F4AF", "one hundred": "\U0001F4AF",
    "100": "\U0001F4AF", "hundred points": "\U0001F4AF",
    "tick": "✅", "check mark": "✅", "checkmark": "✅",
    "green tick": "✅", "check": "✅", "cross": "❌",
    "red cross": "❌", "x": "❌", "cross mark": "❌",
    "warning": "⚠", "warning sign": "⚠", "no entry": "⛔",
    "stop sign": "\U0001F6D1", "question mark": "❓", "question": "❓",
    "exclamation mark": "❗", "exclamation": "❗",
    "lightning": "⚡", "lightning bolt": "⚡", "zap": "⚡",
    "boom": "\U0001F4A5", "collision": "\U0001F4A5", "explosion": "\U0001F4A5",
    "sweat": "\U0001F4A6", "zzz": "\U0001F4A4", "light bulb": "\U0001F4A1",
    "lightbulb": "\U0001F4A1", "idea": "\U0001F4A1", "bell": "\U0001F514",
    "pin": "\U0001F4CC", "pushpin": "\U0001F4CC", "lock": "\U0001F512",
    "key": "\U0001F511", "link": "\U0001F517", "magnifying glass": "\U0001F50D",
    "search": "\U0001F50D", "recycle": "♻", "infinity": "♾",
    "up arrow": "⬆", "down arrow": "⬇", "right arrow": "➡",
    "left arrow": "⬅", "arrow": "➡", "green circle": "\U0001F7E2",
    "red circle": "\U0001F534", "yellow circle": "\U0001F7E1",
    "blue circle": "\U0001F535", "orange circle": "\U0001F7E0",
    "speech bubble": "\U0001F4AC", "thought bubble": "\U0001F4AD",
    # celebration and objects
    "party": "\U0001F389", "party popper": "\U0001F389", "tada": "\U0001F389",
    "confetti": "\U0001F38A", "balloon": "\U0001F388", "gift": "\U0001F381",
    "present": "\U0001F381", "birthday cake": "\U0001F382", "cake": "\U0001F370",
    "trophy": "\U0001F3C6", "medal": "\U0001F3C5", "gold medal": "\U0001F947",
    "crown": "\U0001F451", "rocket": "\U0001F680", "money": "\U0001F4B0",
    "money bag": "\U0001F4B0", "cash": "\U0001F4B5", "pound": "\U0001F4B7",
    "pound note": "\U0001F4B7", "dollar": "\U0001F4B5", "chart": "\U0001F4C8",
    "chart up": "\U0001F4C8", "graph": "\U0001F4C8", "chart down": "\U0001F4C9",
    "calendar": "\U0001F4C5", "clock": "\U0001F552", "alarm": "⏰",
    "hourglass": "⏳", "phone": "\U0001F4F1", "mobile": "\U0001F4F1",
    "laptop": "\U0001F4BB", "computer": "\U0001F4BB", "email": "\U0001F4E7",
    "envelope": "✉", "memo": "\U0001F4DD", "note": "\U0001F4DD",
    "notepad": "\U0001F4DD", "pencil": "✏", "folder": "\U0001F4C1",
    "clipboard": "\U0001F4CB", "books": "\U0001F4DA", "book": "\U0001F4D6",
    "camera": "\U0001F4F7", "music": "\U0001F3B5", "musical note": "\U0001F3B5",
    "microphone": "\U0001F3A4", "mic": "\U0001F3A4", "headphones": "\U0001F3A7",
    "tools": "\U0001F6E0", "hammer": "\U0001F528", "wrench": "\U0001F527",
    "gear": "⚙", "cog": "⚙", "car": "\U0001F697", "house": "\U0001F3E0",
    "home": "\U0001F3E0", "office": "\U0001F3E2", "globe": "\U0001F30D",
    "world": "\U0001F30D", "earth": "\U0001F30D", "plane": "✈",
    "airplane": "✈", "aeroplane": "✈", "target": "\U0001F3AF",
    "bullseye": "\U0001F3AF", "dart": "\U0001F3AF", "dice": "\U0001F3B2",
    "football": "⚽", "soccer ball": "⚽", "basketball": "\U0001F3C0",
    "flag": "\U0001F6A9", "chequered flag": "\U0001F3C1", "checkered flag": "\U0001F3C1",
    "uk flag": "\U0001F1EC\U0001F1E7", "british flag": "\U0001F1EC\U0001F1E7",
    "union jack": "\U0001F1EC\U0001F1E7",
    "england flag": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    "english flag": "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F",
    "us flag": "\U0001F1FA\U0001F1F8", "american flag": "\U0001F1FA\U0001F1F8",
    # food, drink, nature, animals
    "coffee": "☕", "tea": "\U0001F375", "cup of tea": "☕",
    "beer": "\U0001F37A", "beers": "\U0001F37B", "cheers": "\U0001F942",
    "wine": "\U0001F377", "champagne": "\U0001F37E", "pizza": "\U0001F355",
    "burger": "\U0001F354", "hamburger": "\U0001F354", "chips": "\U0001F35F",
    "fries": "\U0001F35F", "doughnut": "\U0001F369", "donut": "\U0001F369",
    "cookie": "\U0001F36A", "popcorn": "\U0001F37F", "apple": "\U0001F34E",
    "banana": "\U0001F34C", "avocado": "\U0001F951", "eggplant": "\U0001F346",
    "aubergine": "\U0001F346", "peach": "\U0001F351",
    "sun": "☀", "sunny": "☀", "sunshine": "☀",
    "cloud": "☁", "rain": "\U0001F327", "rainy": "\U0001F327",
    "umbrella": "☔", "snow": "❄", "snowflake": "❄",
    "snowman": "☃", "rainbow": "\U0001F308", "moon": "\U0001F319",
    "crescent moon": "\U0001F319", "full moon": "\U0001F315",
    "tree": "\U0001F333", "christmas tree": "\U0001F384", "flower": "\U0001F338",
    "rose": "\U0001F339", "sunflower": "\U0001F33B", "plant": "\U0001F331",
    "seedling": "\U0001F331", "four leaf clover": "\U0001F340",
    "dog": "\U0001F436", "puppy": "\U0001F436", "cat": "\U0001F431",
    "kitten": "\U0001F431", "unicorn": "\U0001F984", "lion": "\U0001F981",
    "tiger": "\U0001F42F", "bear": "\U0001F43B", "panda": "\U0001F43C",
    "fox": "\U0001F98A", "rabbit": "\U0001F430", "bunny": "\U0001F430",
    "mouse": "\U0001F42D", "pig": "\U0001F437", "cow": "\U0001F42E",
    "horse": "\U0001F434", "chicken": "\U0001F414", "penguin": "\U0001F427",
    "bird": "\U0001F426", "owl": "\U0001F989", "snake": "\U0001F40D",
    "fish": "\U0001F41F", "shark": "\U0001F988", "whale": "\U0001F433",
    "dolphin": "\U0001F42C", "octopus": "\U0001F419", "butterfly": "\U0001F98B",
    "bee": "\U0001F41D", "bug": "\U0001F41B", "spider": "\U0001F577",
    "turtle": "\U0001F422", "frog": "\U0001F438", "dinosaur": "\U0001F996",
    "t rex": "\U0001F996", "goat": "\U0001F410", "sloth": "\U0001F9A5",
    "pumpkin": "\U0001F383", "santa": "\U0001F385", "father christmas": "\U0001F385",
}

# Code points that count as an emoji when found by Unicode name.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2300, 0x23FF), (0x2B00, 0x2BFF),
    (0x2190, 0x21FF),
)
_EMOJI_SINGLES = frozenset((0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139,
                            0x3030, 0x303D, 0x3297, 0x3299))

# A word as the speech engine writes it: letters (accented too, "Côte"),
# digits, an inner apostrophe or hyphen ("t-rex", "d'Ivoire").
_WORD = r"[^\W_]+(?:['’\-][^\W_]+)*"
# Each "emoji" said: the trigger word, standing on its own.
_TRIGGER_WORD = re.compile(r"(?<![^\s,:])emoji(?:s|es)?\b", re.IGNORECASE)
# The run of words right before it (up to _MAX_WORDS). The words may not
# themselves be "emoji": "pizza emoji ok hand emoji" is two emoji, never one
# name "pizza emoji ok hand". Words may be split by spaces, a comma or a colon
# ("thumbs up, medium skin tone", "flag: France").
_NAME_RUN = re.compile(
    rf"((?:(?!emoji(?:s|es)?\b){_WORD}[ \t,:]+){{1,{_MAX_WORDS}}})$",
    re.IGNORECASE,
)
# Only this much text before each "emoji" is searched, so a long dictation
# costs the same as a short one (the longest name is well under it).
_LOOKBACK = 240
_WORDS = re.compile(_WORD)


def _is_emoji_cp(cp: int) -> bool:
    if cp in _EMOJI_SINGLES:
        return True
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _present(ch: str) -> str:
    """Give a BMP symbol its colour (emoji) look; astral emoji need nothing."""
    if len(ch) == 1 and ord(ch) < 0x10000 and not ch.endswith(_VS16):
        return ch + _VS16
    return ch


def _by_unicode_name(name: str):
    for cand in (name, name + " face", name + " sign"):
        try:
            ch = unicodedata.lookup(cand.upper())
        except KeyError:
            continue
        if len(ch) == 1 and _is_emoji_cp(ord(ch)):
            return ch
    return None


def normalise(name: str) -> str:
    """One form for spoken and table names: lower case, accents and
    apostrophes dropped, every run of spaces, hyphens, colons, commas one
    space, and anything else that is not a letter or digit
    ("Flag: Côte d'Ivoire" -> "flag cote divoire", "A button (blood type)"
    -> "a button blood type")."""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"['’]", "", s.lower())
    return " ".join(re.split(r"[^a-z0-9]+", s)).strip()


_TABLE = None
_FULL = None
_COMMA_KEYS = frozenset()   # official names that themselves hold a comma   # emoji with its presentation marks dropped -> official form


def _load() -> None:
    """The Unicode emoji list (emoji_names.py), loaded on the first spoken
    emoji only, so ordinary dictation never pays for it."""
    global _TABLE, _FULL, _COMMA_KEYS
    if _TABLE is not None:
        return
    try:
        from emoji_names import NAMES, COMMA_NAMES
    except Exception as e:   # never break dictation over the table
        print(f"[Emoji] Name table unavailable: {e}")
        NAMES, COMMA_NAMES = {}, frozenset()
    _COMMA_KEYS = frozenset(COMMA_NAMES)
    _TABLE = NAMES
    _FULL = {}
    for v in NAMES.values():
        _FULL.setdefault(v.replace(_VS16, ""), v)


def _official_form(ch: str):
    """ch as the official list writes it, or None if it is not an emoji.
    Without the list (it failed to load) BMP symbols get their colour mark."""
    if not _FULL:
        return _present(ch)
    return _FULL.get(ch.replace(_VS16, ""))


def lookup(name: str):
    """The emoji for a spoken name, or None.

    Order: everyday aliases (what people mean), then Unicode's official emoji
    list by name (every emoji: flags, skin tones, keycaps, joined emoji), then
    the name with "face" added ("thinking" -> thinking face), then the Unicode
    character name ("heavy dollar sign"). Whatever is found must be on the
    official list, so a symbol that is not an emoji (U+1F5CE DOCUMENT) never
    comes out."""
    key = normalise(name)
    if not key:
        return None
    _load()
    ch = _ALIASES.get(key)
    if ch is None:
        ch = _TABLE.get(key) or _TABLE.get(key + " face")
    if ch is None:
        ch = _by_unicode_name(key)
    return _official_form(ch) if ch else None


def _comma_ok(name: str) -> bool:
    """A name may cross a comma only where the official name has one
    ("family: man, woman, boy") or a skin tone follows it ("thumbs up,
    medium skin tone"). Prose before a comma is never part of the name:
    "Okay, hand emoji" is not the OK hand."""
    if "," not in name:
        return True
    _load()
    if normalise(name) in _COMMA_KEYS:
        return True
    return normalise(name.rsplit(",", 1)[1]).endswith("skin tone")


def _resolve(before: str):
    """before (the words ahead of "emoji") with its name swapped for the
    emoji, or None when no run of its words is a name."""
    spans = list(_WORDS.finditer(before))
    # Longest name first, always ending on the word right before "emoji".
    for start in range(len(spans)):
        name = before[spans[start].start():spans[-1].end()]
        if not _comma_ok(name):
            continue
        ch = lookup(name)
        if ch:
            return before[:spans[start].start()] + ch
    return None


def apply_spoken_emoji(text: str) -> str:
    """Replace "<name> emoji" with the emoji. Unknown names stay as spoken."""
    if not text or "emoji" not in text.lower():
        return text
    out = []
    done = 0                       # text before this is already in out
    for m in _TRIGGER_WORD.finditer(text):
        lo = max(done, m.start() - _LOOKBACK)
        run = _NAME_RUN.search(text, lo, m.start())
        if not run:
            continue
        swapped = _resolve(run.group(1))
        if swapped is None:
            continue
        out.append(text[done:run.start()])
        out.append(swapped)
        done = m.end()
    if not out:
        return text
    out.append(text[done:])
    return "".join(out)
