import asyncio
import random
import re
import urllib.parse
import aiohttp
from aiogram import F, Router, Bot
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    BufferedInputFile,
    ReplyKeyboardRemove,
)
from aiogram.exceptions import TelegramBadRequest
from loguru import logger
from sqlalchemy import update

import app.keyboards as kb
import app.database.requests as rq
from app.database.models import User, Order, Store

from app.api import (
    send_user_to_1c,
    check_stock_in_1c,
    send_order_to_1c,
    check_multiple_stocks_in_1c,
    get_delivery_cost_from_1c,
)

user_router = Router()

MAIN_PHOTO = "AgACAgIAAxkBAAMEaVuYAp6UqH4uAAGSRPodM7TMnPkWAAJjDWsbYpbgShLkw88691SlAQADAgADeAADOAQ"
DEFAULT_PHOTO = (
    "AgACAgIAAxkBAANgaV0Eh_seXGonXHfxt4pWcDbppzAAAu0OaxsUqOlK8xNOZ2bmhi8BAAMCAAN5AAM4BA"
)

AUTH_TEXT = (
    "👋 <b>Добро пожаловать в BASARAB!</b>\n\n"
    "Чтобы получить <b>🎁 500 приветственных бонусов (1 бонус = 1 рубль)</b> "
    "на покупки, нам нужно с вами познакомиться!\n\n"
    "👇 <i>Нажмите кнопку «📞 Поделиться номером телефона» внизу экрана "
    "или введите его вручную в формате +79991234567.</i>\n\n"
    "<blockquote>⚠️ <b>Без номера телефона просмотр каталога и оформление заказов невозможны.</b></blockquote>"
)


class PhoneState(StatesGroup):
    awaiting_phone = State()


class CheckoutState(StatesGroup):
    waiting_for_city = State()


# ==========================================
# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ МЕДИА ---
# ==========================================


async def get_product_media_from_urls_fallback(urls: list) -> list:
    """Скачивает картинки вручную, жестко проверяя их валидность (защита от IMAGE_PROCESS_FAILED)."""
    results = []
    async with aiohttp.ClientSession() as session:
        for url in urls:
            if isinstance(url, str) and (url.startswith("AgA") or url == DEFAULT_PHOTO):
                results.append(url)
                continue

            orig_url = url
            if isinstance(url, str) and "image_proxy.php?url=" in url:
                orig_url = urllib.parse.unquote(url.split("image_proxy.php?url=")[1])

            proxy_url = f"https://basarab.ru/15/image_proxy.php?url={orig_url}"
            media_added = False

            for download_url in [proxy_url, orig_url]:
                try:
                    async with session.get(download_url, timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            # 🔥 Защита от битых файлов: проверяем сигнатуры реальных картинок
                            if len(data) > 1024 and (
                                data.startswith(b"\xff\xd8")
                                or data.startswith(b"\x89PNG")
                                or (data.startswith(b"RIFF") and b"WEBP" in data[8:12])
                            ):
                                # 🔥 ДОБАВЛЕН RANDOM В ИМЯ: чтобы телеграм не путался при отправке альбомов
                                results.append(
                                    BufferedInputFile(
                                        data,
                                        filename=f"img_{random.randint(10000, 99999)}.jpg",
                                    )
                                )
                                media_added = True
                                break
                except Exception:
                    pass

            if not media_added:
                results.append(
                    DEFAULT_PHOTO
                )  # Если файл битый или не скачался, ставим заглушку

    return results


async def cache_file_ids_in_db(product_id: str, messages: list):
    """Извлекает file_id из отправленных сообщений и сохраняет в БД."""
    file_ids = []
    for msg in messages:
        if msg and hasattr(msg, "photo") and msg.photo:
            fid = msg.photo[-1].file_id
            # 🔥 Игнорируем заглушку, чтобы она не сохранилась навсегда
            if fid != DEFAULT_PHOTO and fid != MAIN_PHOTO:
                file_ids.append(fid)

    if file_ids:
        new_file_id_str = "|".join(file_ids)
        await rq.update_product_file_id(product_id, new_file_id_str)


async def clear_media(chat_id: int, state: FSMContext, bot: Bot):
    data = await state.get_data()
    old_media_ids = data.get("cart_media_ids", []) + data.get("product_media_ids", [])

    if old_media_ids:
        try:
            await bot.delete_messages(chat_id=chat_id, message_ids=old_media_ids)
        except Exception as e:
            for mid in old_media_ids:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=mid)
                except Exception:
                    pass
        await state.update_data(cart_media_ids=[], product_media_ids=[])


async def send_menu_page(
    callback: CallbackQuery, state: FSMContext, bot: Bot, text: str, markup
):
    await clear_media(callback.message.chat.id, state, bot)
    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(media=MAIN_PHOTO, caption=text), reply_markup=markup
        )
    except TelegramBadRequest:
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        await callback.message.answer_photo(
            photo=MAIN_PHOTO, caption=text, reply_markup=markup
        )


start_text = (
    "<b>Добро пожаловать в мир BASARAB!</b>\n\n"
    "Мы создаем красивую обувь с заботой о вашем здоровье. "
    "Натуральные материалы, идеальная колодка и стиль, продуманный до мелочей.\n\n"
    "В этом онлайн магазине вы можете:\n"
    "👟 Найти идеальную пару за 2 минуты\n"
    "🔥 Узнать о секретных акциях и новинках\n"
    "🎁 <b>Получить спеццену</b> за рекомендацию друзьям\n\n"
)


@user_router.message(Command(commands=["start", "menu"]))
async def cmd_start(
    message: Message, command: CommandObject, state: FSMContext, bot: Bot
):
    await clear_media(message.chat.id, state, bot)
    state_data = await state.get_state()
    if state_data == PhoneState.awaiting_phone:
        await message.answer_photo(
            photo=MAIN_PHOTO, caption=AUTH_TEXT, reply_markup=kb.get_contact_kb
        )
        return

    is_new = await rq.register_user(
        message.from_user.id, message.from_user.username, command.args
    )
    user_obj = await rq.get_user(message.from_user.id)

    if is_new or not user_obj.phone:
        await message.answer_photo(
            photo=MAIN_PHOTO, caption=AUTH_TEXT, reply_markup=kb.get_contact_kb
        )
        await state.set_state(PhoneState.awaiting_phone)
        return

    await state.update_data(last_location="main_menu", last_menu="back_to_menu")
    cart_items = await rq.get_cart(message.from_user.id)
    has_cart = len(cart_items) > 0

    await message.answer_photo(
        photo=MAIN_PHOTO,
        caption=start_text + "👇 <b>С чего начнем? Выберите раздел в меню:</b>",
        reply_markup=kb.main_menu_kb(has_cart),
    )


