"""Watch: subtitle parsing, YouTube links and protecting the subtitle text."""

import pytest

from app.services.subtitles import SubtitleError, parse
from app.services.videos import _Batch, _Line, _same_text, apply_batch, overall_level, youtube_id

SRT = """1
00:00:01,000 --> 00:00:03,500
<i>こんにちは！</i>

2
00:00:04,000 --> 00:00:06,000
今日は
いい天気ですね。

3
00:00:06,000 --> 00:00:06,000
empty duration is dropped
""".encode()


def test_srt_strips_tags_and_joins_cue_lines():
    cues = parse(SRT, "a.srt")
    assert [(c.start_ms, c.end_ms, c.text) for c in cues] == [
        (1000, 3500, "こんにちは！"), (4000, 6000, "今日は いい天気ですね。")]


def test_vtt_rolling_auto_captions_are_collapsed():
    vtt = """WEBVTT
Kind: captions

00:00:00.000 --> 00:00:02.000 align:start
駅は

00:00:02.000 --> 00:00:04.000
駅はどこですか

00:00:04.000 --> 00:00:05.000
駅はどこですか
""".encode()
    cues = parse(vtt, "a.vtt")
    assert [c.text for c in cues] == ["駅は", "どこですか"]
    assert cues[-1].end_ms == 5000


def test_ass_reads_dialogue_and_skips_signs_and_songs():
    ass = r"""[Script Info]
Title: x

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\an8}行こう、\Nみんな！
Dialogue: 0,0:00:03.00,0:00:04.00,Signs,,0,0,0,,駅前
Dialogue: 0,0:00:03.00,0:00:04.00,OP Song,,0,0,0,,ラララ
Dialogue: 0,0:00:05.00,0:00:06.00,Default-Top,,0,0,0,,待って
""".encode()
    assert [c.text for c in parse(ass, "ep1.ass")] == ["行こう、 みんな！", "待って"]


def test_shift_jis_files_are_read():
    srt = "1\n00:00:01,000 --> 00:00:02,000\nありがとう\n".encode("cp932")
    assert parse(srt, "a.srt")[0].text == "ありがとう"


def test_files_without_cues_are_rejected():
    with pytest.raises(SubtitleError):
        parse(b"just some text", "notes.txt")


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/shorts/dQw4w9WgXcQ",
    "youtube.com/embed/dQw4w9WgXcQ",
    "Check this out! https://youtu.be/dQw4w9WgXcQ",  # text shared from the YouTube app
])
def test_youtube_links(url):
    assert youtube_id(url) == "dQw4w9WgXcQ"


def test_non_youtube_links_are_refused():
    assert youtube_id("https://example.com/watch?v=dQw4w9WgXcQ") is None
    assert youtube_id("https://youtu.be/short") is None


def test_the_model_may_add_furigana_but_not_change_the_line():
    assert _same_text("{今日|きょう}は{雨|あめ}だね。", "今日は雨だね。")
    assert not _same_text("{今日|きょう}は{晴|は}れだね。", "今日は雨だね。")


def test_apply_batch_keeps_the_original_when_rewritten():
    class Row:
        def __init__(self, idx, raw):
            self.idx, self.raw, self.ja, self.kana, self.en, self.words = idx, raw, None, None, None, []
    rows = [Row(0, "今日は雨だね。"), Row(1, "行こう"), Row(2, "missing from the answer")]
    apply_batch("ja", rows, _Batch(level="A2", lines=[
        _Line(i=0, ja="{今日|きょう}は{雨|あめ}だね。", kana="きょうはあめだね。", en="Rainy today, huh."),
        _Line(i=1, ja="{行|い}きましょう", kana="いきましょう", en="Let's go"),
    ]))
    assert rows[0].ja.startswith("{今日|きょう}") and rows[0].kana == "きょうはあめだね。"
    assert rows[1].ja == "行こう" and rows[1].en == "Let's go"  # rewritten line → original kept
    assert rows[2].en == "" and rows[2].ja == rows[2].raw


def test_overall_level_is_the_middle_of_the_batches():
    assert overall_level(["A1", "A2", "B1", None]) == "A2"
    assert overall_level([None]) is None
