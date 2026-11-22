"""Checks for AI-written Japanese lesson content.

The model writes furigana as {漢字|かな}. These checks catch what a learner would
trip over: a reading that no dictionary reading of those kanji can produce
({今日|こんにち}, {行|おこな}きます where いきます was meant is fine, {生|なま}… is fine,
{食|しょく}べる is not), kanji left without furigana, broken markup, romaji in
Japanese text, vocab readings that disagree with their furigana, and word-bank
tiles that don't spell the answer.

Readings come from KANJIDIC2 (curriculum/kanji.json): on'yomi, kun'yomi (stem and
full form), with sound changes in compounds — rendaku (か→が), handakuten after
っ/ん (は→ぱ), and a small っ in place of a final つ/ち/く/き. Words read as a
whole (今日 きょう, 大人 おとな) are listed in JUKUJIKUN.
"""

import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from ..config import get_settings
from .text import RUBY, ruby_reading, strip_ruby

KANJI = re.compile(r"[㐀-鿿豈-﫿々]")
KANA = re.compile(r"^[ぁ-ゟ゠-ヿー]+$")
ROMAJI = re.compile(r"(?<![A-Za-z])[a-z]{3,}(?![A-Za-z])")
_PUNCT = re.compile(r"[\s。、，．・！？!?.,「」『』（）()\[\]…〜~ー]")

# Whole-word readings that can't be built kanji by kanji (jukujikun and fixed exceptions).
JUKUJIKUN: dict[str, tuple[str, ...]] = {
    "今日": ("きょう", "こんにち"), "明日": ("あした", "あす", "みょうにち"), "昨日": ("きのう", "さくじつ"),
    "今朝": ("けさ",), "今年": ("ことし",), "今晩": ("こんばん",), "一昨日": ("おととい",), "明後日": ("あさって",),
    "一昨年": ("おととし",), "大人": ("おとな",), "一人": ("ひとり",), "二人": ("ふたり",), "一日": ("ついたち", "いちにち"),
    "二日": ("ふつか",), "三日": ("みっか",), "四日": ("よっか",), "五日": ("いつか",), "六日": ("むいか",),
    "七日": ("なのか",), "八日": ("ようか",), "九日": ("ここのか",), "十日": ("とおか",), "二十日": ("はつか",),
    "二十歳": ("はたち",), "上手": ("じょうず",), "下手": ("へた",), "時計": ("とけい",), "眼鏡": ("めがね",),
    "果物": ("くだもの",), "部屋": ("へや",), "土産": ("みやげ",), "紅葉": ("もみじ", "こうよう"), "風邪": ("かぜ",),
    "浴衣": ("ゆかた",), "七夕": ("たなばた",), "梅雨": ("つゆ", "ばいう"), "博士": ("はかせ",), "迷子": ("まいご",),
    "真面目": ("まじめ",), "素人": ("しろうと",), "玄人": ("くろうと",), "息子": ("むすこ",), "母さん": ("かあさん",),
    "父さん": ("とうさん",), "兄さん": ("にいさん",), "姉さん": ("ねえさん",), "叔父": ("おじ",), "伯父": ("おじ",),
    "叔母": ("おば",), "伯母": ("おば",), "日本": ("にほん", "にっぽん"), "景色": ("けしき",), "相撲": ("すもう",),
    "一寸": ("ちょっと",), "清水": ("しみず",), "田舎": ("いなか",), "八百屋": ("やおや",), "芝生": ("しばふ",),
    "仲人": ("なこうど",), "若人": ("わこうど",), "雪崩": ("なだれ",), "吹雪": ("ふぶき",), "海苔": ("のり",),
    "竹刀": ("しない",), "数寄屋": ("すきや",), "足袋": ("たび",), "草履": ("ぞうり",), "木綿": ("もめん",),
    "心地": ("ここち",), "行方": ("ゆくえ",), "為替": ("かわせ",), "河原": ("かわら",), "川原": ("かわら",),
    "砂利": ("じゃり",), "太刀": ("たち",), "時雨": ("しぐれ",), "五月雨": ("さみだれ",), "名残": ("なごり",),
    "笑顔": ("えがお",), "神楽": ("かぐら",), "神輿": ("みこし",), "お神輿": ("おみこし",), "山車": ("だし",),
    "出汁": ("だし",), "団扇": ("うちわ",), "老舗": ("しにせ",), "従兄弟": ("いとこ",), "乳母": ("うば",),
    "白髪": ("しらが",), "居士": ("こじ",), "寿司": ("すし",), "可愛い": ("かわいい",), "美味しい": ("おいしい",),
    "煙草": ("たばこ",), "蒲公英": ("たんぽぽ",), "百合": ("ゆり",), "向日葵": ("ひまわり",), "秋刀魚": ("さんま",),
    "大和": ("やまと",), "東京": ("とうきょう",), "京都": ("きょうと",), "大阪": ("おおさか",), "神戸": ("こうべ",),
    "日和": ("びより", "ひより"), "一期一会": ("いちごいちえ",), "猛者": ("もさ",), "火傷": ("やけど",),
    "欠伸": ("あくび",), "土産物": ("みやげもの",), "今宵": ("こよい",), "昨夜": ("ゆうべ", "さくや"),
    "七転八起": ("しちてんはっき",), "侘び寂び": ("わびさび",), "侘寂": ("わびさび",),
}

