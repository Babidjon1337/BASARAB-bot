from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters.callback_data import CallbackData


class Pagination(CallbackData, prefix="pag"):
    category: str
    page: int


class CartOption(CallbackData, prefix="cart_opt"):
    action: str
    item_id: str


# 🔥 КОРОТКИЕ КОЛБЭКИ: Используем аббревиатуры (css, csz), чтобы экономить байты
class CartSelectSize(CallbackData, prefix="css"):
    item_id: str


class CartSize(CallbackData, prefix="csz"):
    item_id: str
    s_idx: int  # Индекс размера (0, 1, 2...). -1 если "Без размера"


class MgrOrder(CallbackData, prefix="mgr_o"):
    action: str
    order_id: int
    item_id: int = 0
    size: str = ""


def products_keyboard(
    category: str,
    page: int,
    total_pages: int,
    product_id: str | int,
    has_cart: bool = False,
    has_sizes: bool = True,
    filter_sizes: list = None,  # 🔥 Принимает список выбранных размеров
    **kwargs,
):
    kb = InlineKeyboardBuilder()
    product_id_str = str(product_id)

    if has_sizes:
        kb.row(
            InlineKeyboardButton(
                text="Выбрать размер",
                callback_data=CartSelectSize(item_id=product_id_str).pack(),
            )
        )

    left_page = page - 1 if page > 0 else total_pages - 1
    right_page = page + 1 if page < total_pages - 1 else 0

    kb.row(
        InlineKeyboardButton(
            text="<<<",
            callback_data=Pagination(category=category, page=left_page).pack(),
        ),
        InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"),
        InlineKeyboardButton(
            text=">>>",
            callback_data=Pagination(category=category, page=right_page).pack(),
        ),
    )

    # 🔥 Кнопка фильтра (меняет текст в зависимости от количества выбранных размеров)
    if filter_sizes:
        if len(filter_sizes) == 1:
            filter_btn_text = f"🔎 Поиск: {filter_sizes[0]} размер"
        else:
            filter_btn_text = f"🔎 Поиск: {len(filter_sizes)} размера"
    else:
        filter_btn_text = "🔎 Поиск по размеру"

    if has_cart:
        kb.row(
            InlineKeyboardButton(text=filter_btn_text, callback_data="ask_filter_size"),
            InlineKeyboardButton(text="🛒 В корзину", callback_data="view_cart"),
        )
    else:
        kb.row(
            InlineKeyboardButton(text=filter_btn_text, callback_data="ask_filter_size")
        )

    # 🔥 ЖЕЛЕЗОБЕТОННЫЙ ВОЗВРАТ НАЗАД
    is_accessory = "accessories" in category
    is_female = "female" in category or "women" in category
    is_male = ("male" in category or "men" in category) and not is_female

    if is_accessory:
        back_cb = "menu_accessories"
    elif is_male:
        back_cb = "menu_men"
    else:
        back_cb = "menu_women"

    kb.row(
        InlineKeyboardButton(
            text="◀️ Назад в меню", style="primary", callback_data=back_cb
        )
    )
    return kb.as_markup()


# 🔥 КЛАВИАТУРА ВЫБОРА РАЗМЕРА ДЛЯ ФИЛЬТРА (МУЛЬТИВЫБОР)
def filter_size_keyboard(category: str, selected_sizes: list = None):
    if selected_sizes is None:
        selected_sizes = []

    kb = InlineKeyboardBuilder()
    sizes = ["35", "36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46"]

    buttons = []
    for sz in sizes:
        # Добавляем галочку, если размер уже выбран
        text = f"✅ {sz}" if sz in selected_sizes else sz
        style = f"success" if sz in selected_sizes else None
        buttons.append(
            InlineKeyboardButton(
                text=text, style=style, callback_data=f"toggle_filter_{sz}"
            )
        )

    kb.row(*buttons, width=4)
    kb.row(
        InlineKeyboardButton(text="✅ Применить", callback_data="apply_filter"),
        InlineKeyboardButton(text="❌ Сбросить", callback_data="clear_filter"),
    )
    kb.row(
        InlineKeyboardButton(
            text="◀️ Назад", style="primary", callback_data="cancel_filter"
        ),
    )
    return kb.as_markup()


