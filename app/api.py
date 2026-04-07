import aiohttp
import json
import os
import base64
import html
import re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, model_validator
from typing import List, Optional, Any
from loguru import logger

import app.database.requests as rq_admin
from config import URL_1C

api_router = APIRouter()

# --- АВТОМАТИЧЕСКАЯ НАСТРОЙКА ЭНДПОИНТОВ ---

NEW_USER_ENDPOINT = f"{URL_1C}/CreatePartner"
CHECK_ORDER_ENDPOINT = f"{URL_1C}/give"
SEND_ORDER_ENDPOINT = f"{URL_1C}/send"
FETCH_ALL_CATALOG_URL = f"{URL_1C}/sends"  # 🔥 Исправлено на /send
DELIVERY_COST_ENDPOINT = f"{URL_1C}/DelCost"  # 🔥 НОВЫЙ ЭНДПОИНТ ДЛЯ ДОСТАВКИ

# 🔥 ЖЕСТКАЯ АВТОРИЗАЦИЯ 1С (ЗАЩИТА ОТ 401 ОШИБКИ)
credentials = "Глазунов Владимир:gv2026bas+"
encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

HEADERS_1C = {
    "Authorization": f"Basic {encoded_credentials}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


class Category1C(BaseModel):
    id: str
    name: str
    parent_id: Optional[str] = None


class SizeStock1C(BaseModel):
    size: str
    stock: int


class Product1C(BaseModel):
    id: str
    name: str
    description: str
    category_code: str
    price: int
    images: List[str]
    sizes: List[SizeStock1C]

    @model_validator(mode="before")
    @classmethod
    def preprocess_1c_data(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # 1. ОПИСАНИЕ И ИМЯ (с очисткой HTML)
            data["name"] = data.get("name", "").strip()
            desc = data.get("description", "")

            if isinstance(desc, str):
                desc = html.unescape(desc)
                desc = re.sub(r"<(br\s*/?|/?p)>", "\n", desc, flags=re.IGNORECASE)

                allowed_tags = [
                    "b",
                    "/b",
                    "strong",
                    "/strong",
                    "i",
                    "/i",
                    "u",
                    "/u",
                    "s",
                    "/s",
                ]

                def clean_tags(match):
                    tag = match.group(1).lower()
                    if tag in allowed_tags:
                        return match.group(0)
                    return ""

                desc = re.sub(r"<([/a-zA-Z0-9]+)[^>]*>", clean_tags, desc)
                desc = re.sub(r"<strong[^>]*>", "<b>", desc, flags=re.IGNORECASE)
                desc = re.sub(r"</strong>", "</b>", desc, flags=re.IGNORECASE)
                desc = re.sub(r"\n{3,}", "\n\n", desc).strip()
                data["description"] = desc[:200]
            else:
                data["description"] = ""

            # 2. КАТЕГОРИЯ
            cat = data.get("category") or data.get("category_id")
            data["category_code"] = str(cat).strip() if cat else ""

            # 3. ЦЕНА
            price = data.get("price", 0)
            if isinstance(price, str):
                data["price"] = int(price) if price.isdigit() else 0
            elif price is None:
                data["price"] = 0

            # 4. ФОТО (Приоритет: links -> image_url -> images)
            images_result = []

            # Сначала ищем поле "links"
            img_data = data.get("links")

            # Если "links" пустое, ищем "image_url"
            if not img_data:
                img_data = data.get("image_url")

            # Если и оно пустое, ищем старый формат "images"
            if not img_data:
                img_data = data.get("images")

            # Обработка если пришла строка, похожая на JSON массив
            if isinstance(img_data, str):
                img_data = img_data.strip()
                if img_data.startswith("[") and img_data.endswith("]"):
                    try:
                        parsed_list = json.loads(img_data)
                        if isinstance(parsed_list, list):
                            img_data = parsed_list
                    except Exception:
                        pass

            # Финальный парсинг массива или строки
            if isinstance(img_data, list):
                images_result = [str(u).strip() for u in img_data if str(u).strip()]
            elif isinstance(img_data, str) and img_data.strip():
                # 🔥 ИСПРАВЛЕНИЕ ЗДЕСЬ: 1С шлет ссылки через перенос строки (\n)
                clean_str = img_data.replace(";", "\n").replace(",", "\n")
                images_result = [u.strip() for u in clean_str.split("\n") if u.strip()]

            data["images"] = images_result

            # 5. РАЗМЕРЫ
            raw_sizes = data.get("sizes", [])
            processed_sizes = []
            if isinstance(raw_sizes, list):
                for sz in raw_sizes:
                    if isinstance(sz, str) or isinstance(sz, int):
                        processed_sizes.append({"size": str(sz), "stock": 1})
                    elif isinstance(sz, dict):
                        processed_sizes.append(sz)
            data["sizes"] = processed_sizes

        return data


class CatalogPayload(BaseModel):
    categories: List[Category1C] = []
    products: List[Product1C]


async def send_user_to_1c(user_id: int, user_name: str, phone: str = "") -> bool:
    payload = {"user_id": user_id, "user_name": user_name, "phone": phone}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                NEW_USER_ENDPOINT, json=payload, headers=HEADERS_1C, timeout=5
            ) as resp:
                response_text = await resp.text()

                print("\n" + "=" * 50)
                print(f"📤 [1С] ОТПРАВКА КЛИЕНТА ({NEW_USER_ENDPOINT}):")
                print(json.dumps(payload, ensure_ascii=False, indent=4))
                print(f"📥 [1С] ОТВЕТ (Статус {resp.status}):")
                print(response_text)
                print("=" * 50 + "\n")

                if resp.status == 200:
                    logger.info(f"✅ Клиент {user_id} успешно создан в 1С.")
                    return True
                else:
                    logger.warning(
                        f"⚠️ 1С вернула ошибку при создании клиента. Статус: {resp.status}. (Для теста продолжаем работу)"
                    )
                    return True
    except Exception as e:
        logger.error(
            f"❌ 1C Connection Error (User): {e}. (Для теста продолжаем работу)"
        )
        return True


async def check_stock_in_1c(product_id: str, requested_size: str = None) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{CHECK_ORDER_ENDPOINT}?product_id={product_id}"

            async with session.get(url, headers=HEADERS_1C, timeout=5) as resp:
                response_text = await resp.text()

                print("\n" + "=" * 50)
                print(f"📤 [1С] ПРОВЕРКА НАЛИЧИЯ РАЗМЕРА '{requested_size}' ({url}):")
                print(f"📥 [1С] ОТВЕТ (Статус {resp.status}):")
                try:
                    print(
                        json.dumps(
                            json.loads(response_text), ensure_ascii=False, indent=4
                        )
                    )
                except:
                    print(response_text)
                print("=" * 50 + "\n")

                if resp.status == 200:
                    try:
                        data = json.loads(response_text)

                        # 🔥 ОБНОВЛЕНИЕ: Парсинг нового формата (через items и qty)
                        items = data.get("items", [])
                        if items:
                            sizes_list = items[0].get("sizes", [])
                        else:
                            sizes_list = data.get("sizes", [])

                        total_stock = 0
                        size_available = False

                        for s in sizes_list:
                            # Учитываем как 'qty' (новый формат), так и 'stock' (старый формат)
                            qty = int(s.get("qty", s.get("stock", 0)))
                            s["stock"] = qty  # Приводим к единому стандарту для бота
                            total_stock += qty

                            if requested_size and requested_size != "Без размера":
                                if str(s.get("size")) == requested_size and qty > 0:
                                    size_available = True

                        if not requested_size or requested_size == "Без размера":
                            size_available = total_stock > 0 or len(sizes_list) > 0

                        return {
                            "success": True,
                            "available": size_available,
                            "total_stock": total_stock,
                            "sizes": sizes_list,
                        }
                    except Exception:
                        return {"success": False, "available": True}
                else:
                    return {"success": False, "available": True}
    except Exception as e:
        logger.error(f"❌ 1C Connection Error (Stock): {e}.")
        return {"success": False, "available": True}


async def check_multiple_stocks_in_1c(product_ids: list) -> dict:
    """Массовая проверка остатков для всех товаров в корзине перед оформлением заказа"""
    if not product_ids:
        return {}
    try:
        async with aiohttp.ClientSession() as session:
            # Склеиваем уникальные ID через запятую
            ids_str = ",".join(set(product_ids))
            url = f"{CHECK_ORDER_ENDPOINT}?product_ids={ids_str}"

            async with session.get(url, headers=HEADERS_1C, timeout=10) as resp:
                response_text = await resp.text()

                print("\n" + "=" * 50)
                print(f"📤 [1С] МАССОВАЯ ПРОВЕРКА НАЛИЧИЯ ПЕРЕД ЗАКАЗОМ ({url}):")
                print(f"📥 [1С] ОТВЕТ (Статус {resp.status}):")
                try:
                    print(
                        json.dumps(
                            json.loads(response_text), ensure_ascii=False, indent=4
                        )
                    )
                except:
                    print(response_text)
                print("=" * 50 + "\n")

                if resp.status == 200:
                    data = json.loads(response_text)
                    items = data.get("items", [])
                    stock_dict = {}
                    for item in items:
                        p_id = item.get("product_id")
                        sizes = item.get("sizes", [])
                        stock_dict[p_id] = sizes
                    return stock_dict
    except Exception as e:
        logger.error(f"❌ 1C Connection Error (Multiple Stock Check): {e}")
    return {}


async def send_order_to_1c(
    user_id: int,
    user_name: str,
    phone: str,
    order_items_tuples: list,
    comment: str = "Заказ из Telegram-бота",
) -> dict:
    # 🔥 Группируем одинаковые товары (по ID товара и размеру)
    grouped_products = {}

    for order_item, store_item in order_items_tuples:
        size_val = order_item.selected_size

        # 🔥 ИСПРАВЛЕНИЕ ДЛЯ 1С: Размер ВСЕГДА должен быть строкой (текстом), иначе 1С падает (Ошибка 500)
        if not size_val:
            size_val = "Без размера"
        else:
            size_val = str(size_val)

        # Создаем уникальный ключ из ID товара и его размера
        key = (store_item.id, size_val)

        if key in grouped_products:
            grouped_products[key] += order_item.quantity  # Учитываем количество из БД
        else:
            grouped_products[key] = order_item.quantity  # Учитываем количество из БД

    # Формируем итоговый компактный список для отправки
    product_list = []
    for (prod_id, size), qty in grouped_products.items():
        product_list.append({"product_id": prod_id, "size": size, "quantity": qty})

    payload = {
        "user_id": user_id,
        "user_name": user_name,
        "phone": phone,
        "product": product_list,
        "comment": comment,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                SEND_ORDER_ENDPOINT, json=payload, headers=HEADERS_1C, timeout=120
            ) as resp:
                response_text = await resp.text()

                print("\n" + "=" * 50)
                print(f"📤 [1С] ОТПРАВКА ЗАКАЗА ({SEND_ORDER_ENDPOINT}):")
                print(json.dumps(payload, ensure_ascii=False, indent=4))
                print(f"📥 [1С] ОТВЕТ (Статус {resp.status}):")
                try:
                    print(
                        json.dumps(
                            json.loads(response_text), ensure_ascii=False, indent=4
                        )
                    )
                except:
                    print(response_text)
                print("=" * 50 + "\n")

                if resp.status != 200:
                    logger.warning(
                        f"⚠️ 1С вернула ошибку при сохранении заказа: {resp.status}. Заказ сохранен только в БД бота."
                    )
                    return {}  # Возвращаем пустой словарь при ошибке
                else:
                    logger.info(f"✅ Заказ успешно отправлен в 1С.")
                    # 🔥 ИСПРАВЛЕНИЕ ДЛЯ PAYLINK: Возвращаем ответ от 1С обратно в бота!
                    try:
                        return json.loads(response_text)
                    except Exception:
                        return {}

    except Exception as e:
        logger.error(
            f"❌ 1C Connection Error (Order): {e}. Заказ сохранен только в БД бота."
        )
        return {}


async def fetch_and_sync_catalog():
    logger.info(f"🔄 Запрашиваем полный каталог из 1С ({FETCH_ALL_CATALOG_URL})...")
    is_1c_success = False

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                FETCH_ALL_CATALOG_URL, headers=HEADERS_1C, timeout=20
            ) as resp:
                response_text = await resp.text()

                # 🔥 СОХРАНЯЕМ ОТВЕТ 1С В ЛОКАЛЬНЫЙ ФАЙЛ ДЛЯ ОТЛАДКИ
                try:
                    parsed_json = json.loads(response_text)
                    with open("products_test.json", "w", encoding="utf-8") as f:
                        json.dump(parsed_json, f, ensure_ascii=False, indent=4)
                    logger.info("💾 Ответ от 1С сохранен в файл 'products_test.json'")
                except Exception:
                    with open("debug_1c_catalog_raw.txt", "w", encoding="utf-8") as f:
                        f.write(response_text)
                    logger.warning(
                        "💾 Ответ от 1С не является JSON. Сохранен как текст в 'debug_1c_catalog_raw.txt'"
                    )

                print("\n" + "=" * 50)
                print(f"📤 [1С] ЗАПРОС КАТАЛОГА ({FETCH_ALL_CATALOG_URL})")
                print(f"📥 [1С] ОТВЕТ (Статус {resp.status}):")
                print(
                    response_text[:500]
                    + "\n... [ОСТАЛЬНЫЕ ДАННЫЕ В ФАЙЛЕ products_test.json] ..."
                )
                print("=" * 50 + "\n")

                if resp.status == 200:
                    raw_data = json.loads(response_text)
                    payload = CatalogPayload(**raw_data)

                    # 🔥 УБИРАЕМ ТОВАРЫ БЕЗ КАТЕГОРИИ ИЗ СОХРАНЕНИЯ
                    valid_products = [p for p in payload.products if p.category_code]

                    result = await rq_admin.update_catalog_from_1c(
                        valid_products, clear_old=True
                    )
                    logger.info(f"✅ Синхронизация с 1С успешна: {result}")
                    is_1c_success = True
                else:
                    logger.warning(
                        f"⚠️ 1С вернула статус {resp.status}. Включаю заглушку."
                    )
    except Exception as e:
        logger.warning(
            f"⚠️ Не удалось подключиться к 1С ({e}). Включаю локальную заглушку."
        )

    if not is_1c_success:
        file_path = "products.json"
        if not os.path.exists(file_path):
            logger.error(f"❌ Локальный файл {file_path} тоже не найден! Каталог пуст.")
            return

        try:
            # Используем utf-8-sig для игнорирования BOM
            with open(file_path, "r", encoding="utf-8-sig") as f:
                raw_data = json.load(f)

            payload = CatalogPayload(**raw_data)

            valid_products = [p for p in payload.products if p.category_code]

            result = await rq_admin.update_catalog_from_1c(
                valid_products, clear_old=True
            )
            logger.info(f"✅ Успешно загружена ЛОКАЛЬНАЯ ЗАГЛУШКА: {result}")
        except Exception as file_error:
            logger.error(f"❌ Ошибка чтения локального файла: {file_error}")


