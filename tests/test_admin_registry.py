import pytest

from cinegate.admin.registry import (
    AdminValidationError,
    get_setting_definition,
)


def test_movie_delete_duration_accepts_human_friendly_units() -> None:
    definition = get_setting_definition("movie_delete_seconds")

    assert definition.parse("120") == 120
    assert definition.parse("2m") == 120
    assert definition.parse("2 دقيقة") == 120
    assert definition.parse("1h") == 3600


def test_movie_delete_duration_respects_telegram_window_bound() -> None:
    definition = get_setting_definition("movie_delete_seconds")

    with pytest.raises(AdminValidationError):
        definition.parse("2 days")


def test_search_result_limit_is_bounded() -> None:
    definition = get_setting_definition("search_result_limit")

    assert definition.parse("10") == 10
    with pytest.raises(AdminValidationError):
        definition.parse("11")


def test_search_similarity_threshold_is_bounded() -> None:
    definition = get_setting_definition("search_similarity_threshold")

    assert definition.parse("0.32") == 0.32
    with pytest.raises(AdminValidationError):
        definition.parse("0.99")


def test_public_base_url_requires_clean_https_url() -> None:
    definition = get_setting_definition("public_base_url")

    assert (
        definition.parse("https://cinegate.example/")
        == "https://cinegate.example"
    )

    for invalid in (
        "http://cinegate.example",
        "https://user:pass@cinegate.example",
        "https://cinegate.example?token=x",
        "https://cinegate.example/#fragment",
    ):
        with pytest.raises(AdminValidationError):
            definition.parse(invalid)


def test_archive_channel_id_must_be_negative() -> None:
    definition = get_setting_definition("archive_channel_id")

    assert definition.parse("-1001234567890") == -1001234567890
    with pytest.raises(AdminValidationError):
        definition.parse("123456")
