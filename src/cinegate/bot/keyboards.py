from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from cinegate.bot.callbacks import (
    MovieBackCallback,
    MovieSelectCallback,
    QualitySelectCallback,
)
from cinegate.domain.search import MovieSearchResult


def build_search_results_keyboard(
    results: tuple[MovieSearchResult, ...],
    *,
    nonce: str,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=_movie_label(result),
                callback_data=MovieSelectCallback(
                    nonce=nonce,
                    movie_id=result.movie_id,
                ).pack(),
                style=ButtonStyle.PRIMARY,
            )
        ]
        for result in results
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_quality_keyboard(
    qualities: tuple[str, ...],
    *,
    nonce: str,
    movie_id: int,
) -> InlineKeyboardMarkup:
    quality_buttons = [
        InlineKeyboardButton(
            text=quality,
            callback_data=QualitySelectCallback(
                nonce=nonce,
                movie_id=movie_id,
                quality=quality,
            ).pack(),
            style=ButtonStyle.PRIMARY,
        )
        for quality in qualities
    ]

    rows = [
        quality_buttons[index : index + 2]
        for index in range(0, len(quality_buttons), 2)
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="رجوع",
                callback_data=MovieBackCallback(nonce=nonce).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _movie_label(result: MovieSearchResult) -> str:
    if result.year is not None:
        return f"{result.display_title} ({result.year})"
    return result.display_title



def build_reward_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="مشاهدة الإعلان",
                    web_app=WebAppInfo(url=url),
                    style=ButtonStyle.SUCCESS,
                )
            ]
        ]
    )
