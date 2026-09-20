from aiogram.enums import ButtonStyle

from cinegate.bot.admin_callbacks import (
    AdminEditCallback,
    AdminPageCallback,
    AdminSettingCallback,
    AdminTemplateCallback,
)
from cinegate.bot.callbacks import (
    MovieBackCallback,
    MovieSelectCallback,
    QualitySelectCallback,
)
from cinegate.bot.keyboards import (
    build_quality_keyboard,
    build_search_results_keyboard,
)
from cinegate.domain.search import MovieSearchResult


def test_search_result_buttons_use_primary_style_and_compact_callbacks() -> None:
    results = (
        MovieSearchResult(123456789, "Interstellar", 2014, 1.0),
        MovieSearchResult(987654321, "Inception", 2010, 0.9),
    )

    keyboard = build_search_results_keyboard(results, nonce="abc12345")

    assert len(keyboard.inline_keyboard) == 2
    for row in keyboard.inline_keyboard:
        button = row[0]
        assert button.style == ButtonStyle.PRIMARY.value
        assert button.callback_data is not None
        assert len(button.callback_data.encode("utf-8")) <= 64


def test_quality_keyboard_renders_only_supplied_qualities_in_stable_rows() -> None:
    keyboard = build_quality_keyboard(
        ("480p", "720p", "1080p"),
        nonce="abc12345",
        movie_id=123,
    )

    assert [button.text for button in keyboard.inline_keyboard[0]] == ["480p", "720p"]
    assert [button.text for button in keyboard.inline_keyboard[1]] == ["1080p"]
    assert keyboard.inline_keyboard[-1][0].text == "رجوع"

    for row in keyboard.inline_keyboard[:-1]:
        for button in row:
            assert button.style == ButtonStyle.PRIMARY.value
            assert button.callback_data is not None
            assert len(button.callback_data.encode("utf-8")) <= 64


def test_callback_payloads_round_trip_and_stay_under_telegram_limit() -> None:
    payloads = (
        MovieSelectCallback(nonce="abcdefgh", movie_id=9223372036854775807).pack(),
        MovieBackCallback(nonce="abcdefgh").pack(),
        QualitySelectCallback(
            nonce="abcdefgh",
            movie_id=9223372036854775807,
            quality="2160p",
        ).pack(),
    )

    assert all(len(payload.encode("utf-8")) <= 64 for payload in payloads)



def test_admin_callback_payloads_stay_within_telegram_limit() -> None:
    payloads = (
        AdminPageCallback(page="diagnostics").pack(),
        AdminSettingCallback(
            action="edit",
            key="miniapp_init_data_max_age_seconds",
        ).pack(),
        AdminTemplateCallback(
            action="preview",
            key="active_reward_conflict",
        ).pack(),
        AdminEditCallback(action="cancel").pack(),
    )

    assert all(len(payload.encode("utf-8")) <= 64 for payload in payloads)
