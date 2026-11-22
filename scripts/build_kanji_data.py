"""Build curriculum/kanji.json from the EDRDG kanji dictionaries.

Run once on a dev machine when the data should be refreshed (the result is
committed; the server never downloads anything):

    curl -L -o /tmp/kanjidic2.xml.gz http://www.edrdg.org/kanjidic/kanjidic2.xml.gz
    curl -L -o /tmp/kradzip.zip      http://ftp.edrdg.org/pub/Nihongo/kradzip.zip
    python scripts/build_kanji_data.py /tmp/kanjidic2.xml.gz /tmp/kradzip.zip

Keeps the Jōyō kanji (grades 1–8), anything with a JLPT level and every kanji
in curriculum/ja.yaml, with up to three English meanings, on/kun readings,
stroke count, grade, old JLPT level (4 = easiest … 1 = hardest), newspaper
frequency rank and component parts.

KANJIDIC2 and KRADFILE are the property of the Electronic Dictionary Research
and Development Group and are used under the CC BY-SA 4.0 licence
(https://www.edrdg.org/edrdg/licence.html).
"""

import gzip
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "curriculum" / "kanji.json"
ATTRIBUTION = ("KANJIDIC2 and KRADFILE, Electronic Dictionary Research and Development Group "
               "(edrdg.org), CC BY-SA 4.0")


def parts_table(kradzip: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    with zipfile.ZipFile(kradzip) as z:
        for name in ("kradfile", "kradfile2"):
            for line in z.read(name).decode("euc_jp", "replace").splitlines():
                if not line or line.startswith("#") or " : " not in line:
                    continue
                char, rest = line.split(" : ", 1)
                out.setdefault(char.strip(), [p for p in rest.split() if p != char.strip()])
    return out


def course_kanji() -> set[str]:
    """Every kanji the Japanese course teaches, kept even when it isn't a school kanji."""
    vocab = "".join(re.findall(r"vocab: \[(.*?)\]", (ROOT / "curriculum" / "ja.yaml").read_text(encoding="utf-8")))
    return {c for c in vocab if "一" <= c <= "鿿"}


def build(kanjidic: Path, kradzip: Path) -> dict[str, dict]:
    parts = parts_table(kradzip)
    wanted = course_kanji()
    entries: dict[str, dict] = {}
    with gzip.open(kanjidic, "rb") as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag != "character":
                continue
            char = el.findtext("literal") or ""
            misc = el.find("misc")
            grade = int(misc.findtext("grade")) if misc is not None and misc.findtext("grade") else None
            jlpt = int(misc.findtext("jlpt")) if misc is not None and misc.findtext("jlpt") else None
            if (grade is None or grade > 8) and jlpt is None and char not in wanted:
                el.clear()
                continue
            rm = el.find("reading_meaning")
            on, kun, meanings = [], [], []
            if rm is not None:
                for r in rm.iter("reading"):
                    if r.get("r_type") == "ja_on":
                        on.append(r.text)
                    elif r.get("r_type") == "ja_kun":
                        kun.append(r.text)
                meanings = [m.text for m in rm.iter("meaning") if m.get("m_lang") is None][:3]
            freq = misc.findtext("freq") if misc is not None else None
            entries[char] = {
                "m": meanings, "on": on[:4], "kun": kun[:6],
                "s": int(misc.findtext("stroke_count")) if misc is not None else None,
                "g": grade, "j": jlpt, "f": int(freq) if freq else None,
                "p": parts.get(char, []),
            }
            el.clear()
    return entries


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    entries = build(Path(sys.argv[1]), Path(sys.argv[2]))
    # One kanji per line keeps diffs readable.
    lines = [f'  {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False, separators=(",", ":"))}'
             for k, v in sorted(entries.items(), key=lambda kv: (kv[1]["f"] or 9999, kv[0]))]
    OUT.write_text('{\n  "_source": ' + json.dumps(ATTRIBUTION) + ',\n' + ",\n".join(lines) + "\n}\n",
                   encoding="utf-8")
    print(f"wrote {len(entries)} kanji to {OUT}")


if __name__ == "__main__":
    main()