@user_router.message(PhoneState.awaiting_phone)
async def get_phone(message: Message, state: FSMContext):
    raw_phone = message.contact.phone_number if message.contact else message.text
    if raw_phone:
        digits = "".join(filter(str.isdigit, raw_phone))
        if len(digits) >= 10:
            if len(digits) == 11 and digits.startswith(("7", "8")):
                phone = "+7" + digits[1:]
            elif len(digits) == 10:
                phone = "+7" + digits
            else:
                phone = "+" + digits

            await state.clear()
            await message.answer(
                "Спасибо! Ваш номер телефона сохранен.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await asyncio.sleep(1)

            await send_user_to_1c(
                message.from_user.id, message.from_user.full_name, phone
            )
            await rq.update_user_1c_data(message.from_user.id, phone)

            await state.update_data(last_location="main_menu", last_menu="back_to_menu")
            cart_items = await rq.get_cart(message.from_user.id)
            has_cart = len(cart_items) > 0

            await message.answer_photo(
                photo=MAIN_PHOTO,
                caption="👇 <b>С чего начнем? Выберите раздел в меню:</b>",
                reply_markup=kb.main_menu_kb(has_cart),
            )
        else:
            await message.answer(
                "Пожалуйста, введите корректный номер телефона в формате +79991234567."
            )
    else:
        await message.answer("Пожалуйста, поделитесь своим номером телефона.")


@user_router.callback_query(F.data.startswith("back_to_menu"))
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(last_location="main_menu", last_menu="back_to_menu")
    cart_items = await rq.get_cart(callback.from_user.id)
    text = start_text + "👇 <b>С чего начнем? Выберите раздел в меню:</b>"
    await send_menu_page(
        callback, state, bot, text, kb.main_menu_kb(len(cart_items) > 0)
    )


@user_router.callback_query(F.data == "success_to_menu")
async def success_to_menu_callback(
    callback: CallbackQuery, state: FSMContext, bot: Bot
):
    await callback.answer()
    await state.update_data(last_location="main_menu", last_menu="back_to_menu")

    current_markup = callback.message.reply_markup
    if current_markup:
        new_inline_keyboard = []
        for row in current_markup.inline_keyboard:
            new_row = [btn for btn in row if btn.callback_data != "success_to_menu"]
            if new_row:
                new_inline_keyboard.append(new_row)
        try:
            await callback.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(inline_keyboard=new_inline_keyboard)
            )
        except Exception:
            pass

    cart_items = await rq.get_cart(callback.from_user.id)
    text = start_text + "👇 <b>С чего начнем? Выберите раздел в меню:</b>"

    await callback.message.answer_photo(
        photo=MAIN_PHOTO,
        caption=text,
        reply_markup=kb.main_menu_kb(len(cart_items) > 0),
    )


@user_router.callback_query(F.data == "novinki")
async def novinki_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(last_location="novinki", last_menu="novinki")
    cart_items = await rq.get_cart(callback.from_user.id)
    text = "Раздел 'Новинки' в разработке..."
    await send_menu_page(
        callback, state, bot, text, kb.back_to_menu_kb(len(cart_items) > 0)
    )


@user_router.callback_query(F.data == "women")
async def women_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(last_location="women", last_menu="women")
    cart_items = await rq.get_cart(callback.from_user.id)
    text = "<b>👠 Женская обувь</b>\nВыберите категорию:"
    await send_menu_page(callback, state, bot, text, kb.women_kb(len(cart_items) > 0))


@user_router.callback_query(F.data == "men")
async def men_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(last_location="men", last_menu="men")
    cart_items = await rq.get_cart(callback.from_user.id)
    text = "<b>👞 Мужская обувь</b>\nВыберите категорию:"
    await send_menu_page(callback, state, bot, text, kb.men_kb(len(cart_items) > 0))


@user_router.callback_query(F.data == "accessories")
async def accessories_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(last_location="accessories", last_menu="accessories")
    cart_items = await rq.get_cart(callback.from_user.id)
    text = "<b>👜 Аксессуары</b>\nВыберите категорию:"
    await send_menu_page(
        callback, state, bot, text, kb.accessories_kb(len(cart_items) > 0)
    )


@user_router.callback_query(F.data.in_(["sale_women", "sale_men"]))
async def sale_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(last_location=callback.data, last_menu=callback.data)
    cart_items = await rq.get_cart(callback.from_user.id)
    text = "Раздел '🤩 Распродажа' в разработке..."
    await send_menu_page(
        callback, state, bot, text, kb.back_to_menu_kb(len(cart_items) > 0)
    )


@user_router.callback_query(F.data.startswith("sub_"))
async def subcategory_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(last_location=callback.data, last_menu=callback.data)
    cart_items = await rq.get_cart(callback.from_user.id)
    has_cart = len(cart_items) > 0

    data = callback.data
    if data == "sub_women_heels":
        text, markup = (
            "<b>👠 Женская обувь на каблуке</b>\nВыберите категорию:",
            kb.women_heels_kb(has_cart),
        )
    elif data == "sub_women_boots":
        text, markup = (
            "<b>👢 Женские Ботинки и Сапоги</b>\nВыберите категорию:",
            kb.women_boots_kb(has_cart),
        )
    elif data == "sub_men_boots":
        text, markup = (
            "<b>👞 Мужские Ботинки</b>\nВыберите категорию:",
            kb.men_boots_kb(has_cart),
        )
    else:
        text, markup = "Раздел в разработке...", kb.back_to_menu_kb(has_cart)

    await send_menu_page(callback, state, bot, text, markup)


@user_router.callback_query(F.data.startswith("menu_"))
async def menu_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    await state.update_data(last_location=callback.data, last_menu=callback.data)
    cart_items = await rq.get_cart(callback.from_user.id)
    has_cart = len(cart_items) > 0

    data = callback.data
    if data == "menu_women":
        text, markup = "<b>👠 Женская обувь</b>\nВыберите категорию:", kb.women_kb(
            has_cart
        )
    elif data == "menu_men":
        text, markup = "<b>👞 Мужская обувь</b>\nВыберите категорию:", kb.men_kb(
            has_cart
        )
    elif data == "menu_accessories":
        text, markup = (
            "<b>👜 Аксессуары</b>\nВыберите категорию:",
            kb.accessories_kb(has_cart),
        )
    else:
        text, markup = "Раздел в разработке...", kb.back_to_menu_kb(has_cart)

    await send_menu_page(callback, state, bot, text, markup)


