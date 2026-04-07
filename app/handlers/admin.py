import asyncio
from aiogram import F, Router, Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
)

import app.database.requests as rq
import app.keyboards as kb
from config import MANAGER

admin_router = Router()


class Newsletter(StatesGroup):
    waiting_for_message = State()
    confirmation = State()


@admin_router.message(Command("admin"))
async def admin_comand(message: Message, state: FSMContext):
    if message.from_user.id == MANAGER:
        await state.clear()
        await message.answer(
            "<b>Админ-панель</b>.\n"
            "<i>(База товаров обновляется автоматически со стороны 1С по API)</i>",
            reply_markup=kb.admin_keyboard,
        )


@admin_router.callback_query(F.data.startswith("back_to_admin"))
async def admin_command(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    if callback.from_user.id == MANAGER:
        await state.clear()
        if callback.data == "back_to_admin_new":
            await callback.message.edit_reply_markup(None)
            await callback.message.answer(
                "<b>Админ-панель</b>.",
                reply_markup=kb.admin_keyboard,
            )
            return

        await callback.message.edit_text(
            "<b>Админ-панель</b>.",
            reply_markup=kb.admin_keyboard,
        )


# Теперь кнопка просто информирует, так как 1С сама пушит изменения
@admin_router.callback_query(F.data == "update_table")
async def callback_update_table(callback: CallbackQuery):
    if callback.from_user.id == MANAGER:
        await callback.answer(
            "База данных обновляется автоматически со стороны 1С по API-хукам 🔄",
            show_alert=True,
        )


# ... весь остальной код рассылки оставляем без изменений ...
@admin_router.callback_query(F.data == "message_all_users")
async def start_newsletter(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != MANAGER:
        return

    mes = await callback.message.edit_text(
        "<b>📢 Создание рассылки</b>\n\n"
        "Отправьте сообщение, которое хотите разослать всем пользователям.\n"
        "Это может быть текст, фото, видео, гиф или пост с кнопкой.\n\n"
        "<i>Если вы отправите альбом (несколько фото), они придут пользователям отдельными сообщениями или как копия поста.</i>",
        reply_markup=kb.back_to_admin_kb,
    )
    await state.update_data(admin_mes_id=mes.message_id)
    await state.set_state(Newsletter.waiting_for_message)


@admin_router.message(Newsletter.waiting_for_message)
async def preview_newsletter(message: Message, state: FSMContext):
    data = await state.get_data()
    messages_to_send = data.get("messages_to_send", [])
    messages_to_send.append(message.message_id)
    await state.update_data(messages_to_send=messages_to_send)

    if message.media_group_id:
        await asyncio.sleep(0.5)
        new_data = await state.get_data()
        if new_data.get("last_processed_group") == message.media_group_id:
            return
        await state.update_data(last_processed_group=message.media_group_id)

    admin_mes_id = data.get("admin_mes_id")
    try:
        await message.bot.edit_message_reply_markup(
            chat_id=message.chat.id, message_id=admin_mes_id, reply_markup=None
        )
    except:
        pass

    await message.answer("<b>Вот превью вашего сообщения:</b>", parse_mode="HTML")
    messages_to_send.sort()
    await message.bot.copy_messages(
        chat_id=message.chat.id,
        from_chat_id=message.chat.id,
        message_ids=messages_to_send,
    )

    await message.answer(
        "Начать рассылку для всех пользователей?",
        reply_markup=kb.news_letter_keyboard,
        parse_mode="HTML",
    )
    await state.set_state(Newsletter.confirmation)


@admin_router.callback_query(Newsletter.confirmation, F.data == "confirm_newsletter")
async def run_newsletter(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    messages_to_send = data.get("messages_to_send", [])
    messages_to_send.sort()
    from_chat_id = callback.message.chat.id

    users = await rq.get_all_users()
    count = 0
    blocked = 0

    await callback.message.edit_text(
        f"🚀 Рассылка запущена для {len(users)} пользователей..."
    )

    for user in users:
        try:
            await bot.copy_messages(
                chat_id=user.telegram_id,
                from_chat_id=from_chat_id,
                message_ids=messages_to_send,
            )
            count += 1
            await asyncio.sleep(0.05)
        except TelegramForbiddenError:
            blocked += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            await bot.copy_messages(
                chat_id=user.telegram_id,
                from_chat_id=from_chat_id,
                message_ids=messages_to_send,
            )
            count += 1
        except Exception as e:
            print(f"Ошибка рассылки для {user.telegram_id}: {e}")

    await callback.message.answer(
        f"<b>🏁 Рассылка завершена!</b>\n\n"
        f"✅ Получили: {count}\n"
        f"🚫 Не удалось отправить: {blocked}",
        reply_markup=kb.new_admin_kb,
    )
    await state.clear()


@admin_router.message(F.photo | F.animation)
async def photo_callback(message: Message):
    if message.from_user.id == MANAGER:
        if message.animation:
            await message.answer(
                f"File ID: <code>{message.animation.file_id}</code>", parse_mode="HTML"
            )
            return
        await message.answer(
            f"File ID: <code>{message.photo[-1].file_id}</code>", parse_mode="HTML"
        )
