"""Uploaded video files: what gets repackaged or refused, subtitle tracks, transcript timing."""

import pytest

from app.services.video_files import (
    CHUNK_BYTES,
    VideoFileError,
    chunk_count,
    merge_segments,
    plan_output,
    subtitle_stream,
)


def streams(*items):
    return {"streams": [dict(index=i, **s) for i, s in enumerate(items)]}


def test_h264_with_aac_is_copied_into_mp4_without_re_encoding():
    container, args = plan_output(streams({"codec_type": "video", "codec_name": "h264"},
                                          {"codec_type": "audio", "codec_name": "aac"}))
    assert container == "mp4"
    assert args[args.index("-c:v") + 1] == "copy" and args[args.index("-c:a") + 1] == "copy"
    assert "+faststart" in args


def test_unplayable_audio_is_converted_but_the_picture_is_not():
    container, args = plan_output(streams({"codec_type": "video", "codec_name": "h264"},
                                          {"codec_type": "audio", "codec_name": "flac"}))
    assert container == "mp4" and args[args.index("-c:v") + 1] == "copy"
    assert args[args.index("-c:a") + 1] == "aac"


def test_vp9_goes_to_webm_and_cover_art_is_not_the_video():
    container, args = plan_output(streams(
        {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}},
        {"codec_type": "video", "codec_name": "vp9"}, {"codec_type": "audio", "codec_name": "opus"}))
    assert container == "webm" and "0:1" in args


def test_hevc_is_refused_with_a_conversion_tip():
    with pytest.raises(VideoFileError, match="H.264"):
        plan_output(streams({"codec_type": "video", "codec_name": "hevc"}, {"codec_type": "audio", "codec_name": "aac"}))


def test_japanese_text_track_is_found_and_image_subtitles_are_skipped():
    info = streams({"codec_type": "video", "codec_name": "h264"},
                   {"codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle", "tags": {"language": "jpn"}},
                   {"codec_type": "subtitle", "codec_name": "ass", "tags": {"language": "eng"}},
                   {"codec_type": "subtitle", "codec_name": "ass", "tags": {"language": "jpn", "title": "Japanese"}})
    assert subtitle_stream(info, "ja")["index"] == 3
    assert subtitle_stream(info, "fr") is None


def test_track_titled_japanese_counts_even_without_a_language_tag():
    info = streams({"codec_type": "subtitle", "codec_name": "subrip", "tags": {"title": "日本語"}})
    assert subtitle_stream(info, "ja")["index"] == 0


def test_transcribed_clips_join_into_one_timeline_without_overlaps():
    cues = merge_segments([(0, [(0.5, 2.0, "こんにちは"), (110.0, 121.0, "長い文")]),
                           (120, [(0.2, 3.0, "次の文"), (4.0, 4.0, "")])])
    assert [(c.start_ms, c.end_ms, c.text) for c in cues] == [
        (500, 2000, "こんにちは"), (110000, 121000, "長い文"), (121000, 123000, "次の文")]


def test_pieces_cover_the_whole_file():
    assert chunk_count(1) == 1
    assert chunk_count(CHUNK_BYTES) == 1
    assert chunk_count(CHUNK_BYTES + 1) == 2