async def send_product_page(
    callback: CallbackQuery,
    product: Store,
    page: int,
    total_pages: int,
    category_code: str,
    state: FSMContext,
    bot: Bot,
):
    await state.update_data(last_location="product")

    if product.sizes and product.sizes.strip():
        display_sizes = [
            s.split(" (")[0].strip() for s in product.sizes.split(",") if s.strip()
        ]
        size_text = f"📏 <b>Доступные размеры:</b>\n<blockquote>{', '.join(display_sizes)}</blockquote>\n\n"
        has_sizes = True
    else:
        size_text = f"🔴 <b>Нет в наличии (распродано)</b>\n\n"
        has_sizes = False

    cart_items = await rq.get_cart(callback.from_user.id)
    has_cart = len(cart_items) > 0

    data = await state.get_data()
    last_menu = data.get("last_menu", "back_to_menu")
    filter_sizes = data.get("filter_sizes", [])

    keyboard = kb.products_keyboard(
        category=category_code,
        page=page,
        total_pages=total_pages,
        product_id=product.id,
        last_menu=last_menu,
        has_cart=has_cart,
        has_sizes=has_sizes,
        filter_sizes=filter_sizes,
    )

    def get_caption(is_photo=False):
        price_str = f"{product.price:,}".replace(",", ".")
        size_block = f"{size_text}💰 <b>Цена:</b> {price_str} руб"
        max_len = 950 if is_photo else 3900

        base_caption = f"<b>{product.name}</b>{size_block}"
        desc = f"\n\n{product.description}\n\n" or ""

        if len(base_caption) + len(desc) > max_len:
            desc = re.sub(r"<[^>]+>", "", desc)
            allowed = max_len - len(base_caption) - 5
            if allowed > 0:
                desc = desc[:allowed]
                desc = desc.rsplit(" ", 1)[0] + "..." if " " in desc else desc + "..."
            else:
                desc = ""

        return f"<b>{product.name}</b>{desc}{size_block}"

    # 🔥 1. ВСЕГДА СОБИРАЕМ ОРИГИНАЛЬНЫЕ URL
    raw_photos = [
        p.strip().replace("\\", "/") for p in product.photo.split("|") if p.strip()
    ]
    valid_photos = []
    for p in raw_photos:
        if not p.startswith("http") and not p.startswith("AgA"):
            p = "https://" + p
        if p not in valid_photos:
            valid_photos.append(p)
    valid_photos = valid_photos[:7]
    if not valid_photos:
        valid_photos = [DEFAULT_PHOTO]

    url_sources = []
    for p in valid_photos:
        if p.startswith("AgA") or p == DEFAULT_PHOTO:
            url_sources.append(p)
        else:
            url_sources.append(f"https://basarab.ru/15/image_proxy.php?url={p}")

    # 🔥 2. ПРОВЕРЯЕМ БАЗУ ДАННЫХ И ИГНОРИРУЕМ "ОТРАВЛЕННЫЕ" ЗАГЛУШКАМИ ФАЙЛЫ
    cached_fids = []
    if hasattr(product, "file_id") and product.file_id:
        cached_fids = [
            f.strip()
            for f in product.file_id.split("|")
            if f.strip() and f.strip() not in (MAIN_PHOTO, DEFAULT_PHOTO)
        ]

    # Формируем источники для быстрого пути (FIDs, если есть)
    fast_sources = cached_fids if cached_fids else url_sources

    # Убираем дубликаты
    unique_fast_sources = []
    seen_ms = set()
    for m in fast_sources:
        if m not in seen_ms:
            seen_ms.add(m)
            unique_fast_sources.append(m)
    fast_sources = unique_fast_sources

    is_album = len(fast_sources) > 1
    sent_messages = []
    old_media_ids = data.get("product_media_ids", [])
    was_album = len(old_media_ids) > 0
    can_cache = not bool(cached_fids)

    async def _send_single(sources, is_edit_allowed):
        media_item = sources[0]
        cap = get_caption(is_photo=True)
        if is_edit_allowed:
            try:
                msg = await callback.message.edit_media(
                    media=InputMediaPhoto(media=media_item, caption=cap),
                    reply_markup=keyboard,
                )
                return [msg]
            except TelegramBadRequest as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    return []
                if "message to edit not found" in err:
                    pass
        # Fallback to Send New
        msg = await callback.message.answer_photo(
            photo=media_item, caption=cap, reply_markup=keyboard
        )
        return [msg]

    try:
        # 🚀 БЫСТРЫЙ ПУТЬ: Пробуем отправить (file_id или URL)
        if is_album:
            album_inputs = [InputMediaPhoto(media=m) for m in fast_sources]
            sent_messages = await callback.message.answer_media_group(
                media=album_inputs
            )
            await callback.message.answer(
                text=get_caption(is_photo=False), reply_markup=keyboard
            )
        else:
            sent_messages = await _send_single(
                fast_sources, is_edit_allowed=not was_album
            )

    except TelegramBadRequest as e:
        logger.warning(
            f"Быстрая отправка не удалась (возможно битый file_id), качаем вручную: {e}"
        )
        # 🐌 МЕДЛЕННЫЙ ПУТЬ: Ручное скачивание с заглушками (Используем оригинальные URL!)
        manual_media = await get_product_media_from_urls_fallback(url_sources)
        can_cache = True  # Если скачаем успешно, вылечим базу!

        unique_manual = []
        seen_mm = set()
        for m in manual_media:
            if isinstance(m, str):
                if m in seen_mm:
                    continue
                seen_mm.add(m)
            unique_manual.append(m)
        manual_media = unique_manual
        is_album_manual = len(manual_media) > 1

        if any(m == DEFAULT_PHOTO for m in manual_media):
            can_cache = False

        try:
            if is_album_manual:
                album_inputs = [InputMediaPhoto(media=m) for m in manual_media]
                sent_messages = await callback.message.answer_media_group(
                    media=album_inputs
                )
                await callback.message.answer(
                    text=get_caption(is_photo=False), reply_markup=keyboard
                )
            else:
                sent_messages = await _send_single(
                    manual_media, is_edit_allowed=not was_album
                )
        except Exception as e2:
            logger.error(
                f"Ручное скачивание альбома провалилось. Ставим заглушку! {e2}"
            )
            is_album_manual = False
            can_cache = False
            sent_messages = await _send_single(
                [DEFAULT_PHOTO], is_edit_allowed=not was_album
            )

    # Очищаем старые сообщения
    if was_album and old_media_ids:
        try:
            await bot.delete_messages(
                chat_id=callback.message.chat.id, message_ids=old_media_ids
            )
        except Exception:
            pass
    if is_album or was_album:
        try:
            await callback.message.delete()
        except Exception:
            pass

    if is_album or (not is_album and len(fast_sources) > 1):
        await state.update_data(product_media_ids=[m.message_id for m in sent_messages])
    else:
        if was_album:
            await state.update_data(product_media_ids=[])

    if can_cache and sent_messages:
        await cache_file_ids_in_db(product.id, sent_messages)


@user_router.callback_query(
    F.data.startswith("cat_")
    | F.data.startswith("all_")
    | F.data.endswith("_female")
    | F.data.endswith("_male")
)
async def show_category_products(callback: CallbackQuery, state: FSMContext, bot: Bot):
    category_code = callback.data

    await state.update_data(filter_sizes=[], draft_filter_sizes=[])

    product_ids = await rq.get_category_ids(category_code)
    if not product_ids:
        return await callback.answer("Товары не найдены", show_alert=True)

    if category_code.startswith("all_"):
        random.shuffle(product_ids)

    await callback.answer()
    await state.update_data(
        product_ids=product_ids, current_category=category_code, current_page=0
    )
    await send_product_page(
        callback,
        await rq.get_product_by_id(product_ids[0]),
        0,
        len(product_ids),
        category_code,
        state,
        bot,
    )


@user_router.callback_query(kb.Pagination.filter())
async def paginate_products(
    callback: CallbackQuery, callback_data: kb.Pagination, state: FSMContext, bot: Bot
):
    category_code = callback_data.category
    page = callback_data.page
    data = await state.get_data()
    product_ids = data.get("product_ids", [])
    filter_sizes = data.get("filter_sizes", [])

    if not product_ids:
        product_ids = await rq.get_category_ids(
            category_code, size_filters=filter_sizes
        )
        if category_code.startswith("all_"):
            random.shuffle(product_ids)
        await state.update_data(product_ids=product_ids)

    if not product_ids:
        return await callback.answer("Ошибка доступа", show_alert=True)
    await callback.answer()

    if page >= len(product_ids):
        page = 0
    elif page < 0:
        page = len(product_ids) - 1

    await state.update_data(current_page=page)
    await send_product_page(
        callback,
        await rq.get_product_by_id(product_ids[page]),
        page,
        len(product_ids),
        category_code,
        state,
        bot,
    )


