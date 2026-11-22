"""Kana lessons added to the module later don't lock A1 again for people who finished it."""

from types import SimpleNamespace as NS

from app.services.course import kana_done


def _level(lessons):
    return [NS(cefr="PRE", units=[NS(lessons=lessons)])]


def test_finishing_the_original_lessons_still_unlocks_a1_after_extras_are_added():
    lessons = [NS(id=i, order=i, skeleton_json={}) for i in (1, 2)]
    extra = NS(id=3, order=3, skeleton_json={"extra": True})
    test = NS(id=9, order=100, skeleton_json={})
    done = {i: NS(status="completed") for i in (1, 2)}
    enrolment = NS(settings_json={})
    assert kana_done(enrolment, done, _level([*lessons, extra, test]))
    # an unfinished regular lesson still keeps A1 locked
    assert not kana_done(enrolment, {1: NS(status="completed")}, _level([*lessons, extra, test]))
