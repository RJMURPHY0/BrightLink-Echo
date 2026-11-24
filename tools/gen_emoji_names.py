"""Build emoji_names.py from Unicode's official emoji-test.txt.

    python tools/gen_emoji_names.py <path to emoji-test.txt>

Source: https://unicode.org/Public/emoji/15.1/emoji-test.txt (the CLDR short
names Windows' emoji panel shows). Only fully-qualified emoji are kept. The
file is data only: it is read as text here and never executed, and Echo ships
the generated table, not the download.

Keys are normalised exactly as spoken_emoji.normalise() does at run time, so a
spoken name and a table name meet in the same form. Flags also get the order
people say them in ("united kingdom flag" as well as "flag united kingdom").
"""

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from spoken_emoji import normalise  # noqa: E402

_LINE = re.compile(r"^([0-9A-F ]+?)\s*;\s*fully-qualified\s*#\s*(\S+)\s+E[\d.]+\s+(.+)$")


def build(path: str) -> tuple[dict, str, set]:
    names: dict[str, str] = {}
    comma: set[str] = set()
    version = ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("# Version:"):
                version = line.split(":", 1)[1].strip()
            m = _LINE.match(line.strip())
            if not m:
                continue
            cps, name = m.group(1), m.group(3)
            emoji = "".join(chr(int(c, 16)) for c in cps.split())
            # Keycap symbols have spoken names ("keycap: #" -> "keycap hash").
            name = name.replace("#", " hash").replace("*", " star")
            keys = [normalise(name)]
            if name.startswith("flag: "):
                keys.append(normalise(name[6:] + " flag"))
            for k in keys:
                if k and k not in names:
                    names[k] = emoji
                    if "," in name:
                        comma.add(k)
    return names, version, comma


def main() -> None:
    src = sys.argv[1]
    names, version, comma = build(src)
    out = os.path.join(REPO, "emoji_names.py")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write('"""Every emoji by its official name (generated, do not edit).\n\n'
                f"Unicode emoji {version}, fully-qualified, from emoji-test.txt.\n"
                "Rebuild with tools/gen_emoji_names.py. Loaded by spoken_emoji\n"
                'only when a dictation says "emoji".\n"""\n\n')
        f.write("NAMES = {\n")
        for k in sorted(names):
            esc = names[k].encode("unicode_escape").decode("ascii")
            f.write(f'    "{k}": "{esc}",\n')
        f.write("}\n\n")
        f.write('# Names that hold a comma themselves ("family: man, woman, boy").\n')
        f.write("COMMA_NAMES = frozenset({\n")
        for k in sorted(comma):
            f.write(f'    "{k}",\n')
        f.write("})\n")
    print(f"{len(names)} names, Unicode emoji {version} -> {out}")


if __name__ == "__main__":
    main()
