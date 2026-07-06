import aiosqlite
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timedelta

from database import DB, get_user, extend_user_days, _generate_sub_file
from xray import add_client_multi_async, add_proxy_client_async

router = Router()

# ─── DB ───────────────────────────────────────────────────────────────────────

async def init_balance_db():
    """Добавляет колонку balance если её нет."""
    async with aiosqlite.connect(DB) as db:
        try:
            await db.execute("ALTER TABLE users ADD COLUMN balance INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass

async def get_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row and row[0] else 0

async def add_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET balance = COALESCE(balance, 0) + ? WHERE user_id=?",
            (amount, user_id)
        )
        await db.commit()

async def deduct_balance(user_id: int, amount: int) -> bool:
    """Списывает amount с баланса. Возвращает False если недостаточно средств."""
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        bal = row[0] if row and row[0] else 0
        if bal < amount:
            return False
        await db.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id=?",
            (amount, user_id)
        )
        await db.commit()
        return True

# ─── Хендлеры ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "balance")
async def balance_menu(cb: CallbackQuery):
    bal = await get_balance(cb.from_user.id)
    await cb.message.edit_text(
        f"💰 *Ваш баланс: {bal}₽*\n\n"
        "Используйте баланс для оплаты подписки.\n"
        "Выполняйте задания, чтобы пополнить баланс.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить подписку с баланса", callback_data="balance_pay_plans")],
            [InlineKeyboardButton(text="📋 Задания", callback_data="tasks_menu")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
        ])
    )
    await cb.answer()

@router.callback_query(F.data == "balance_pay_plans")
async def balance_pay_plans(cb: CallbackQuery):
    from handlers.user import PLANS, plan_price
    from config import TRAFFIC_LIMITS
    bal = await get_balance(cb.from_user.id)
    rows = []
    for months, p in PLANS.items():
        price = plan_price(months)
        gb = TRAFFIC_LIMITS.get(months, 50) * months
        enough = "✅" if bal >= price else "❌"
        rows.append([InlineKeyboardButton(
            text=f"{enough} {p['label']} — {price}₽ · {gb} ГБ",
            callback_data=f"balance_buy_{months}"
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="balance")])
    await cb.message.edit_text(
        f"💰 *Баланс: {bal}₽*\n\n"
        "Выберите тариф для оплаты с баланса:\n"
        "✅ — хватает средств  ❌ — недостаточно",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await cb.answer()

@router.callback_query(F.data.regexp(r"^balance_buy_\d+$"))
async def balance_buy(cb: CallbackQuery):
    from handlers.user import PLANS, plan_price, main_menu
    months = int(cb.data.split("_")[2])
    if months not in PLANS:
        return await cb.answer("Неверный тариф.", show_alert=True)

    price = plan_price(months)
    bal = await get_balance(cb.from_user.id)
    if bal < price:
        return await cb.answer(
            f"❌ Недостаточно средств.\nНужно: {price}₽, у вас: {bal}₽",
            show_alert=True
        )

    ok = await deduct_balance(cb.from_user.id, price)
    if not ok:
        return await cb.answer("❌ Ошибка списания. Попробуйте снова.", show_alert=True)

    days = PLANS[months]["days"]
    was_active = (await get_user(cb.from_user.id))["active"]
    await extend_user_days(cb.from_user.id, days)

    if not was_active:
        user = await get_user(cb.from_user.id)
        uuids = [u for u in [user["uuid"], user["uuid2"], user["uuid3"]] if u]
        await add_client_multi_async(uuids, str(cb.from_user.id))
        await add_proxy_client_async(cb.from_user.id)

    new_bal = await get_balance(cb.from_user.id)
    user = await get_user(cb.from_user.id)
    await cb.message.edit_text(
        f"✅ *Подписка оплачена с баланса!*\n\n"
        f"Тариф: *{PLANS[months]['label']}*\n"
        f"Списано: *{price}₽*\n"
        f"Остаток баланса: *{new_bal}₽*\n"
        f"Оплачено до: *{user['paid_until']}*",
        parse_mode="Markdown",
        reply_markup=main_menu(True)
    )
    await cb.answer()