_DAKUTEN = dict(zip("かきくけこさしすせそたちつてとはひふへほ", "がぎぐげござじずぜぞだぢづでどばびぶべぼ"))
_HANDAKUTEN = dict(zip("はひふへほ", "ぱぴぷぺぽ"))
_EXTRA_VOICING = {"ち": "じ", "つ": "ず"}  # ぢ/づ are usually written じ/ず


def hira(text: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


@lru_cache
def _kanji_data() -> dict[str, Any]:
    path = get_settings().curriculum_dir / "kanji.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_source", None)
    return data


@lru_cache(maxsize=8192)
def base_readings(char: str) -> frozenset[str]:
    entry = _kanji_data().get(char)
    if not entry:
        return frozenset()
    out: set[str] = set()
    for r in entry.get("on", []):
        out.add(hira(r.strip("-")))
    for r in entry.get("kun", []):
        r = r.strip("-")
        stem, _, okuri = r.partition(".")
        out.add(stem)
        if okuri:
            out.add(stem + okuri)
    return frozenset(x for x in out if x)


@lru_cache(maxsize=16384)
def _variants(char: str, first: bool, last: bool) -> frozenset[str]:
    out = set(base_readings(char))
    if not first:  # sound changes inside a compound
        for r in list(out):
            head = r[0]
            for changed in (_DAKUTEN.get(head), _HANDAKUTEN.get(head), _EXTRA_VOICING.get(head)):
                if changed:
                    out.add(changed + r[1:])
    if not last:
        for r in list(out):
            if len(r) >= 2 and r[-1] in "つちくき":
                out.add(r[:-1] + "っ")
    return frozenset(out)


def plausible_reading(base: str, reading: str, *, joined_before: bool = False, joined_after: bool = False) -> bool:
    """Can `reading` be built from dictionary readings of `base` (kana in the base must match)?
    `joined_before/after`: the group touches another kanji group ({三|さん}{千|ぜん}), so sound
    changes at that edge are allowed. Unknown kanji (not in the data) get the benefit of the doubt."""
    base, reading = base.strip(), hira(reading.strip())
    if not base or not reading:
        return False
    if any(KANJI.match(c) and c != "々" and not base_readings(c) for c in base):
        return True

    @lru_cache(maxsize=None)
    def match(i: int, j: int) -> bool:
        if i == len(base):
            return j == len(reading)
        if j >= len(reading):
            return False
        for whole, readings in JUKUJIKUN.items():
            if base.startswith(whole, i):
                for r in readings:
                    if reading.startswith(r, j) and match(i + len(whole), j + len(r)):
                        return True
        ch = base[i]
        if not KANJI.match(ch):
            return hira(ch) == reading[j] and match(i + 1, j + 1)
        src = base[i - 1] if ch == "々" and i > 0 else ch
        last = (i == len(base) - 1 and not joined_after) or (i < len(base) - 1 and not KANJI.match(base[i + 1]))
        for cand in _variants(src, i == 0 and not joined_before, last):
            if reading.startswith(cand, j) and match(i + 1, j + len(cand)):
                return True
        return False

    return match(0, 0)


# ---------------------------------------------------------------- issues

@dataclass
class Issue:
    where: str
    kind: str  # reading | no_furigana | markup | romaji | vocab_reading | tiles | kana_furigana
    detail: str
    severity: str = "error"  # error: a learner sees something wrong · warning: worth a look
    text: str = ""  # the whole string, so a repair can replace it

    def dict(self) -> dict[str, str]:
        return asdict(self)


# Strings a learner types against rather than reads: furigana there is optional.
_HIDDEN = re.compile(r"\.accepted\[\d+\]$|\.answers\[[1-9]\d*\]$")


