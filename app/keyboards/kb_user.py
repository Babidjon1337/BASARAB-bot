from aiogram.types import (
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder


get_contact_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📞 Поделиться номером телефона", request_contact=True)],
    ],
    resize_keyboard=True,
    one_time_keyboard=True,
)


def main_menu_kb(has_cart: bool = False):
    kb = InlineKeyboardBuilder()
    top_row = []

    top_row.append(InlineKeyboardButton(text="🔥 Новинки", callback_data="novinki"))

    kb.row(*top_row)
    kb.row(
        InlineKeyboardButton(text="👠 Женская", callback_data="women"),
        InlineKeyboardButton(text="👞 Мужская", callback_data="men"),
    )
    kb.row(
        InlineKeyboardButton(text="👜 Аксессуары", callback_data="accessories"),
    )
    # Корзина появится сверху слева, если в ней есть товары
    if has_cart:
        kb.row(InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart"))
    return kb.as_markup()


def women_kb(has_cart: bool = False):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🛍️ Вся Женская обувь", callback_data="all_women"))
    kb.row(
        InlineKeyboardButton(text="На каблуке", callback_data="sub_women_heels"),
        InlineKeyboardButton(text="Ботинки и Сапоги", callback_data="sub_women_boots"),
    )
    kb.row(
        InlineKeyboardButton(
            text="Спортивная", callback_data="sportivnaya_obuv_female"
        ),
        InlineKeyboardButton(
            text="Туфли комфорт", callback_data="tufli_comfort_female"
        ),
    )
    kb.row(
        InlineKeyboardButton(text="Босоножки", callback_data="bosonogaya_obuv_female"),
        InlineKeyboardButton(text="Летняя", callback_data="letnaya_obuv_female"),
    )
    kb.row(InlineKeyboardButton(text="Распродажа", callback_data="sale_women"))

    if has_cart:
        kb.row(InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart"))
    kb.row(
        InlineKeyboardButton(
            text="◀️ В главное меню", style="primary", callback_data="back_to_menu"
        )
    )
    return kb.as_markup()


def women_heels_kb(has_cart: bool = False):
    kb = InlineKeyboardBuilder()
    # Сохранены орфографические особенности разработчика 1С (kobluke)
    kb.row(
        InlineKeyboardButton(
            text="Туфли на каблуке", callback_data="tufli_na_kobluke_female"
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="Ботинки на каблуке", callback_data="botinki_na_kabluke_female"
        )
    )
    kb.row(
        InlineKeyboardButton(
            text="Открытая обувь на каблуке",
            callback_data="otkritaya_obuv_na_kobluke_female",
        )
    )

    if has_cart:
        kb.row(InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart"))
    kb.row(
        InlineKeyboardButton(
            text="◀️ Назад к категориям", style="primary", callback_data="menu_women"
        )
    )
    return kb.as_markup()


def women_boots_kb(has_cart: bool = False):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(
            text="Ботинки спорт", callback_data="botinki_sport_female"
        ),
        InlineKeyboardButton(
            text="Ботинки комфорт", callback_data="botinki_comfort_female"
        ),
    )
    kb.row(InlineKeyboardButton(text="Сапоги", callback_data="sapogi_female"))

    if has_cart:
        kb.row(InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart"))
    kb.row(
        InlineKeyboardButton(
            text="◀️ Назад к категориям", style="primary", callback_data="menu_women"
        )
    )
    return kb.as_markup()


def men_kb(has_cart: bool = False):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🛍️ Вся мужская обувь", callback_data="all_men"))
    kb.row(
        InlineKeyboardButton(text="Спортивная", callback_data="sportivnaya_obuv_male"),
        InlineKeyboardButton(text="Туфли комфорт", callback_data="tufli_comfort_male"),
    )
    kb.row(
        InlineKeyboardButton(text="Ботинки", callback_data="sub_men_boots"),
        InlineKeyboardButton(text="Летняя", callback_data="letnaya_obuv_male"),
    )
    kb.row(InlineKeyboardButton(text="Распродажа", callback_data="sale_men"))

    if has_cart:
        kb.row(InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart"))
    kb.row(
        InlineKeyboardButton(
            text="◀️ В главное меню", style="primary", callback_data="back_to_menu"
        )
    )
    return kb.as_markup()


def men_boots_kb(has_cart: bool = False):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Комфорт", callback_data="botinki_comfort_male"))
    kb.row(
        InlineKeyboardButton(text="Классические", callback_data="botinki_classic_male")
    )
    kb.row(InlineKeyboardButton(text="Спортивные", callback_data="botinki_sport_male"))

    if has_cart:
        kb.row(InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart"))
    kb.row(
        InlineKeyboardButton(
            text="◀️ Назад к категориям", style="primary", callback_data="menu_men"
        )
    )
    return kb.as_markup()


def accessories_kb(has_cart: bool = False):
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🛍️ Всe Аксессуары", callback_data="all_accessories")
    )
    kb.row(
        InlineKeyboardButton(text="Носки", callback_data="cat_accessories_socks"),
        InlineKeyboardButton(text="Уход", callback_data="cat_accessories_care"),
        InlineKeyboardButton(text="Стельки", callback_data="cat_accessories_insoles"),
    )

    if has_cart:
        kb.row(InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart"))
    kb.row(
        InlineKeyboardButton(
            text="◀️ В главное меню", style="primary", callback_data="back_to_menu"
        )
    )
    return kb.as_markup()


def back_to_menu_kb(has_cart: bool = False):
    kb = InlineKeyboardBuilder()
    if has_cart:
        kb.row(InlineKeyboardButton(text="🛒 Корзина", callback_data="view_cart"))
    kb.row(
        InlineKeyboardButton(
            text="◀️ Назад", style="primary", callback_data="back_to_menu"
        )
    )
    return kb.as_markup()
