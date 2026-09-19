from cinegate.services.text import (
    clean_display_title,
    extract_quality,
    extract_year,
    normalize_title,
)


def test_ampersand_and_word_normalize_equally() -> None:
    assert normalize_title("Fast & Furious 2011") == normalize_title(
        "Fast and Furious 2011"
    )


def test_punctuation_year_quality_and_username_are_normalized() -> None:
    assert normalize_title("Batman: Begins 2005 #1080p @Shahedv_bot") == "batman begins"


def test_extract_year_and_quality() -> None:
    text = "Irish Ashes 2025 #720p"
    assert extract_year(text) == 2025
    assert extract_quality(text) == "720p"


def test_clean_display_title_preserves_words_but_removes_year_quality() -> None:
    assert clean_display_title("Top Gun: Maverick 2022 #1080p") == "Top Gun: Maverick"


def test_underscore_is_treated_as_a_separator() -> None:
    assert normalize_title("Spider_Man 2002") == "spider man"