def _plausible_in_context(text: str, m: re.Match[str]) -> bool:
    """Is a furigana group right, allowing words split oddly by the markup, such as
    お{父|とう}さん (父さん is read とうさん as a whole)?"""
    base, reading = m.group(1), m.group(2)
    before = text[:m.start()]
    joined_before = before.endswith("}") or bool(before and KANJI.match(before[-1]))
    rest = text[m.end():]
    joined_after = rest.startswith("{") or bool(rest and KANJI.match(rest[0]))
    if plausible_reading(base, reading, joined_before=joined_before, joined_after=joined_after):
        return True
    after = re.match(r"[ぁ-ゟ]{1,3}", text[m.end():])
    for k in range(len(after.group(0)) if after else 0, 0, -1):
        tail = after.group(0)[:k]
        if plausible_reading(base + tail, reading + tail):
            return True
    return False


def check_text(text: str, where: str, *, romaji_ok: bool = False) -> list[Issue]:
    """Problems in one piece of Japanese text."""
    issues: list[Issue] = []
    if not isinstance(text, str) or not text:
        return issues
    hidden = bool(_HIDDEN.search(where))

    def add(kind: str, detail: str, severity: str = "error") -> None:
        issues.append(Issue(where, kind, detail, "warning" if hidden and severity == "error" else severity, text))

    if text.count("{") != text.count("}") or re.search(r"\{[^{}|]*\}", text) or "|" in RUBY.sub("", text):
        add("markup", f"Broken furigana markup: {text}")
    for m in RUBY.finditer(text):
        base, reading = m.group(1), m.group(2)
        if "_" in base or "_" in reading:
            add("markup", f"A blank inside furigana markup: {m.group(0)}")
        elif not KANJI.search(base):
            add("kana_furigana", f"Furigana on kana: {m.group(0)}", "warning")
        elif re.search(r"[・･\s]", reading):
            add("markup", f"Dots or spaces inside a reading: {m.group(0)}")
        elif not KANA.match(reading):
            add("markup", f"Reading isn't kana: {m.group(0)}")
        elif not _plausible_in_context(text, m):
            add("reading", f"{base} isn't read {reading}")
    bare = KANJI.findall(RUBY.sub("", text))
    if bare:
        add("no_furigana", f"Kanji without furigana: {''.join(dict.fromkeys(bare))} in {text}")
    if not romaji_ok and ROMAJI.search(strip_ruby(text)):
        add("romaji", f"Latin letters in Japanese text: {text}", "warning")
    return issues


def _norm(text: str) -> str:
    return _PUNCT.sub("", strip_ruby(text or ""))


def _vocab_issues(v: dict[str, Any], where: str) -> list[Issue]:
    issues = check_text(v.get("word", ""), f"{where}.word") + check_text(v.get("example", ""), f"{where}.example")
    word, reading = (v.get("word") or "").replace("〜", ""), v.get("reading")
    if "{" in word and reading and hira(reading.replace("〜", "")) != hira(ruby_reading(word)):
        issues.append(Issue(f"{where}.reading", "vocab_reading",
                            f"Reading {reading} doesn't match the furigana of {word} ({ruby_reading(word)})"))
    return issues


def _exercise_issues(ex: dict[str, Any], where: str) -> list[Issue]:
    t = ex.get("type")
    out: list[Issue] = []

    def texts(value: Any, field: str) -> None:
        if isinstance(value, list):
            for n, item in enumerate(value):
                out.extend(check_text(item, f"{where}.{field}[{n}]"))
        elif isinstance(value, str):
            out.extend(check_text(value, f"{where}.{field}"))

    if t == "multiple_choice":
        if ex.get("question_lang") == "target":
            texts(ex.get("question"), "question")
        if ex.get("options_lang") == "target":
            texts(ex.get("options"), "options")
    elif t == "listening_choice":
        texts(ex.get("audio_text"), "audio_text")
        if ex.get("options_lang") == "target":
            texts(ex.get("options"), "options")
    elif t == "word_bank":
        for field in ("answer", "answer_tiles", "distractors", "accepted"):
            texts(ex.get(field), field)
        tiles = "".join(_norm(x) for x in ex.get("answer_tiles") or [])
        if tiles != _norm(ex.get("answer", "")):
            out.append(Issue(f"{where}.answer_tiles", "tiles",
                             f"Tiles spell {tiles} but the answer is {strip_ruby(ex.get('answer', ''))}"))
    elif t == "translate":
        if ex.get("direction") == "to_target":
            texts(ex.get("answers"), "answers")
        else:
            texts(ex.get("source"), "source")
    elif t == "fill_blank":
        sentence = ex.get("sentence") or ""
        texts(sentence, "sentence")
        pre, _, post = sentence.partition("___")
        for field in ("answers", "options"):
            for n, choice in enumerate(ex.get(field) or []):
                if not isinstance(choice, str):
                    continue
                at = f"{where}.{field}[{n}]"
                found = check_text(choice, at)
                out.extend(i for i in found if i.kind != "reading")
                # a reading is judged where the choice goes: お___さん + {父|とう} is お父さん (おとうさん)
                whole = pre + choice + post
                for m in RUBY.finditer(whole):
                    inside = len(pre) <= m.start() < len(pre) + len(choice)
                    if inside and KANJI.search(m.group(1)) and KANA.match(_clean(m.group(2))) \
                            and not _plausible_in_context(whole, m):
                        severity = "warning" if _HIDDEN.search(at) else "error"
                        out.append(Issue(at, "reading", f"{m.group(1)} isn't read {m.group(2)}", severity, choice))
    elif t == "match_pairs":
        texts([p.get("left", "") for p in ex.get("pairs") or []], "pairs")
    elif t in ("dictation", "speak"):
        texts(ex.get("text"), "text")
        texts(ex.get("accepted"), "accepted")
    elif t == "reading":
        texts(ex.get("passage"), "passage")
    return out


