from app.services.answer_check import check_answer, expand_alternatives, levenshtein, normalize


def verdict(answer, accepted, lang, **kw):
    return check_answer(answer, accepted, lang, **kw).verdict


# --------------------------------------------------------------------------- normalisation


def test_normalize_case_punctuation_whitespace():
    assert normalize("  Bonjour,   Marie !  ", "fr") == "bonjour marie"
    assert normalize("C’est l’été.", "fr") == "c'est l'été"
    assert normalize("Est-ce que tu viens ?", "fr") == "est ce que tu viens"


def test_normalize_unicode_nfc():
    decomposed = "été"  # é written as e + combining acute
    assert normalize(decomposed, "fr") == normalize("été", "fr")


def test_normalize_japanese_width_and_punctuation():
    assert normalize("ｺｰﾋｰをください。", "ja") == "コーヒーをください"
    assert normalize("ＡＢＣ　です！", "ja") == "abcです"


def test_normalize_english_contractions():
    assert normalize("I'm not hungry", "en") == normalize("I am not hungry", "en")
    assert normalize("Don’t worry", "en") == "do not worry"


def test_expand_alternatives_optional_parts_and_ruby():
    assert set(expand_alternatives("Je m'appelle (Marie)")) >= {"Je m'appelle", "Je m'appelle Marie"}
    assert set(expand_alternatives("{日本|にほん}に{行|い}きます")) == {"日本に行きます", "にほんにいきます"}


def test_levenshtein():
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("", "abc") == 3
    assert levenshtein("same", "same") == 0


# --------------------------------------------------------------------------- verdicts


def test_exact_match_is_correct():
    assert verdict("je suis étudiant", ["Je suis étudiant."], "fr") == "correct"


def test_missing_accent_is_almost_correct_with_highlight():
    result = check_answer("Je suis alle au marche", ["Je suis allé au marché"], "fr")
    assert result.verdict == "accent"
    assert result.is_correct
    marked = [s.text.strip() for s in result.segments if s.kind == "accent"]
    assert "allé" in " ".join(marked) and "marché" in " ".join(marked)


def test_italian_accent():
    assert verdict("perche no", ["Perché no?"], "it") == "accent"


def test_small_typo_in_long_word_is_tolerated():
    assert verdict("Je voudrais un restaurent", ["Je voudrais un restaurant"], "fr") == "typo"
    assert verdict("bonjuor", ["bonjour"], "fr") == "typo"


def test_wrong_ending_is_not_a_typo():
    # conjugation / agreement errors look like 1-letter typos but are real mistakes
    assert verdict("tu parle français", ["tu parles français"], "fr") == "wrong"
    assert verdict("una ragazzo", ["un ragazzo"], "it") == "wrong"


def test_wrong_article_is_critical():
    assert verdict("le maison", ["la maison"], "fr") == "wrong"


def test_extra_or_missing_words_are_wrong():
    assert verdict("je suis", ["je suis là"], "fr") == "wrong"


def test_typo_tolerance_can_be_disabled():
    assert verdict("bonjuor", ["bonjour"], "fr", typo_tolerance=False) == "wrong"


def test_any_accepted_alternative_matches():
    accepted = ["Comment tu t'appelles ?", "Comment vous appelez-vous ?", "Tu t'appelles comment ?"]
    assert verdict("comment vous appelez vous", accepted, "fr") == "correct"


def test_japanese_kana_or_kanji_accepted():
    accepted = ["{日本|にほん}に{行|い}きます"]
    assert verdict("日本に行きます", accepted, "ja") == "correct"
    assert verdict("にほんにいきます", accepted, "ja") == "correct"
    assert verdict("にほんにいきます。", accepted, "ja") == "correct"


def test_japanese_particle_error_is_wrong():
    assert verdict("わたしがすしをたべます", ["わたしはすしをたべます"], "ja") == "wrong"


def test_japanese_small_slip_in_long_answer_is_typo():
    assert verdict("としょかんでべんきょしました", ["としょかんでべんきょうしました"], "ja") == "typo"


def test_english_answer_for_to_english_direction():
    assert verdict("I'm a student", ["I am a student"], "en") == "correct"


def test_empty_answer_is_wrong():
    assert verdict("   ", ["oui"], "fr") == "wrong"