@user_router.callback_query(F.data == "ask_filter_size")
async def ask_filter_size(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await clear_media(callback.message.chat.id, state, bot)
    try:
        await callback.message.delete()
    except:
        pass

    data = await state.get_data()
    category = data.get("current_category", "all")
    filter_sizes = data.get("filter_sizes", [])

    await state.update_data(
        draft_filter_sizes=filter_sizes.copy() if filter_sizes else []
    )

    text = (
        "🔎 <b>Настройка поиска по размеру</b>\n\n"
        "Выберите один или сразу несколько размеров. Мы покажем только те модели, "
        "которые есть в наличии.\n\n"
        "<i>Нажимайте на кнопки, чтобы выбрать нужные размеров, а затем нажмите «Применить».</i>"
    )
    markup = kb.filter_size_keyboard(category, filter_sizes)

    await callback.message.answer(text, reply_markup=markup)


@user_router.callback_query(F.data.startswith("toggle_filter_"))
async def toggle_filter_size(callback: CallbackQuery, state: FSMContext):
    size = callback.data.replace("toggle_filter_", "")
    data = await state.get_data()
    draft_filters = data.get("draft_filter_sizes", [])

    if size in draft_filters:
        draft_filters.remove(size)
    else:
        draft_filters.append(size)

    await state.update_data(draft_filter_sizes=draft_filters)

    category = data.get("current_category", "all")
    markup = kb.filter_size_keyboard(category, draft_filters)

    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest:
        pass
    await callback.answer()


@user_router.callback_query(F.data == "apply_filter")
async def apply_filter_size(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    category_code = data.get("current_category", "all")
    draft_filters = data.get("draft_filter_sizes", [])

    await state.update_data(filter_sizes=draft_filters)

    product_ids = await rq.get_category_ids(category_code, size_filters=draft_filters)

    if not product_ids:
        return await callback.answer(
            "В этой категории нет товаров выбранных размеров 😔", show_alert=True
        )

    await callback.answer("✅ Фильтр применен")

    if category_code.startswith("all_"):
        random.shuffle(product_ids)

    await state.update_data(product_ids=product_ids, current_page=0)

    await send_product_page(
        callback,
        await rq.get_product_by_id(product_ids[0]),
        0,
        len(product_ids),
        category_code,
        state,
        bot,
    )


@user_router.callback_query(F.data == "clear_filter")
async def clear_filter_size(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await state.update_data(filter_sizes=[], draft_filter_sizes=[])
    data = await state.get_data()
    category_code = data.get("current_category", "all")

    product_ids = await rq.get_category_ids(category_code)

    if not product_ids:
        return await callback.answer("Товары не найдены", show_alert=True)

    if category_code.startswith("all_"):
        random.shuffle(product_ids)

    await state.update_data(product_ids=product_ids, current_page=0)
    await callback.answer("❌ Фильтр сброшен")

    await send_product_page(
        callback,
        await rq.get_product_by_id(product_ids[0]),
        0,
        len(product_ids),
        category_code,
        state,
        bot,
    )


@user_router.callback_query(F.data == "cancel_filter")
async def cancel_filter(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    page = data.get("current_page", 0)
    category_code = data.get("current_category", "all")
    product_ids = data.get("product_ids", [])

    if not product_ids:
        try:
            await callback.message.delete()
        except:
            pass
        return await callback.answer(
            "Сессия устарела. Откройте меню заново.", show_alert=True
        )

    await callback.answer()

    await send_product_page(
        callback,
        await rq.get_product_by_id(product_ids[page]),
        page,
        len(product_ids),
        category_code,
        state,
        bot,
    )


@user_router.callback_query(kb.CartSelectSize.filter())
async def process_select_size(
    callback: CallbackQuery, callback_data: kb.CartSelectSize
):
    product = await rq.get_product_by_id(callback_data.item_id)
    if not product:
        return await callback.answer("Товар не найден", show_alert=True)

    await callback.answer()

    markup = kb.select_size_keyboard(product.id, product.sizes)
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest:
        pass


@user_router.callback_query(F.data == "cancel_size_selection")
async def cancel_size_selection(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    page = data.get("current_page", 0)
    category_code = data.get("current_category", "all")
    product_ids = data.get("product_ids", [])
    last_menu = data.get("last_menu", "back_to_menu")
    filter_sizes = data.get("filter_sizes", [])

    if not product_ids:
        await callback.message.edit_reply_markup(reply_markup=None)
        return await callback.answer(
            "Сессия устарела. Откройте меню заново.", show_alert=True
        )

    await callback.answer()

    product = await rq.get_product_by_id(product_ids[page])

    cart_items = await rq.get_cart(callback.from_user.id)
    has_cart = len(cart_items) > 0
    has_sizes = bool(product.sizes and product.sizes.strip())

    markup = kb.products_keyboard(
        category=category_code,
        page=page,
        total_pages=len(product_ids),
        product_id=product.id,
        last_menu=last_menu,
        has_cart=has_cart,
        has_sizes=has_sizes,
        filter_sizes=filter_sizes,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest:
        pass


@user_router.callback_query(kb.CartSize.filter())
async def add_item_with_size_to_cart(
    callback: CallbackQuery, callback_data: kb.CartSize, state: FSMContext, bot: Bot
):
    product_id = callback_data.item_id
    product = await rq.get_product_by_id(product_id)
    if not product:
        return await callback.answer("Товар не найден", show_alert=True)

    size = "Без размера"
    if callback_data.s_idx != -1 and product.sizes:
        available_sizes = []
        for part in product.sizes.split(","):
            sz = part.split(" (")[0].strip()
            if sz:
                available_sizes.append(sz)

        if 0 <= callback_data.s_idx < len(available_sizes):
            size = available_sizes[callback_data.s_idx]

    cart_items = await rq.get_cart(callback.from_user.id)
    already_in_cart = sum(
        qty for _, p, s, qty in cart_items if p.id == product_id and s == size
    )

    stock_info = await check_stock_in_1c(product_id, size)

    has_stock = stock_info.get("available", True)
    actual_stock = 0

    if stock_info.get("success"):
        sizes_list = stock_info.get("sizes", [])
        available_sizes_db = []
        has_stock = False

        for sz_info in sizes_list:
            stock_qty = int(sz_info.get("stock", 0))
            sz_name = str(sz_info.get("size"))

            if stock_qty > 0:
                available_sizes_db.append(f"{sz_name} ({stock_qty}шт)")

            if sz_name == size or size == "Без размера":
                actual_stock = stock_qty
                if stock_qty > already_in_cart:
                    has_stock = True

        new_sizes_str = ", ".join(available_sizes_db)
        await rq.update_product_sizes(product_id, new_sizes_str)
        product.sizes = new_sizes_str

    if not has_stock:
        if already_in_cart > 0 and stock_info.get("success"):
            await callback.answer(
                f"❌ Достигнут лимит!\n\nНа складе доступно всего {actual_stock} шт. (Размер: {size}).\nВы уже добавили их все в корзину.",
                show_alert=True,
            )
        elif not product.sizes:
            await callback.answer(
                "К сожалению, этот товар полностью распродан 😔", show_alert=True
            )
        else:
            await callback.answer(
                f"К сожалению, размер {size} только что раскупили 😔", show_alert=True
            )

        data = await state.get_data()
        product_ids = data.get("product_ids", [])
        category_code = data.get("current_category", "all")
        page = data.get("current_page", 0)
        if not product_ids:
            product_ids = [product_id]

        await send_product_page(
            callback, product, page, len(product_ids), category_code, state, bot
        )
        return

    await rq.add_to_cart(callback.from_user.id, product_id, size)
    msg = (
        f"✅ Размер {size} добавлен в корзину!"
        if size != "Без размера"
        else "✅ Добавлено в корзину!"
    )

    await callback.answer(msg, show_alert=True)

    data = await state.get_data()
    product_ids = data.get("product_ids", [])
    category_code = data.get("current_category", "all")
    page = data.get("current_page", 0)
    last_menu = data.get("last_menu", "back_to_menu")
    filter_sizes = data.get("filter_sizes", [])

    if not product_ids:
        product_ids = [product_id]

    cart_items = await rq.get_cart(callback.from_user.id)
    has_cart = len(cart_items) > 0
    has_sizes = bool(product.sizes and product.sizes.strip())

    markup = kb.products_keyboard(
        category=category_code,
        page=page,
        total_pages=len(product_ids),
        product_id=product.id,
        last_menu=last_menu,
        has_cart=has_cart,
        has_sizes=has_sizes,
        filter_sizes=filter_sizes,
    )
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest:
        pass


# ==========================================
# --- КОРЗИНА И ОФОРМЛЕНИЕ ЗАКАЗА ---
# ==========================================


async def edit_cart_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Обновляет только текст, если пользователь меняет количество (увеличивает/уменьшает без удаления)"""
    cart_items = await rq.get_cart(callback.from_user.id)
    if not cart_items:
        # Если корзина пуста, отправляем на полную перерисовку
        await view_cart(callback, state, bot)
        return

    total_price = sum(store_obj.price * qty for _, store_obj, _, qty in cart_items)
    text = "🛒 <b>Ваша корзина:</b>\n\n"

    for idx, (cart_id, product, size, qty) in enumerate(cart_items, start=1):
        text += f"<b>{idx}. {product.name}</b>\n"
        if size and size != "Без размера":
            text += f"└ Размер: {size}\n"
        item_total_price = f"{product.price * qty:,}".replace(",", ".")
        price_str = f"{product.price:,}".replace(",", ".")
        text += f"└ Цена: {qty} шт. x {price_str} руб. = {item_total_price} руб.\n\n"

    text += f"💰 <b>Итого к оплате: {f'{total_price:,}'.replace(',', '.')} руб.</b>"

    try:
        if callback.message.text:
            await callback.message.edit_text(
                text=text, reply_markup=kb.cart_keyboard(cart_items)
            )
        else:
            await callback.message.edit_caption(
                caption=text, reply_markup=kb.cart_keyboard(cart_items)
            )
    except TelegramBadRequest:
        pass


@user_router.callback_query(F.data == "view_cart")
async def view_cart(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await callback.answer()
    cart_items = await rq.get_cart(callback.from_user.id)

    # 🔥 ВСЕГДА УДАЛЯЕМ СТАРЫЕ МЕДИА И ТЕКУЩЕЕ СООБЩЕНИЕ ПРИ ОТКРЫТИИ КОРЗИНЫ
    await clear_media(callback.message.chat.id, state, bot)
    try:
        await callback.message.delete()
    except Exception:
        pass

    if not cart_items:
        text = (
            "🛒 <b>Ваша корзина пуста</b>\n\nСамое время выбрать что-нибудь стильное!"
        )
        msg = await callback.message.answer_photo(
            photo=MAIN_PHOTO, caption=text, reply_markup=kb.cart_keyboard([])
        )
        await state.update_data(cart_media_ids=[msg.message_id])
        return

    total_price = sum(store_obj.price * qty for _, store_obj, _, qty in cart_items)
    text = "🛒 <b>Ваша корзина:</b>\n\n"

    seen_products = set()
    cart_media_fast = []
    cart_media_urls = []

    for idx, (cart_id, product, size, qty) in enumerate(cart_items, start=1):
        text += f"<b>{idx}. {product.name}</b>\n"
        if size and size != "Без размера":
            text += f"└ Размер: {size}\n"
        item_total_price = f"{product.price * qty:,}".replace(",", ".")
        price_str = f"{product.price:,}".replace(",", ".")
        text += f"└ Цена: {qty} шт. x {price_str} руб. = {item_total_price} руб.\n\n"

        if product.id not in seen_products:
            seen_products.add(product.id)
            if len(cart_media_fast) < 7:
                # Игнорируем сохраненные заглушки
                fid = None
                if hasattr(product, "file_id") and product.file_id:
                    fid_list = [
                        f.strip()
                        for f in product.file_id.split("|")
                        if f.strip() and f.strip() not in (MAIN_PHOTO, DEFAULT_PHOTO)
                    ]
                    if fid_list:
                        fid = fid_list[0]

                raw_p = (
                    product.photo.split("|")[0].strip().replace("\\", "/")
                    if product.photo
                    else ""
                )
                if not raw_p.startswith("http") and not raw_p.startswith("AgA"):
                    raw_p = "https://" + raw_p
                if not raw_p:
                    raw_p = DEFAULT_PHOTO

                if raw_p.startswith("AgA") or raw_p == DEFAULT_PHOTO:
                    url_src = raw_p
                else:
                    url_src = f"https://basarab.ru/15/image_proxy.php?url={raw_p}"

                # Сохраняем оригинальные урлы для фоллбэка
                cart_media_urls.append(url_src)
                cart_media_fast.append(fid if fid else url_src)

    text += f"💰 <b>Итого к оплате: {f'{total_price:,}'.replace(',', '.')} руб.</b>"

    if not cart_media_fast:
        cart_media_fast = [DEFAULT_PHOTO]
        cart_media_urls = [DEFAULT_PHOTO]

    async def _send_cart(sources):
        # Убираем дубликаты
        unique_sources = []
        seen_strings = set()
        for m in sources:
            if isinstance(m, str):
                if m in seen_strings:
                    continue
                seen_strings.add(m)
            unique_sources.append(m)

        inputs = [InputMediaPhoto(media=m) for m in unique_sources]
        is_album_local = len(unique_sources) > 1

        if is_album_local:
            msgs = await callback.message.answer_media_group(media=inputs)
            msg = await callback.message.answer(
                text=text, reply_markup=kb.cart_keyboard(cart_items)
            )
            # 🔥 ОБЯЗАТЕЛЬНО сохраняем и фото, И ТЕКСТОВОЕ СООБЩЕНИЕ, чтобы потом удалить всё
            media_ids = [m.message_id for m in msgs] + [msg.message_id]
            await state.update_data(cart_media_ids=media_ids)
        else:
            media_item = inputs[0].media
            msg = await callback.message.answer_photo(
                photo=media_item,
                caption=text,
                reply_markup=kb.cart_keyboard(cart_items),
            )
            await state.update_data(cart_media_ids=[msg.message_id])

    try:
        # 🚀 Пробуем отправить быстрым путем
        await _send_cart(cart_media_fast)
    except TelegramBadRequest as e:
        logger.warning(
            f"Быстрая загрузка корзины не удалась. Скачиваем проблемные фото: {e}"
        )
        # 🐌 Медленный путь
        manual_media = await get_product_media_from_urls_fallback(cart_media_urls)
        try:
            await _send_cart(manual_media)
        except Exception as e2:
            logger.error(f"Медленный путь тоже упал: {e2}")
            msg = await callback.message.answer_photo(
                photo=DEFAULT_PHOTO,
                caption=text,
                reply_markup=kb.cart_keyboard(cart_items),
            )
            await state.update_data(cart_media_ids=[msg.message_id])


@user_router.callback_query(F.data == "return_from_cart")
async def return_from_cart_callback(
    callback: CallbackQuery, state: FSMContext, bot: Bot
):
    await callback.answer()
    await clear_media(callback.message.chat.id, state, bot)

    data = await state.get_data()
    last_loc = data.get("last_location", "main_menu")
    cart_items = await rq.get_cart(callback.from_user.id)
    has_cart = len(cart_items) > 0

    if last_loc == "product":
        product_ids = data.get("product_ids", [])
        if product_ids:
            page = data.get("current_page", 0)
            category_code = data.get("current_category", "all")
            product = await rq.get_product_by_id(product_ids[page])
            if product:
                await send_product_page(
                    callback, product, page, len(product_ids), category_code, state, bot
                )
                return

    elif last_loc == "women":
        await send_menu_page(
            callback,
            state,
            bot,
            "<b>👠 Женская обувь</b>\nВыберите категорию:",
            kb.women_kb(has_cart),
        )
        return
    elif last_loc == "men":
        await send_menu_page(
            callback,
            state,
            bot,
            "<b>👞 Мужская обувь</b>\nВыберите категорию:",
            kb.men_kb(has_cart),
        )
        return
    elif last_loc == "accessories":
        await send_menu_page(
            callback,
            state,
            bot,
            "<b>👜 Аксессуары</b>\nВыберите категорию:",
            kb.accessories_kb(has_cart),
        )
        return
    elif last_loc == "novinki":
        await send_menu_page(
            callback,
            state,
            bot,
            "Раздел 'Новинки' в разработке...",
            kb.back_to_menu_kb(has_cart),
        )
        return
    elif last_loc in ["sale_women", "sale_men"]:
        await send_menu_page(
            callback,
            state,
            bot,
            "Раздел '🤩 Распродажа' в разработке...",
            kb.back_to_menu_kb(has_cart),
        )
        return
    elif last_loc.startswith("sub_"):
        if last_loc == "sub_women_heels":
            text, markup = (
                "<b>👠 Женская обувь на каблуке</b>\nВыберите категорию:",
                kb.women_heels_kb(has_cart),
            )
        elif last_loc == "sub_women_boots":
            text, markup = (
                "<b>👢 Женские Ботинки и Сапоги</b>\nВыберите категорию:",
                kb.women_boots_kb(has_cart),
            )
        elif last_loc == "sub_men_boots":
            text, markup = (
                "<b>👞 Мужские Ботинки</b>\nВыберите категорию:",
                kb.men_boots_kb(has_cart),
            )
        else:
            text, markup = "Раздел в разработке...", kb.back_to_menu_kb(has_cart)
        await send_menu_page(callback, state, bot, text, markup)
        return
    elif last_loc.startswith("menu_"):
        if last_loc == "menu_women":
            text, markup = "<b>👠 Женская обувь</b>\nВыберите категорию:", kb.women_kb(
                has_cart
            )
        elif last_loc == "menu_men":
            text, markup = "<b>👞 Мужская обувь</b>\nВыберите категорию:", kb.men_kb(
                has_cart
            )
        elif last_loc == "menu_accessories":
            text, markup = (
                "<b>👜 Аксессуары</b>\nВыберите категорию:",
                kb.accessories_kb(has_cart),
            )
        else:
            text, markup = "Раздел в разработке...", kb.back_to_menu_kb(has_cart)
        await send_menu_page(callback, state, bot, text, markup)
        return

    text = start_text + "👇 <b>С чего начнем? Выберите раздел в меню:</b>"
    await send_menu_page(callback, state, bot, text, kb.main_menu_kb(has_cart))


@user_router.callback_query(kb.CartOption.filter(F.action == "increase"))
async def increase_item_qty(
    callback: CallbackQuery, callback_data: kb.CartOption, state: FSMContext, bot: Bot
):
    cart_items = await rq.get_cart(callback.from_user.id)
    target = next(
        (item for item in cart_items if item[0] == int(callback_data.item_id)), None
    )

    if not target:
        return await callback.answer("Товар не найден в корзине", show_alert=True)

    cart_id, product, size, current_qty = target

    stock_info = await check_stock_in_1c(product.id, size)
    has_stock = False
    actual_stock = 0

    if stock_info.get("success"):
        sizes_list = stock_info.get("sizes", [])
        for sz_info in sizes_list:
            sz_name = str(sz_info.get("size"))
            if sz_name == size or size == "Без размера":
                actual_stock = int(sz_info.get("stock", 0))
                if actual_stock > current_qty:
                    has_stock = True
                break

        if not has_stock:
            return await callback.answer(
                f"❌ Больше добавить нельзя!\n\nНа складе осталось только {actual_stock} шт. (Размер: {size}).",
                show_alert=True,
            )
    else:
        if product.sizes:
            for part in product.sizes.split(","):
                sz = part.split(" (")[0].strip()
                if sz == size or size == "Без размера":
                    try:
                        qty_str = part.split("(")[1].replace("шт)", "").strip()
                        actual_stock = int(qty_str)
                        if actual_stock > current_qty:
                            has_stock = True
                    except Exception:
                        has_stock = True
                    break
            if not has_stock:
                return await callback.answer(
                    f"❌ Больше добавить нельзя!\n\nНа складе осталось только {actual_stock} шт.",
                    show_alert=True,
                )

    await rq.change_cart_item_qty(cart_id, 1)
    await callback.answer("✅ Добавлено!")

    # Если мы просто увеличиваем, картинки не меняются, поэтому быстро обновляем текст
    await edit_cart_callback(callback, state, bot)


@user_router.callback_query(kb.CartOption.filter(F.action == "decrease"))
async def decrease_item_qty(
    callback: CallbackQuery, callback_data: kb.CartOption, state: FSMContext, bot: Bot
):
    cart_items = await rq.get_cart(callback.from_user.id)
    target = next(
        (item for item in cart_items if item[0] == int(callback_data.item_id)), None
    )

    if not target:
        return await callback.answer("Товар не найден в корзине", show_alert=True)

    cart_id, product, size, current_qty = target

    if current_qty > 1:
        await rq.change_cart_item_qty(cart_id, -1)
        await callback.answer("➖ Убавлено")
        # Если количество больше 1, картинка не пропадает, просто обновляем текст
        await edit_cart_callback(callback, state, bot)
    else:
        await rq.remove_from_cart(cart_id)
        await callback.answer("❌ Удалено из корзины")
        # 🔥 Товар удаляется полностью -> нужна полная перерисовка корзины (чтобы удалить картинку)
        await view_cart(callback, state, bot)


@user_router.callback_query(kb.CartOption.filter(F.action == "remove"))
async def remove_item_from_cart(
    callback: CallbackQuery, callback_data: kb.CartOption, state: FSMContext, bot: Bot
):
    await rq.remove_from_cart(int(callback_data.item_id))
    await callback.answer("❌ Удалено из корзины")
    # 🔥 Товар удаляется полностью -> нужна полная перерисовка корзины (чтобы удалить картинку)
    await view_cart(callback, state, bot)


async def generate_and_send_receipt(
    user_id: int, city: str, state: FSMContext, bot: Bot, chat_id: int, message_id: int
):
    cart_items = await rq.get_cart(user_id)
    if not cart_items:
        return

    user_obj = await rq.get_user(user_id)
    total_price = sum(store_item.price * qty for _, store_item, _, qty in cart_items)
    bonuses = user_obj.bonuses if user_obj and user_obj.bonuses else 0

    discount = min(total_price, bonuses)
    products_final_price = total_price - discount

    can_get_bonus = user_obj.number_of_referrals < 3

    delivery_cost = await get_delivery_cost_from_1c(city)
    if delivery_cost is None:
        await asyncio.sleep(1.5)
        delivery_cost = await get_delivery_cost_from_1c(city)

    data = await state.get_data()
    base_text = data.get("checkout_base_text", "")

    if delivery_cost is None:
        error_text = base_text + (
            "\n\n⚠️ <b>Ошибка расчета доставки</b>\n"
            "Не удалось рассчитать стоимость доставки для вашего города.\n"
            "Проверьте правильность написания или попробуйте немного позже."
        )
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 Повторить попытку",
                        callback_data=kb.CartOption(
                            action="checkout", item_id="0"
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="✏️ Изменить город доставки", callback_data="change_city"
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="◀️ Назад в корзину",
                        style="primary",
                        callback_data="view_cart",
                    )
                ],
            ]
        )
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=error_text,
                reply_markup=markup,
            )
        except TelegramBadRequest:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=error_text,
                    reply_markup=markup,
                )
            except Exception:
                pass
        return

    await state.update_data(delivery_cost=delivery_cost, delivery_city=city)

    final_price = products_final_price + int(delivery_cost)

    text = (
        f"🧾 <b>Ваш заказ (Предварительный чек):</b>\n\n"
        f"🏙 <b>Город доставки:</b> <code>{city}</code>\n"
        f"📦 <b>Сумма товаров:</b> {total_price} руб.\n"
    )
    if discount > 0:
        text += f"🎁 <b>Скидка бонусами:</b> -{discount} руб.\n"

    text += (
        f"🚚 <b>Стоимость доставки:</b> {int(delivery_cost)} руб.\n"
        f"──────────────\n"
        f"💰 <b>Итого к оплате: {final_price} руб.</b>\n\n"
    )

    if can_get_bonus:
        text += f"<blockquote>💡 <i>У вас есть возможность получить дополнительную скидку 500 рублей!</i></blockquote>\n"
    else:
        text += f"👇 <i>Проверьте данные и подтвердите заказ.</i>"

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"✅ Подтвердить заказ",
                    callback_data=kb.CartOption(
                        action="confirm_order", item_id="0"
                    ).pack(),
                )
            ]
        ]
    )
    if can_get_bonus:
        markup.inline_keyboard.append(
            [
                InlineKeyboardButton(
                    text="🎁 Получить 500 бонусов",
                    callback_data=kb.CartOption(
                        action="bonus_info", item_id="0"
                    ).pack(),
                )
            ]
        )

    markup.inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="✏️ Изменить город доставки", callback_data="change_city"
            )
        ]
    )
    markup.inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="◀️ Вернуться в корзину", style="primary", callback_data="view_cart"
            )
        ]
    )

    try:
        await bot.edit_message_caption(
            chat_id=chat_id, message_id=message_id, caption=text, reply_markup=markup
        )
    except TelegramBadRequest:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=markup,
                disable_web_page_preview=True,
            )
        except Exception:
            pass


@user_router.callback_query(kb.CartOption.filter(F.action == "checkout"))
async def process_checkout(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = callback.from_user

    cart_items = await rq.get_cart(user.id)
    if not cart_items:
        return await callback.answer("Ваша корзина пуста!", show_alert=True)

    requested_qtys = {}
    product_ids = []
    total_price = 0
    base_text = "🛒 <b>Оформление заказа:</b>\n\n"

    for idx, (cart_id, store_item, size, qty) in enumerate(cart_items, start=1):
        key = (store_item.id, size)
        if key not in requested_qtys:
            requested_qtys[key] = {"name": store_item.name, "qty": 0}
        requested_qtys[key]["qty"] += qty
        product_ids.append(store_item.id)

        total_price += store_item.price * qty
        base_text += f"<b>{idx}. {store_item.name}</b>\n"
        if size and size != "Без размера":
            base_text += f"└ Размер: {size}\n"
        base_text += (
            f"└ {qty} шт. x {store_item.price} руб. = {store_item.price * qty} руб.\n\n"
        )

    base_text += f"💰 <b>Сумма товаров: {total_price} руб.</b>"

    await state.update_data(
        checkout_base_text=base_text, checkout_msg_id=callback.message.message_id
    )

    stock_dict = await check_multiple_stocks_in_1c(product_ids)

    if stock_dict:
        out_of_stock_msgs = []

        for p_id, sizes_list in stock_dict.items():
            available_sizes = []
            for sz_info in sizes_list:
                qty = int(sz_info.get("qty", sz_info.get("stock", 0)))
                if qty > 0:
                    available_sizes.append(f"{sz_info.get('size')} ({qty}шт)")
            new_sizes_str = ", ".join(available_sizes)
            await rq.update_product_sizes(p_id, new_sizes_str)

        for (req_p_id, req_size), req_data in requested_qtys.items():
            sizes_list = stock_dict.get(req_p_id)
            if sizes_list is None:
                out_of_stock_msgs.append(
                    f"🔸 <b>{req_data['name']}</b> (Размер: {req_size})\n"
                    f"Запрошено: {req_data['qty']} шт. | В наличии: 0 шт. (Снят с продажи)"
                )
                await rq.update_product_sizes(req_p_id, "")
                continue

            stock_by_size = {}
            for sz_info in sizes_list:
                qty = int(sz_info.get("qty", sz_info.get("stock", 0)))
                sz_name = str(sz_info.get("size"))
                stock_by_size[sz_name] = qty

            actual_qty = stock_by_size.get(req_size, 0)
            if req_size == "Без размера":
                actual_qty = sum(stock_by_size.values()) if stock_by_size else 0

            if req_data["qty"] > actual_qty:
                out_of_stock_msgs.append(
                    f"🔸 <b>{req_data['name']}</b> (Размер: {req_size})\n"
                    f"Запрошено: {req_data['qty']} шт. | В наличии: {actual_qty} шт."
                )

        if out_of_stock_msgs:
            error_text = (
                "⚠️ <b>ОШИБКА: Товаров не хватает на складе</b>\n\n"
                + "\n\n".join(out_of_stock_msgs)
                + "\n\nПожалуйста, удалите лишние позиции из корзины 🛒"
            )

            await callback.answer("Не хватает товаров на складе!", show_alert=True)
            # Возвращаем корзину с ошибкой
            await view_cart(callback, state, bot)
            try:
                await callback.message.answer(error_text)
            except Exception:
                pass
            return

    user_obj = await rq.get_user(user.id)
    city = getattr(user_obj, "city", None)

    if not city:
        await callback.answer()
        text = (
            base_text
            + "\n\n<blockquote>👇 Для расчета доставки напишите ваш город в чат:</blockquote>"
        )
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="◀️ Назад в корзину",
                        style="primary",
                        callback_data="view_cart",
                    )
                ]
            ]
        )
        try:
            if callback.message.text:
                await callback.message.edit_text(text=text, reply_markup=markup)
            else:
                await callback.message.edit_caption(caption=text, reply_markup=markup)
        except TelegramBadRequest:
            pass
        await state.set_state(CheckoutState.waiting_for_city)
    else:
        await callback.answer("Считаем стоимость доставки... ⏳")
        await generate_and_send_receipt(
            user.id,
            city,
            state,
            bot,
            callback.message.chat.id,
            callback.message.message_id,
        )


@user_router.callback_query(F.data == "change_city")
async def change_city_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    data = await state.get_data()
    base_text = data.get("checkout_base_text", "🛒 Оформление заказа\n\n")
    text = (
        base_text
        + "\n\n<blockquote>👇 Для расчета доставки напишите ваш город в чат:</blockquote>"
    )

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="◀️ Назад в корзину", style="primary", callback_data="view_cart"
                )
            ]
        ]
    )

    try:
        if callback.message.text:
            await callback.message.edit_text(text=text, reply_markup=markup)
        else:
            await callback.message.edit_caption(caption=text, reply_markup=markup)
    except TelegramBadRequest:
        pass

    await state.update_data(checkout_msg_id=callback.message.message_id)
    await state.set_state(CheckoutState.waiting_for_city)


@user_router.message(CheckoutState.waiting_for_city)
async def process_city_input(message: Message, state: FSMContext, bot: Bot):
    city = message.text.strip()
    user_id = message.from_user.id
    chat_id = message.chat.id

    try:
        await message.delete()
    except Exception:
        pass

    async with rq.async_session() as session:
        await session.execute(
            update(User).where(User.telegram_id == user_id).values(city=city)
        )
        await session.commit()

    data = await state.get_data()
    checkout_msg_id = data.get("checkout_msg_id")
    base_text = data.get("checkout_base_text", "🛒 Оформление заказа\n\n")

    if checkout_msg_id:
        loading_text = base_text + "\n\n⏳ <i>Считаем стоимость доставки...</i>"
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=checkout_msg_id,
                caption=loading_text,
                reply_markup=None,
            )
        except TelegramBadRequest:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=checkout_msg_id,
                    text=loading_text,
                    reply_markup=None,
                )
            except Exception:
                pass

        await generate_and_send_receipt(
            user_id, city, state, bot, chat_id, checkout_msg_id
        )
    else:
        processing_msg = await message.answer_photo(
            photo=MAIN_PHOTO, caption="Считаем стоимость доставки... ⏳"
        )
        await generate_and_send_receipt(
            user_id, city, state, bot, chat_id, processing_msg.message_id
        )


@user_router.callback_query(kb.CartOption.filter(F.action == "bonus_info"))
async def process_bonus_info(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user = callback.from_user
    user_obj = await rq.get_user(user.id)

    await callback.answer()

    friends_left = 3 - (user_obj.number_of_referrals if user_obj else 0)
    bot_info = await bot.get_me()
    invite_link = f"https://t.me/{bot_info.username}?start={user.id}"

    text = (
        f"🎁 <b>Как получить 500 бонусов?</b>\n\n"
        f"1️⃣ Отправьте вашу персональную ссылку 3 друзьям.\n"
        f"2️⃣ Как только они зайдут в бота и оставят свой номер телефона, вам автоматически начислится 500 бонусов!\n"
        f"3️⃣ Вернитесь к оформлению заказа, и сумма станет на 500 руб. меньше.\n\n"
        f"Осталось пригласить: <b>{friends_left} чел.</b>\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n<code>{invite_link}</code>\n\n"
        f"<i>(Акция доступна только 1 раз)</i>"
    )

    markup = kb.bonus_info_kb(invite_link)

    try:
        if callback.message.text:
            await callback.message.edit_text(
                text=text, reply_markup=markup, disable_web_page_preview=True
            )
        else:
            await callback.message.edit_caption(caption=text, reply_markup=markup)
    except TelegramBadRequest:
        pass


@user_router.callback_query(kb.CartOption.filter(F.action == "confirm_order"))
async def process_checkout_confirm(
    callback: CallbackQuery, state: FSMContext, bot: Bot
):
    user = callback.from_user

    data = await state.get_data()
    delivery_cost = data.get("delivery_cost", 0.0)
    city = data.get("delivery_city", "Не указан")

    cart_items = await rq.get_cart(user.id)
    if not cart_items:
        return await callback.answer("Ваша корзина пуста!", show_alert=True)

    user_obj = await rq.get_user(user.id)
    total_price = sum(store_item.price * qty for _, store_item, _, qty in cart_items)
    bonuses = user_obj.bonuses if user_obj and user_obj.bonuses else 0

    discount = min(total_price, bonuses)
    products_final_price = total_price - discount
    final_price = products_final_price + int(delivery_cost)

    text = (
        f"🧾 <b>Ваш заказ (Предварительный чек):</b>\n\n"
        f"🏙 <b>Город доставки:</b> <code>{city}</code>\n"
        f"📦 <b>Сумма товаров:</b> {total_price} руб.\n"
    )
    if discount > 0:
        text += f"🎁 <b>Скидка бонусами:</b> -{discount} руб.\n"

    text += (
        f"🚚 <b>Стоимость доставки:</b> {int(delivery_cost)} руб.\n"
        f"──────────────\n"
        f"💰 <b>Итого к оплате: {final_price} руб.</b>\n\n"
        f"<blockquote>⏳ <b>Формируется ссылка на оплату, пожалуйста, подождите...</b></blockquote>"
    )

    try:
        if callback.message.text:
            await callback.message.edit_text(text=text, reply_markup=None)
        else:
            await callback.message.edit_caption(caption=text, reply_markup=None)
    except TelegramBadRequest:
        pass

    asyncio.create_task(
        _background_checkout(
            user.id,
            delivery_cost,
            callback.message.chat.id,
            callback.message.message_id,
            state,
            bot,
        )
    )


async def _background_checkout(
    user_id: int,
    delivery_cost: float,
    chat_id: int,
    message_id: int,
    state: FSMContext,
    bot: Bot,
):
    try:
        order = await rq.create_order_from_cart(user_id)
        if not order:
            return

        if delivery_cost > 0:
            async with rq.async_session() as session:
                await session.execute(
                    update(Order)
                    .where(Order.id == order.id)
                    .values(total_price=order.total_price + int(delivery_cost))
                )
                await session.commit()
            order.total_price += int(delivery_cost)

        user_obj = await rq.get_user(user_id)
        phone = user_obj.phone if user_obj.phone else "+70000000000"

        order_data, items = await rq.get_order_with_items(order.id)

        await rq.update_order_status(order.id, "payment_sent")

        response_data = await send_order_to_1c(
            user_obj.telegram_id, user_obj.user_name, phone, items
        )

        paylink = "https://basarab.ru/"
        if isinstance(response_data, dict) and response_data.get("paylink"):
            paylink = response_data.get("paylink")

        total_items_price = sum(
            ord_item.price * ord_item.quantity for ord_item, prod in items
        )
        discount = total_items_price - (order.total_price - int(delivery_cost))

        success_text = (
            f"✅ <b>Заявка успешно оформлена!</b>\n\n🛒 <b>Ваш заказ:</b>\n\n"
        )

        for idx, (ord_item, prod) in enumerate(items, start=1):
            size_str = (
                f" (Размер: {ord_item.selected_size})"
                if ord_item.selected_size and ord_item.selected_size != "Без размера"
                else ""
            )
            item_total = ord_item.price * ord_item.quantity
            success_text += f"<b>{idx}. {prod.name}</b>{size_str}\n└ {ord_item.quantity} шт. x {ord_item.price} руб. = {item_total} руб.\n\n"

        success_text += f"📦 <b>Сумма товаров:</b> {total_items_price} руб.\n"
        if discount > 0:
            success_text += f"🎁 <b>Скидка бонусами:</b> -{discount} руб.\n"

        success_text += (
            f"🚚 <b>Доставка:</b> {int(delivery_cost)} руб.\n──────────────\n"
        )
        success_text += f"💰 <b>Итого к оплате: {order.total_price} руб.</b>\n\n"
        success_text += (
            f"👇 Нажмите кнопку ниже, чтобы перейти к защищенной странице оплаты:"
        )

        markup = kb.user_payment_kb(paylink)

        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=success_text,
                reply_markup=markup,
            )
        except TelegramBadRequest:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=success_text,
                    reply_markup=markup,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.error(f"❌ Не удалось отредактировать сообщение с чеком: {e}")

    except Exception as e:
        logger.error(f"❌ Ошибка в фоновом оформлении заказа: {e}")


@user_router.callback_query(F.data == "noop")
async def noop_callback(callback: CallbackQuery):
    await callback.answer()
