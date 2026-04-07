from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

admin_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Обновить таблицу 🔄", callback_data="update_table"
            )
        ],
        [
            InlineKeyboardButton(
                text="Рассылка всем пользователям 📩", callback_data="message_all_users"
            )
        ],
    ]
)


news_letter_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="❌ Отмена", style="danger", callback_data="back_to_admin"
            ),
            InlineKeyboardButton(
                text="✅ Отправить", style="success", callback_data="confirm_newsletter"
            ),
        ],
    ]
)


back_to_admin_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="◀️ Назад", style="primary", callback_data="back_to_admin"
            )
        ],
    ]
)

new_admin_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🖥 Админ панель", callback_data="back_to_admin_new"
            )
        ],
    ]
)