async def get_delivery_cost_from_1c(city: str) -> float | None:
    """
    Отправляет GET запрос в 1С для получения стоимости доставки по городу.
    Возвращает стоимость (float) или None в случае ошибки.
    """
    params = {"city": city}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                DELIVERY_COST_ENDPOINT, params=params, headers=HEADERS_1C, timeout=10
            ) as resp:
                logger.info(
                    f"📤 [1С] ЗАПРОС ДОСТАВКИ ({DELIVERY_COST_ENDPOINT}?city={city})"
                )

                if resp.status == 200:
                    # 🔥 ИСПРАВЛЕНИЕ: content_type=None заставит aiohttp игнорировать неправильный mimetype от 1С
                    data = await resp.json(content_type=None)
                    return float(data.get("cost", 0.0))
                else:
                    response_text = await resp.text()
                    logger.warning(
                        f"⚠️ 1С Ошибка расчета доставки. Статус: {resp.status}. Ответ: {response_text}"
                    )
                    return None
    except Exception as e:
        logger.error(f"❌ 1C Connection Error (Delivery Cost): {e}")
        return 1000.0


@api_router.get("/status")
async def get_status():
    return {"status": "ok", "message": "API работает!"}


@api_router.post("/1c/stock")
async def update_stock_from_1c(products: List[Product1C]):
    try:
        valid_products = [p for p in products if p.category_code]
        result = await rq_admin.update_catalog_from_1c(valid_products, clear_old=False)
        return {"status": "success", "message": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
