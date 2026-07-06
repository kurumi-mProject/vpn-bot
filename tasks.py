import aiosqlite
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

from database import DB

router = Router()

CHANNEL = "@maluna_project"
CHANNEL_URL = "https://t.me/maluna_project"
TASK_ID = "sub_maluna"
REWARD = 60

# ─── DB ───────────────────────────────────────────────────────────────────────

async def init_tasks_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS completed_tasks (
                user_id INTEGER,
                task_id TEXT,
                PRIMARY KEY (user_id, task_id)
            )
        """)
        await db.commit()

async def _is_done(user_id: int, task_id: str) -> bool:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT 1 FROM completed_tasks WHERE user_id=? AND task_id=?", (user_id, task_id)
        ) as cur:
            return await cur.fetchone() is not None

async def _mark_done(user_id: int, task_id: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO completed_tasks (user_id, task_id) VALUES (?,?)",
            (user_id, task_id)
        )
        await db.commit()

async def _add_balance(user_id: int, amount: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET balance = COALESCE(balance,0) + ? WHERE user_id=?",
            (amount, user_id)
        )
        await db.commit()

# ─── Хендлеры ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "tasks_menu")
async def tasks_menu(cb: CallbackQuery):
    done = await _is_done(cb.from_user.id, TASK_ID)
    status = "✅ Выполнено" if done else f"+{REWARD}₽"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📢 Подписаться на канал — {status}",
            callback_data="task_already_done" if done else "task_sub_start"
        )],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="balance")],
    ])
    await cb.message.edit_text(
        "📋 *Задания*\n\n"
        "Выполняй задания и получай рубли на баланс.\n"
        "Баланс можно тратить на оплату подписки.",
        parse_mode="Markdown",
        reply_markup=kb
    )
    await cb.answer()

@router.callback_query(F.data == "task_already_done")
async def task_already_done(cb: CallbackQuery):
    await cb.answer("✅ Это задание уже выполнено!", show_alert=True)

@router.callback_query(F.data == "task_sub_start")
async def task_sub_start(cb: CallbackQuery):
    if await _is_done(cb.from_user.id, TASK_ID):
        return await cb.answer("✅ Уже выполнено!", show_alert=True)
    await cb.message.edit_text(
        f"📢 *Задание: подписаться на канал*\n\n"
        f"Подпишитесь на @maluna\\_project и получите *{REWARD}₽* на баланс.\n\n"
        "1️⃣ Нажмите кнопку ниже и подпишитесь\n"
        "2️⃣ Вернитесь и нажмите *Проверить подписку*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="task_sub_check")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="tasks_menu")],
        ])
    )
    await cb.answer()

@router.callback_query(F.data == "task_sub_check")
async def task_sub_check(cb: CallbackQuery):
    if await _is_done(cb.from_user.id, TASK_ID):
        return await cb.answer("✅ Уже выполнено!", show_alert=True)

    try:
        member = await cb.bot.get_chat_member(CHANNEL, cb.from_user.id)
        subscribed = member.status not in ("left", "kicked", "banned")
    except TelegramBadRequest:
        subscribed = False

    if not subscribed:
        return await cb.answer(
            "❌ Вы не подписаны на канал.\nПодпишитесь и попробуйте снова.",
            show_alert=True
        )

    await _mark_done(cb.from_user.id, TASK_ID)
    await _add_balance(cb.from_user.id, REWARD)

    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT balance FROM users WHERE user_id=?", (cb.from_user.id,)) as cur:
            row = await cur.fetchone()
    bal = row[0] if row else REWARD

    await cb.message.edit_text(
        f"✅ *Задание выполнено!*\n\n"
        f"Начислено: *+{REWARD}₽*\n"
        f"Ваш баланс: *{bal}₽*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 К балансу", callback_data="balance")],
        ])
    )
    await cb.answer()
