import random
from sqlalchemy import select, update, delete, or_

from app.database.models import User, Store, Cart, Order, OrderItem, async_session


async def register_user(telegram_id: int, user_name: str, referrer_id: str | None):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            ref_id = None
            if (
                referrer_id
                and referrer_id.isdigit()
                and int(referrer_id) != telegram_id
            ):
                ref_id = int(referrer_id)

            new_user = User(
                telegram_id=telegram_id,
                user_name=user_name,
                referrar_by=ref_id,
                bonuses=500,  # 🎁 500 приветственных бонусов новичку
            )
            session.add(new_user)
            await session.commit()
            return True
        return False


async def get_user(telegram_id: int) -> User | None:
    async with async_session() as session:
        return await session.get(User, telegram_id)


async def increment_orders_count(telegram_id: int):
    async with async_session() as session:
        user = await session.get(User, telegram_id)
        if user:
            await session.execute(
                update(User)
                .where(User.telegram_id == telegram_id)
                .values(total_sale_orders=user.total_sale_orders + 1)
            )
            await session.commit()


async def update_user_1c_data(telegram_id: int, phone: str):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user:
            is_first_phone = not bool(user.phone)
            user.phone = phone

            if is_first_phone and user.referrar_by:
                user_ref = await session.scalar(
                    select(User).where(User.telegram_id == user.referrar_by)
                )
                if user_ref:
                    user_ref.number_of_referrals += 1
                    if user_ref.number_of_referrals == 3:
                        user_ref.bonuses += 500

            await session.commit()


async def get_user_city(telegram_id: int) -> str | None:
    """Получает город пользователя из БД"""
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        return user.city if user and hasattr(user, "city") else None


async def save_user_city(telegram_id: int, city: str):
    """Сохраняет город пользователя в БД"""
    async with async_session() as session:
        await session.execute(
            update(User).where(User.telegram_id == telegram_id).values(city=city)
        )
        await session.commit()


# 🔥 ИСПРАВЛЕННЫЙ ПОИСК с поддержкой Мульти-фильтра по размеру
async def get_category_ids(category_code: str, size_filters: list = None):
    async with async_session() as session:
        clean_code = category_code.replace("cat_", "")

        stmt = select(Store.id)

        if clean_code in ["all_women", "all_female"]:
            stmt = stmt.where(Store.category_code.like(r"%\_female", escape="\\"))
        elif clean_code in ["all_men", "all_male"]:
            stmt = stmt.where(Store.category_code.like(r"%\_male", escape="\\"))
        elif clean_code.startswith("all_"):
            cat = clean_code.replace("all_", "")
            stmt = stmt.where(Store.category_code.icontains(cat))
        elif clean_code.endswith("_female"):
            base_cat = clean_code.replace("_female", "")
            stmt = stmt.where(
                Store.category_code.startswith(base_cat)
                & Store.category_code.like(r"%\_female", escape="\\")
            )
        elif clean_code.endswith("_male"):
            base_cat = clean_code.replace("_male", "")
            stmt = stmt.where(
                Store.category_code.startswith(base_cat)
                & Store.category_code.like(r"%\_male", escape="\\")
            )
        else:
            stmt = stmt.where(Store.category_code == clean_code)

        # 🔥 ФИЛЬТР ПО РАЗМЕРУ (обрабатываем как 1 размер, так и список размеров)
        if size_filters:
            conditions = [Store.sizes.like(f"%{sz} (%") for sz in size_filters]
            stmt = stmt.where(or_(*conditions))

        result = await session.execute(stmt)
        return result.scalars().all()


async def get_product_by_id(product_id: str) -> Store:
    async with async_session() as session:
        return await session.get(Store, product_id)


async def get_all_users():
    async with async_session() as session:
        result = await session.execute(select(User))
        return result.scalars().all()


async def update_product_sizes(product_id: str, new_sizes_str: str):
    async with async_session() as session:
        await session.execute(
            update(Store).where(Store.id == product_id).values(sizes=new_sizes_str)
        )
        await session.commit()


async def update_product_photos(product_id: str, new_photos_str: str):
    async with async_session() as session:
        await session.execute(
            update(Store).where(Store.id == product_id).values(photo=new_photos_str)
        )
        await session.commit()


# --- КОРЗИНА ---


async def add_to_cart(telegram_id: int, product_id: str, size: str):
    async with async_session() as session:
        existing_item = await session.scalar(
            select(Cart).where(
                Cart.user_id == telegram_id,
                Cart.product_id == product_id,
                Cart.size == size,
            )
        )
        if existing_item:
            existing_item.quantity += 1
        else:
            session.add(
                Cart(user_id=telegram_id, product_id=product_id, size=size, quantity=1)
            )
        await session.commit()


async def get_cart(telegram_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(Cart.id, Store, Cart.size, Cart.quantity)
            .join(Store, Cart.product_id == Store.id)
            .where(Cart.user_id == telegram_id)
        )
        return result.all()


