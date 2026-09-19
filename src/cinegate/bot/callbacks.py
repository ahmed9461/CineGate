from aiogram.filters.callback_data import CallbackData


class MovieSelectCallback(CallbackData, prefix="m"):
    nonce: str
    movie_id: int


class MovieBackCallback(CallbackData, prefix="b"):
    nonce: str


class QualitySelectCallback(CallbackData, prefix="q"):
    nonce: str
    movie_id: int
    quality: str