def _all_vocab(content: dict[str, Any]) -> list[dict[str, Any]]:
    return [*(content.get("vocab") or []),
            *((ex.get("vocab") or {}) for ex in content.get("exercises") or [] if ex.get("type") == "vocab_intro")]


def _known_readings(content: dict[str, Any]) -> dict[str, set[str]]:
    """Kanji words the lesson teaches (a whole vocab word that is one furigana group of
    2+ kanji, like {今日|きょう}) → their reading. Single kanji are too ambiguous (何 なに/なん)."""
    out: dict[str, set[str]] = {}
    for v in _all_vocab(content):
        m = RUBY.fullmatch((v.get("word") or "").replace("〜", "").strip())
        if m and len(m.group(1)) >= 2:
            out.setdefault(m.group(1), set()).add(hira(_clean(m.group(2))))
    return out


def _clean(reading: str) -> str:
    return re.sub(r"[・･\s]", "", reading)


def _strings(node: Any, where: str):
    if isinstance(node, str):
        yield node, where
    elif isinstance(node, list):
        for n, v in enumerate(node):
            yield from _strings(v, f"{where}[{n}]")
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _strings(v, f"{where}.{k}")


def check_lesson(content: dict[str, Any]) -> list[Issue]:
    """Every problem found in a lesson's content (vocab, grammar and exercises)."""
    issues: list[Issue] = []
    known = _known_readings(content)
    for key in ("grammar", "exercises"):
        for text, where in _strings(content.get(key) or [], key):
            for m in RUBY.finditer(text):
                base, reading = m.group(1), hira(_clean(m.group(2)))
                if base in known and reading not in known[base]:
                    issues.append(Issue(where, "reading", f"{base} is read {reading} here but "
                                        f"{'/'.join(sorted(known[base]))} in the vocab list", "warning", text))
    for i, v in enumerate(content.get("vocab") or []):
        issues += _vocab_issues(v, f"vocab[{i}]")
    for i, g in enumerate(content.get("grammar") or []):
        for n, e in enumerate(g.get("examples") or []):
            issues += check_text(e.get("target", ""), f"grammar[{i}].examples[{n}]")
    for i, ex in enumerate(content.get("exercises") or []):
        if ex.get("type") not in ("vocab_intro", "grammar_note"):  # those repeat vocab / grammar
            issues += _exercise_issues(ex, f"exercises[{i}]")
    seen: set[tuple[str, str]] = set()
    unique = []
    for issue in issues:  # the same problem in several places is one problem
        if (issue.kind, issue.detail) not in seen:
            seen.add((issue.kind, issue.detail))
            unique.append(issue)
    return unique


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


# ---------------------------------------------------------------- repairs

def _map_strings(content: dict[str, Any], fn) -> int:
    """Apply fn to every string in vocab, grammar and exercises; count the changes."""
    changed = 0

    def walk(node: Any) -> Any:
        nonlocal changed
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            new = fn(node)
            changed += new != node
            return new
        return node

    for key in ("vocab", "grammar", "exercises"):
        if key in content:
            content[key] = walk(content[key])
    return changed


