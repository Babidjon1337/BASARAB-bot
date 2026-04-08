import asyncio

from sqlalchemy import BigInteger, String, Integer, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, AsyncAttrs, async_sessionmaker

engine = create_async_engine(url="sqlite+aiosqlite:///app/database/db.sqlite3")

async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_id = mapped_column(BigInteger, primary_key=True)
    user_name = mapped_column(String(255), nullable=True)
    phone = mapped_column(String(20), nullable=True)
    city = mapped_column(String(100), nullable=True)
    # Поля partner_id и contractor_id полностью удалены

    total_sale_orders = mapped_column(Integer, default=0)
    number_of_referrals = mapped_column(Integer, default=0)
    referrar_by = mapped_column(BigInteger, nullable=True)
    bonuses = mapped_column(Integer, default=0)


class Store(Base):
    __tablename__ = "store"

    id = mapped_column(String(100), primary_key=True)
    category_code = mapped_column(String(100), nullable=False)
    name = mapped_column(String)
    description = mapped_column(String)
    sizes = mapped_column(String)
    price = mapped_column(Integer, nullable=False)
    photo = mapped_column(String)
    file_id = mapped_column(String, nullable=True)


class Category(Base):

    __tablename__ = "categories"

    code = mapped_column(String(100), primary_key=True)
    name = mapped_column(String, nullable=False)


class Cart(Base):
    __tablename__ = "cart"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    product_id = mapped_column(String(100), ForeignKey("store.id"))
    size = mapped_column(String(50), nullable=True)
    quantity = mapped_column(Integer, default=1)  # 🔥 ДОБАВЛЕНО


class Order(Base):
    __tablename__ = "orders"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
    total_price = mapped_column(Integer, nullable=False)
    status = mapped_column(String(50), default="pending")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id = mapped_column(Integer, ForeignKey("orders.id"))
    product_id = mapped_column(String(100), ForeignKey("store.id"))
    selected_size = mapped_column(String(50), nullable=True)
    price = mapped_column(Integer, nullable=False)
    quantity = mapped_column(Integer, default=1)  # 🔥 ДОБАВЛЕНО


async def async_main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    asyncio.run(async_main())
