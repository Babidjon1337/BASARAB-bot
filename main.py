import logging
import uvicorn
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.client.bot import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession

from config import (
    BOT_TOKEN,
    WEBHOOK_URL,
    WEBHOOK_SECRET,
    PROXY_URL,
)

# 1. Импортируем роутер aiogram для бота
from app.database.models import async_main
from app.handlers.admin import admin_router
from app.handlers.user import user_router

# 2. ИМПОРТИРУЕМ НОВЫЙ РОУТЕР FASTAPI
from app.api import api_router, fetch_and_sync_catalog


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


bot = Bot(
    token=BOT_TOKEN,
    session=AiohttpSession(proxy=PROXY_URL),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()


# Подключаем роутер aiogram
admin_router._parent_router = None
user_router._parent_router = None

dp.include_routers(admin_router, user_router)


@asynccontextmanager
async def lifespan(app: FastAPI):
    polling_task = None

    logger.info("Bot start... Устанавливаем вебхук.")
    await async_main()  # Инициализация базы данных при запуске бота

    # --- ВАРИАНТ 1: WEBHOOK (Закомментирован) ---
    # Раскомментируйте эти строки, чтобы вернуть вебхуки:
    # await bot.set_webhook(
    #     url=f"{WEBHOOK_URL}/webhook",
    #     secret_token=WEBHOOK_SECRET,
    #     drop_pending_updates=True,
    # )
    # logger.info(f"Вебхук установлен: {webhook_url}")
    # -----------------------------------------------------------------

    # --- ВАРИАНТ 2: LONG POLLING (Активен сейчас) ---
    # Закомментируйте эти строки, если переходите обратно на вебхуки:
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Вебхук Telegram удален. Переходим на Long Polling.")
    polling_task = asyncio.create_task(dp.start_polling(bot))
    # -----------------------------------------------------------------

    # ВОТ ЗДЕСЬ БОТ ЗАПРАШИВАЕТ КАТАЛОГ ИЗ 1С ПРИ ЗАПУСКЕ
    await fetch_and_sync_catalog()

    yield
    # --- ВАРИАНТ 1: WEBHOOK (Закомментирован) ---
    # Раскомментировать, если возвращаетесь на вебхуки:
    # await bot.delete_webhook()
    # -----------------------------------------------------------------

    # --- ВАРИАНТ 2: LONG POLLING (Активен сейчас) ---
    # Закомментировать, если возвращаетесь на вебхуки:
    if polling_task:
        polling_task.cancel()
    # -----------------------------------------------------------------

    await bot.session.close()
    logger.info("Сессия бота закрыта")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ПОДКЛЮЧАЕМ РУЧКИ ИЗ ДРУГОГО ФАЙЛА ---
# prefix="/api" добавит /api ко всем ручкам в этом роутере (будет /api/status)
app.include_router(api_router, prefix="/api", tags=["API"])


# --- ЭНДПОИНТ ДЛЯ TELEGRAM WEBHOOK (Остается в main.py) ---
@app.post("/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=None),
):
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        logger.warning("Попытка несанкционированного доступа к вебхуку!")
        raise HTTPException(status_code=401, detail="Unauthorized")

    update_data = await request.json()
    update = types.Update(**update_data)
    await dp.feed_update(bot=bot, update=update)

    return {"status": "ok"}


if __name__ == "__main__":
    try:
        uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
    except KeyboardInterrupt:
        logger.warning("Бот остановлен вручную")