def autofix(content: dict[str, Any]) -> int:
    """Repairs that need no judgement: dots or spaces inside readings, furigana on kana,
    and vocab readings that disagree with their own furigana."""
    fixed = _map_strings(content, lambda t: RUBY.sub(
        lambda m: m.group(1) if not KANJI.search(m.group(1))
        else "{" + m.group(1) + "|" + _clean(m.group(2)) + "}", t))
    for v in _all_vocab(content):
        word = (v.get("word") or "").replace("〜", "")
        if "{" in word:
            want = ruby_reading(word)
            if v.get("reading") != want:
                v["reading"] = want
                fixed += 1
    return fixed


def visible(text: str) -> set[str]:
    """What a learner reads, ignoring furigana — also through broken markup such as {一日},
    本当|ほんとう or a reading in brackets 人 (にん). A stray |reading has no end marker
    (降|ふります could be 降ります), so every possible end is offered."""
    t = re.sub(r"\s*[（(][ぁ-ヿー]+[)）]", "", strip_ruby(text)).replace("{", "").replace("}", "")
    out = {t}
    for _ in range(3):  # at most a few stray bars in one string
        nxt = set()
        for v in out:
            m = re.search(r"\|([ぁ-ヿー]+)", v)
            if not m:
                nxt.add(v)
                continue
            for k in range(1, len(m.group(1)) + 1):
                nxt.add(v[:m.start()] + m.group(1)[k:] + v[m.end():])
        out = nxt
    return out


def accept_repair(original: str, fixed: str) -> bool:
    """A repaired string may only change furigana: same visible text, and no errors left."""
    if not isinstance(fixed, str) or strip_ruby(fixed) not in visible(original):
        return False
    return not errors(check_text(fixed, "repair"))


REPAIR_SYSTEM = (
    "You fix furigana markup in Japanese learning content. Furigana is written {漢字|かな}: the kanji, a bar, "
    "then the reading in plain hiragana with no dots or spaces, e.g. {日本|にほん}に{行|い}きます. For each "
    "string you get, return it with every kanji inside correct markup and every reading right for this context. "
    "Change nothing else: not one character outside the markup, not the punctuation, not the blanks (___), which "
    "must stay outside any markup. A reading written in brackets after a word, like 人 (にん), becomes markup. "
    'You get a JSON list of {"n": number, "text": string}. Return JSON: {"fixed": [{"n": <same number>, '
    '"text": "<corrected string>"}]}'
)


async def repair(ai: Any, content: dict[str, Any], *, limit: int = 40) -> tuple[int, list[Issue]]:
    """Fix what autofix can't (missing furigana, wrong readings, broken markup) with one
    small model call on just the faulty strings; each fix is kept only if it passes the
    checks with the visible text unchanged. Returns (strings fixed, issues left)."""
    from pydantic import BaseModel  # local: keeps this module light for the checks alone

    from ..providers.base import ChatMessage

    class _Fix(BaseModel):
        n: int
        text: str

    class _Fixes(BaseModel):
        fixed: list[_Fix]

    fixed = autofix(content)
    todo = list(dict.fromkeys(i.text for i in errors(check_lesson(content))
                              if i.text and i.kind in ("reading", "no_furigana", "markup")))[:limit]
    if todo:
        listing = json.dumps([{"n": n, "text": t} for n, t in enumerate(todo)], ensure_ascii=False)
        result = await ai.llm_json("lesson_repair", "content", _Fixes, system=REPAIR_SYSTEM,
                                   messages=[ChatMessage("user", listing)], temperature=0.1,
                                   max_tokens=min(8192, 400 + 160 * len(todo)), thinking="low")
        good = {todo[f.n]: f.text for f in result.fixed
                if 0 <= f.n < len(todo) and accept_repair(todo[f.n], f.text)}
        if good:
            fixed += _map_strings(content, lambda t: good.get(t, t))
    return fixed, check_lesson(content)


def issues_json(issues: list[Issue]) -> list[dict[str, str]]:
    return [{k: v for k, v in i.dict().items() if k != "text"} for i in issues]


# ---------------------------------------------------------------- speech

def speakable_japanese(text: str) -> str:
    """Text for the voice. Given plain kanji, voices pick a reading themselves and often pick
    another word ({辛|から}い said つらい, {明日|あした} said あす, {一日|ついたち} said いちにち). So
    single-kanji words and whole-word readings are spoken from their furigana; regular
    compounds (電話番号, 日曜日) stay in kanji, which the voice reads well and phrases better."""
    def say(m: re.Match[str]) -> str:
        base, reading = m.group(1), re.sub(r"[・･\s]", "", m.group(2))
        kanji = KANJI.findall(base)
        if len(kanji) <= 1 or base in JUKUJIKUN or any(w in base for w in JUKUJIKUN if len(w) > 1):
            return reading
        return base
    return RUBY.sub(say, text)