async def remove_from_cart(cart_id: int):
    async with async_session() as session:
        await session.execute(delete(Cart).where(Cart.id == cart_id))
        await session.commit()


async def change_cart_item_qty(cart_id: int, delta: int):
    async with async_session() as session:
        item = await session.scalar(select(Cart).where(Cart.id == cart_id))
        if item:
            item.quantity += delta
            await session.commit()


async def clear_cart(telegram_id: int):
    async with async_session() as session:
        await session.execute(delete(Cart).where(Cart.user_id == telegram_id))
        await session.commit()


async def get_cart_total(telegram_id: int) -> float:
    """Считает общую сумму товаров в корзине"""
    async with async_session() as session:
        cart_result = await session.execute(
            select(Store.price, Cart.quantity)
            .join(Cart, Cart.product_id == Store.id)
            .where(Cart.user_id == telegram_id)
        )
        products = cart_result.all()
        # Считаем сумму (цена * количество)
        return sum(p[0] * p[1] for p in products)


# --- ЗАКАЗЫ ---


async def create_order_from_cart(telegram_id: int) -> Order:
    async with async_session() as session:
        cart_result = await session.execute(
            select(Store, Cart.size, Cart.quantity)
            .join(Cart, Cart.product_id == Store.id)
            .where(Cart.user_id == telegram_id)
        )
        products = cart_result.all()

        if not products:
            return None

        raw_total_price = sum(p[0].price * p[2] for p in products)

        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        bonuses = user.bonuses if user and user.bonuses else 0

        discount = min(raw_total_price, bonuses)
        final_price = raw_total_price - discount

        if user and discount > 0:
            user.bonuses -= discount

        new_order = Order(user_id=telegram_id, total_price=final_price)
        session.add(new_order)
        await session.flush()

        for store_item, size, qty in products:
            session.add(
                OrderItem(
                    order_id=new_order.id,
                    product_id=store_item.id,
                    price=store_item.price,
                    selected_size=size,
                    quantity=qty,
                )
            )

        await session.execute(delete(Cart).where(Cart.user_id == telegram_id))
        await session.commit()

        return new_order


async def get_order_with_items(order_id: int):
    async with async_session() as session:
        order = await session.get(Order, order_id)
        result = await session.execute(
            select(OrderItem, Store)
            .join(Store, OrderItem.product_id == Store.id)
            .where(OrderItem.order_id == order_id)
        )
        items = result.all()
        return order, items


async def get_order(order_id: int) -> Order | None:
    async with async_session() as session:
        return await session.get(Order, order_id)


async def update_order_status(order_id: int, status: str):
    async with async_session() as session:
        await session.execute(
            update(Order).where(Order.id == order_id).values(status=status)
        )
        await session.commit()


async def clear_order_sizes(order_id: int):
    async with async_session() as session:
        await session.execute(
            update(OrderItem)
            .where(OrderItem.order_id == order_id)
            .values(selected_size=None)
        )
        await session.commit()


async def get_next_unsized_item(order_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(OrderItem, Store)
            .join(Store, OrderItem.product_id == Store.id)
            .where(OrderItem.order_id == order_id, OrderItem.selected_size == None)
        )
        return result.first()


async def set_item_size(item_id: int, size: str):
    async with async_session() as session:
        await session.execute(
            update(OrderItem).where(OrderItem.id == item_id).values(selected_size=size)
        )
        await session.commit()


# 🔥 ДОБАВЛЕНО: Новые функции для управления корзиной менеджером
async def update_order_item_qty(item_id: int, delta: int):
    async with async_session() as session:
        item = await session.get(OrderItem, item_id)
        if item:
            item.quantity += delta
            order = await session.get(Order, item.order_id)
            if item.quantity <= 0:
                order.total_price = max(0, order.total_price - item.price)
                await session.delete(item)
            else:
                order.total_price = max(0, order.total_price + (item.price * delta))
            await session.commit()


async def remove_order_item(item_id: int):
    async with async_session() as session:
        item = await session.get(OrderItem, item_id)
        if item:
            order = await session.get(Order, item.order_id)
            order.total_price = max(0, order.total_price - (item.price * item.quantity))
            await session.delete(item)
            await session.commit()


async def add_item_to_order(order_id: int, product_id: str) -> bool:
    async with async_session() as session:
        product = await session.get(Store, product_id)
        if not product:
            return False

        order = await session.get(Order, order_id)

        existing_item = await session.scalar(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.product_id == product_id,
                OrderItem.selected_size == "Без размера",
            )
        )

        if existing_item:
            existing_item.quantity += 1
        else:
            new_item = OrderItem(
                order_id=order_id,
                product_id=product_id,
                price=product.price,
                selected_size="Без размера",
                quantity=1,
            )
            session.add(new_item)

        order.total_price += product.price
        await session.commit()
        return True
