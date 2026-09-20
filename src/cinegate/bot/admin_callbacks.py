from aiogram.filters.callback_data import CallbackData


class AdminPageCallback(CallbackData, prefix="ap"):
    page: str


class AdminSettingCallback(CallbackData, prefix="as"):
    action: str
    key: str


class AdminTemplateCallback(CallbackData, prefix="at"):
    action: str
    key: str


class AdminEditCallback(CallbackData, prefix="ae"):
    action: str