def select_size_keyboard(product_id: str, sizes_str: str):
    kb = InlineKeyboardBuilder()
    available_sizes = []

    if sizes_str:
        for part in sizes_str.split(","):
            sz = part.split(" (")[0].strip()
            if sz:
                available_sizes.append(sz)

    buttons = []
    if not available_sizes:
        buttons.append(
            InlineKeyboardButton(
                text="Добавить (без размера)",
                callback_data=CartSize(item_id=str(product_id), s_idx=-1).pack(),
            )
        )
    else:
        for idx, sz in enumerate(available_sizes):
            buttons.append(
                InlineKeyboardButton(
                    text=f"{sz}",
                    callback_data=CartSize(item_id=str(product_id), s_idx=idx).pack(),
                )
            )
    kb.row(*buttons, width=3)

    kb.row(
        InlineKeyboardButton(
            text="◀️ Отмена", style="primary", callback_data="cancel_size_selection"
        )
    )
    return kb.as_markup()


def cart_keyboard(cart_items: list):
    kb = InlineKeyboardBuilder()
    for idx, (cart_id, product, size, qty) in enumerate(cart_items, start=1):
        # 🔥 Единая строка: Управление количеством [№ 1] [➖] [1 шт.] [➕] [❌]
        kb.row(
            InlineKeyboardButton(text=f"№ {idx}", callback_data="noop"),
            InlineKeyboardButton(
                text="➖",
                callback_data=CartOption(
                    action="decrease", item_id=str(cart_id)
                ).pack(),
            ),
            InlineKeyboardButton(text=f"{qty} шт.", callback_data="noop"),
            InlineKeyboardButton(
                text="➕",
                callback_data=CartOption(
                    action="increase", item_id=str(cart_id)
                ).pack(),
            ),
            InlineKeyboardButton(
                text="❌",
                callback_data=CartOption(action="remove", item_id=str(cart_id)).pack(),
            ),
        )

    if cart_items:
        kb.row(
            InlineKeyboardButton(
                text="✅ Оформить заказ",
                callback_data=CartOption(action="checkout", item_id="0").pack(),
            )
        )

    kb.row(
        InlineKeyboardButton(
            text="◀️ Назад", style="primary", callback_data="return_from_cart"
        )
    )
    return kb.as_markup()


def checkout_choice_kb(final_price: int, show_bonus_offer: bool):
    kb = InlineKeyboardBuilder()

    kb.row(
        InlineKeyboardButton(
            text=f"✅ Подтвердить заказ за {final_price} руб.",
            callback_data=CartOption(action="confirm_order", item_id="0").pack(),
        )
    )

    # Показываем кнопку бонуса только если человек еще не собрал 3 друзей
    if show_bonus_offer:
        kb.row(
            InlineKeyboardButton(
                text="🎁 Получить +500 бонусов",
                callback_data=CartOption(action="bonus_info", item_id="0").pack(),
            )
        )

    kb.row(
        InlineKeyboardButton(
            text="◀️ Вернуться в корзину", style="primary", callback_data="view_cart"
        )
    )
    return kb.as_markup()


def bonus_info_kb(invite_link: str):
    kb = InlineKeyboardBuilder()

    share_url = f"https://t.me/share/url?url={invite_link}&text=%D0%9F%D1%80%D0%B8%D0%B2%D0%B5%D1%82!%20%D0%A2%D1%83%D1%82%20%D0%B4%D0%B0%D1%80%D1%8F%D1%82%20500%20%D0%B1%D0%BE%D0%BD%D1%83%D1%81%D0%BE%D0%B2%20%D0%BD%D0%B0%20%D0%BA%D0%BB%D0%B0%D1%81%D1%81%D0%BD%D1%83%D1%8E%20%D0%BE%D0%B1%D1%83%D0%B2%D1%8C%20(1%20%D0%B1%D0%BE%D0%BD%D1%83%D1%81%20%3D%201%20%D1%80%D1%83%D0%B1%D0%BB%D1%8C)!"

    kb.row(InlineKeyboardButton(text="🚀 Пригласить друзей", url=share_url))

    kb.row(
        InlineKeyboardButton(
            text="◀️ Назад к оформлению",
            style="primary",
            callback_data=CartOption(action="checkout", item_id="0").pack(),
        )
    )
    return kb.as_markup()









def user_payment_kb(paylink: str = "https://basarab.ru/"):
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="💳 ОПЛАТИТЬ ЗАКАЗ", url=paylink))
    kb.row(
        InlineKeyboardButton(
            text="На главную 🏠", style="primary", callback_data="success_to_menu"
        )
    )
    return kb.as_markup()


