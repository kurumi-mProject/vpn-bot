import asyncio, shutil, os
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, ADMIN_ID
from database import (
    init_db, get_expiring_users, get_expired_users, deactivate_user, get_all_users,
    block_user_traffic, unblock_user_traffic, set_traffic_reset_date, 
    reset_monthly_traffic, get_traffic_blocked_users, get_users_for_traffic_check,
    sync_all_users_traffic, reset_user_month_traffic, calc_traffic_limit
)
from xray import (
    remove_client_multi, remove_proxy_client, get_user_traffic_detail,
    add_client_multi,
    remove_client_multi_async, remove_proxy_client_async, add_client_multi_async
)
from handlers import admin, user
import balance as balance_module
import tasks as tasks_module

# ─── Уведомление об истечении и деактивация ───────────────────────────────────
async def notify_expiring(bot: Bot):
    while True:
        try:
            for u in await get_expiring_users(3):
                try:
                    from database import get_user
                    days = (datetime.strptime(u["paid_until"], "%Y-%m-%d").date() - datetime.now().date()).days
                    await bot.send_message(u["user_id"],
                        f"⚠️ *Подписка истекает через {days} дн.* ({u['paid_until']})\n\n"
                        f"Продлите сейчас чтобы не потерять доступ 👇",
                        parse_mode="Markdown")
                except Exception:
                    pass
            for u in await get_expired_users():
                try:
                    await deactivate_user(u["user_id"])
                    uuids = [uid for uid in [u["uuid"], u["uuid2"], u["uuid3"]] if uid]
                    await remove_client_multi_async(uuids)
                    await remove_proxy_client_async(u["user_id"])
                    await bot.send_message(u["user_id"],
                        "❌ *Подписка истекла.*\n\nДля продления нажмите /start → 💳 Оплатить.",
                        parse_mode="Markdown")
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(86400)

# ─── Уведомление при 80% трафика ─────────────────────────────────────────────
async def notify_traffic(bot: Bot):
    notified = set()
    await asyncio.sleep(300)
    executor = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(3600)
        try:
            users = [u for u in await get_all_users() if u["active"] and u["traffic_limit_gb"]]

            async def check_one(u):
                uid = u["user_id"]
                try:
                    detail = await executor.run_in_executor(None, get_user_traffic_detail, str(uid))
                    pct = detail["total"] / u["traffic_limit_gb"]
                    if pct >= 0.95 and f"{uid}_95" not in notified:
                        notified.add(f"{uid}_95")
                        await bot.send_message(uid,
                            f"🚨 *Трафик почти исчерпан ({int(pct*100)}%)!*\n\n"
                            f"Осталось: *{max(0, u['traffic_limit_gb'] - detail['total']):.2f} ГБ*\n\n"
                            f"Продлите подписку прямо сейчас 👇",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="💳 Продлить", callback_data="pay_plans")
                            ]])
                        )
                    elif pct >= 0.8 and f"{uid}_80" not in notified:
                        notified.add(f"{uid}_80")
                        await bot.send_message(uid,
                            f"⚠️ *Трафик на {int(pct*100)}%*\n\n"
                            f"Использовано: *{detail['total']:.1f} ГБ* из *{u['traffic_limit_gb']} ГБ*\n"
                            f"Осталось: *{max(0, u['traffic_limit_gb'] - detail['total']):.1f} ГБ*",
                            parse_mode="Markdown")
                except Exception:
                    pass

            for i in range(0, len(users), 10):
                await asyncio.gather(*[check_one(u) for u in users[i:i+10]])
                await asyncio.sleep(0.5)
        except Exception:
            pass

# ─── Проверка лимитов трафика и блокировка ────────────────────────────────────
async def check_traffic_limits(bot: Bot):
    """Проверяет трафик каждые 5 минут и блокирует при превышении лимита."""
    await asyncio.sleep(60)
    executor = asyncio.get_event_loop()
    while True:
        await asyncio.sleep(300)
        try:
            users = await get_users_for_traffic_check()
            if not users:
                continue

            # Получаем трафик всех пользователей параллельно
            async def check_one(u):
                if not u["traffic_limit_gb"]:
                    return
                uid = u["user_id"]
                try:
                    month_used = u["traffic_month_used_gb"] or 0.0
                    if month_used >= u["traffic_limit_gb"]:
                        uuids = [x for x in [u["uuid"], u["uuid2"], u["uuid3"]] if x]
                        await remove_client_multi_async(uuids)
                        await remove_proxy_client_async(uid)
                        await block_user_traffic(uid)
                        now = datetime.now()
                        next_reset = (now.replace(day=1) + timedelta(days=32)).replace(day=1).strftime("%Y-%m-%d")
                        await set_traffic_reset_date(uid, next_reset)
                        await bot.send_message(uid,
                            f"🚫 *Лимит трафика исчерпан*\n\n"
                            f"Использовано: *{month_used:.1f} ГБ* из *{u['traffic_limit_gb']} ГБ*\n\n"
                            f"Подписка возобновится *{next_reset}*\n"
                            f"или продлите сейчас для увеличения лимита 👇",
                            parse_mode="Markdown",
                            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                                InlineKeyboardButton(text="💳 Продлить", callback_data="pay_plans")
                            ]])
                        )
                except Exception:
                    pass

            # Батчами по 10 чтобы не перегружать xray API
            for i in range(0, len(users), 10):
                await asyncio.gather(*[check_one(u) for u in users[i:i+10]])
                await asyncio.sleep(0.5)
        except Exception:
            pass

