from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def main_menu(mini_app_url="", *, can_open_panel=False) -> InlineKeyboardMarkup | None:
    if not mini_app_url or not can_open_panel:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Event panel", web_app=WebAppInfo(url=mini_app_url)),
            ]
        ]
    )
