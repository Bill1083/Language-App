"""Small text helpers shared by answer checking, TTS and conversation.

Japanese text from the LLM carries furigana as `{漢字|かんじ}`; the frontend
renders it with <ruby>, everything else needs the plain base or reading.
"""

import re
import unicodedata

RUBY = re.compile(r"\{([^{}|]+)\|([^{}]+)\}")
UNCLEAR = re.compile(r"\[\?\]")


def strip_ruby(text: str) -> str:
    """{日本|にほん}に → 日本に"""
    return RUBY.sub(r"\1", text)


def ruby_reading(text: str) -> str:
    """{日本|にほん}に → にほんに"""
    return RUBY.sub(r"\2", text)


def speakable(text: str) -> str:
    text = UNCLEAR.sub("", strip_ruby(text))
    text = re.sub(r"[*_`#>]+", "", text)  # stray markdown
    return re.sub(r"\s+", " ", text).strip()


SENTENCE_END = re.compile(r"(?<=[.!?…。！？])[\"'»」』)]*\s+|(?<=[。！？])")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_END.split(text)]
    return [p for p in parts if p]


def take_complete_sentences(buffer: str) -> tuple[list[str], str]:
    """Split a streaming buffer into finished sentences and the unfinished tail."""
    last = -1
    for m in SENTENCE_END.finditer(buffer):
        last = m.end()
    if last <= 0:
        return [], buffer
    done, rest = buffer[:last], buffer[last:]
    # Don't cut inside an open furigana group
    if done.count("{") != done.count("}"):
        return [], buffer
    return split_sentences(done), rest


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def has_japanese(text: str) -> bool:
    return any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in text)