# ─── Ежемесячный сброс трафика ────────────────────────────────────────────────
async def monthly_traffic_reset(bot: Bot):
    """Сбрасывает трафик 1-го числа каждого месяца в 00:05."""
    await asyncio.sleep(60)  # ждём старта
    while True:
        now = datetime.now()
        # Если 1-е число и время между 00:05 и 00:10
        if now.day == 1 and 5 <= now.minute < 10:
            try:
                # Сначала синхронизируем трафик за прошлый месяц
                await sync_all_users_traffic()
                
                users = await get_all_users()
                reset_count = 0
                for u in users:
                    if u["active"]:
                        # Создаём запись нового месяца с нуля
                        await reset_user_month_traffic(u["user_id"])
                        reset_count += 1
                
                await bot.send_message(ADMIN_ID,
                    f"🔄 *Ежемесячный сброс трафика*\n\n"
                    f"Сброшено пользователей: *{reset_count}*",
                    parse_mode="Markdown")
                
                # Спим до следующего дня чтобы не повторять
                await asyncio.sleep(86400)
            except Exception:
                pass
        
        # Проверяем каждую минуту
        await asyncio.sleep(60)

# ─── Разблокировка пользователей в новом месяце ───────────────────────────────
async def unblock_traffic_users(bot: Bot):
    """Разблокирует пользователей, у которых наступила дата сброса."""
    await asyncio.sleep(120)  # ждём старта
    while True:
        await asyncio.sleep(3600)  # каждый час
        try:
            blocked = await get_traffic_blocked_users()
            now = datetime.now()
            
            for u in blocked:
                if not u["traffic_reset_date"]:
                    continue
                reset_date = datetime.strptime(u["traffic_reset_date"], "%Y-%m-%d")
                if now >= reset_date:
                    uuids = [uid for uid in [u["uuid"], u["uuid2"], u["uuid3"]] if uid]
                    await add_client_multi_async(uuids, str(u["user_id"]))
                    await unblock_user_traffic(u["user_id"])
                    await reset_monthly_traffic(u["user_id"])
                    new_limit = calc_traffic_limit(u["paid_until"]) if u["paid_until"] else u["traffic_limit_gb"]
                    try:
                        await bot.send_message(u["user_id"],
                            f"✅ *Подписка восстановлена!*\n\n"
                            f"Трафик сброшен. Лимит: *{new_limit} ГБ*\n\n"
                            f"Приятного использования! 🚀",
                            parse_mode="Markdown")
                    except Exception:
                        pass
                    try:
                        await bot.send_message(ADMIN_ID,
                            f"✅ *Пользователь разблокирован*\n\n"
                            f"ID: `{u['user_id']}`\n"
                            f"Username: @{u['username'] or 'нет'}",
                            parse_mode="Markdown")
                    except Exception:
                        pass
        except Exception:
            pass

# ─── Авто-бэкап БД ────────────────────────────────────────────────────────────
async def auto_backup(bot: Bot):
    backup_dir = "/root/backups"
    os.makedirs(backup_dir, exist_ok=True)
    while True:
        await asyncio.sleep(86400)
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            dst = f"{backup_dir}/vpn_{ts}.db"
            shutil.copy2("/root/vpn_bot/vpn.db", dst)
            # Удаляем бэкапы старше 7 дней
            for f in os.listdir(backup_dir):
                fp = os.path.join(backup_dir, f)
                if os.path.isfile(fp) and (datetime.now().timestamp() - os.path.getmtime(fp)) > 7*86400:
                    os.remove(fp)
            await bot.send_message(ADMIN_ID,
                f"💾 *Бэкап создан:* `{dst}`\n"
                f"Размер: {os.path.getsize(dst)//1024} КБ",
                parse_mode="Markdown")
        except Exception as e:
            await bot.send_message(ADMIN_ID, f"❌ Ошибка бэкапа: {e}")

# ─── Мониторинг сервисов ──────────────────────────────────────────────────────
async def monitor_services(bot: Bot):
    import subprocess
    services = ["vpn-bot", "vpn-api", "xray", "nginx"]
    was_down = set()
    await asyncio.sleep(60)  # ждём старта
    while True:
        await asyncio.sleep(300)  # каждые 5 минут
        try:
            for svc in services:
                r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
                active = r.stdout.strip() == "active"
                if not active and svc not in was_down:
                    was_down.add(svc)
                    await bot.send_message(ADMIN_ID,
                        f"🚨 *Сервис упал:* `{svc}`\n\nПытаюсь перезапустить...",
                        parse_mode="Markdown")
                    subprocess.run(["systemctl", "restart", svc])
                    await asyncio.sleep(5)
                    r2 = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
                    status = "✅ восстановлен" if r2.stdout.strip() == "active" else "❌ не удалось"
                    await bot.send_message(ADMIN_ID, f"`{svc}` — {status}", parse_mode="Markdown")
                elif active and svc in was_down:
                    was_down.discard(svc)
        except Exception:
            pass

async def main():
    await init_db()
    await balance_module.init_balance_db()
    await tasks_module.init_tasks_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))
    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(user.router)
    dp.include_router(balance_module.router)
    dp.include_router(tasks_module.router)
    asyncio.create_task(notify_expiring(bot))
    asyncio.create_task(notify_traffic(bot))
    asyncio.create_task(auto_backup(bot))
    asyncio.create_task(monitor_services(bot))
    asyncio.create_task(check_traffic_limits(bot))
    asyncio.create_task(monthly_traffic_reset(bot))
    asyncio.create_task(unblock_traffic_users(bot))
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
