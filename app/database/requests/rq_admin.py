import asyncio
from sqlalchemy import delete, select
from loguru import logger

from app.database.models import Store, async_session


async def update_catalog_from_1c(products_data: list, clear_old: bool = True) -> str:
    """
    Принимает валидированные Pydantic-модели из api.py и сохраняет их в БД.
    """
    async with async_session() as session:
        # 🔥 ШАГ 1: ЗАПОМИНАЕМ КЭШ ФОТОГРАФИЙ ПЕРЕД УДАЛЕНИЕМ
        existing_products = await session.execute(select(Store.id, Store.photo))

        # Создаем словарь { "id_товара": "AgA...|AgA..." }
        cached_photos = {row[0]: row[1] for row in existing_products}

        if clear_old:
            await session.execute(delete(Store))

        store_objects = []
        for item in products_data:

            # 🔥 ШАГ 2: ПРОВЕРЯЕМ, ЕСТЬ ЛИ УЖЕ ГОТОВЫЙ КЭШ ДЛЯ ЭТОГО ТОВАРА
            old_photo = cached_photos.get(item.id)

            # Если старое фото существует, и это закэшированный file_id (начинается с AgA),
            # и это НЕ стандартная заглушка, то оставляем старый кэш!
            if (
                old_photo
                and "AgA" in old_photo
                and old_photo
                != "AgACAgIAAxkBAANgaV0Eh_seXGonXHfxt4pWcDbppzAAAu0OaxsUqOlK8xNOZ2bmhi8BAAMCAAN5AAM4BA"
            ):
                photo_url = old_photo
            else:
                # Если кэша нет, берем новые ссылки от 1С
                if item.images:
                    valid_images = [img.strip() for img in item.images if img.strip()]
                    photo_url = (
                        "|".join(valid_images)
                        if valid_images
                        else "AgACAgIAAxkBAANgaV0Eh_seXGonXHfxt4pWcDbppzAAAu0OaxsUqOlK8xNOZ2bmhi8BAAMCAAN5AAM4BA"
                    )
                else:
                    photo_url = "AgACAgIAAxkBAANgaV0Eh_seXGonXHfxt4pWcDbppzAAAu0OaxsUqOlK8xNOZ2bmhi8BAAMCAAN5AAM4BA"

            available_sizes = []
            for sz in item.sizes:
                if sz.stock > 0:
                    available_sizes.append(f"{sz.size} ({sz.stock}шт)")

            sizes_str = ", ".join(available_sizes)

            store_objects.append(
                Store(
                    id=item.id,
                    category_code=item.category_code,
                    name=item.name,
                    description=item.description,
                    sizes=sizes_str,
                    price=item.price,
                    photo=photo_url,
                )
            )

        session.add_all(store_objects)
        await session.commit()

        logger.info(
            f"ℹ️  [DB] База обновлена из 1С. Всего товаров: {len(store_objects)}. Кэш перенесен!"
        )

    return f"Загружено товаров: {len(store_objects)}"
