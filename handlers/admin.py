from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
import secrets
import string

from database import (
    activate_user, deactivate_user, get_all_users, get_user,
    confirm_payment, get_payment, set_setting, get_setting,
    get_pending_payments, get_revenue, get_expired_users, get_expiring_users,
    create_promo_code, get_stats, add_server, get_servers, delete_server, get_server,
    set_payment_waiting_msg
)
from xray import add_client, add_client_multi, remove_client, remove_client_multi, add_proxy_client, remove_proxy_client, add_client_multi_async, remove_client_multi_async, add_proxy_client_async, remove_proxy_client_async
from config import ADMIN_ID, PRICE, TRAFFIC_LIMITS

router = Router()

class AdminStates(StatesGroup):
    waiting_requisites = State()
    waiting_broadcast = State()
    waiting_price = State()
    waiting_support = State()
    waiting_promo = State()
    waiting_mass_promo = State()
    waiting_activate_id = State()
    waiting_check_uuid = State()
    # Добавление сервера
    server_ip = State()
    server_ssh_user = State()
    server_ssh_pass = State()
    server_region = State()

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users"),
         InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="⏳ Ожидают оплаты", callback_data="admin_pending"),
         InlineKeyboardButton(text="⚠️ Истекают", callback_data="admin_expiring")],
        [InlineKeyboardButton(text="🔄 Авто-деактивация", callback_data="admin_deactivate"),
         InlineKeyboardButton(text="👤 Активировать", callback_data="admin_activate")],
        [InlineKeyboardButton(text="💳 Реквизиты", callback_data="admin_requisites"),
         InlineKeyboardButton(text="💰 Цена", callback_data="admin_price")],
        [InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin_promo"),
         InlineKeyboardButton(text="📦 Масс промокоды", callback_data="admin_mass_promo")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="admin_support")],
        [InlineKeyboardButton(text="📤 Экспорт", callback_data="admin_export"),
         InlineKeyboardButton(text="🖥 Статус сервера", callback_data="admin_server")],
        [InlineKeyboardButton(text="💾 Бэкап проекта", callback_data="admin_backup")],
        [InlineKeyboardButton(text="🌍 Серверы VPN", callback_data="admin_servers")],
        [InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="admin_check_uuid")],
    ])

def admin_guard(cb: CallbackQuery) -> bool:
    return cb.from_user.id == ADMIN_ID

@router.message(Command("admin"))
async def admin_panel(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer("🔧 *Админ-панель*", parse_mode="Markdown", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_stats")
async def admin_stats(cb: CallbackQuery):
    if not admin_guard(cb): return
    stats = await get_stats()

    # Топ трафик
    traffic_text = ""
    for row in stats["top_traffic"]:
        name = f"@{row[0]}" if row[0] else f"id{row[1]}"
        traffic_text += f"  • {name}: *{round(row[2], 1)} ГБ*\n"

    # Топ рефералы
    refs_text = ""
    for row in stats["top_refs"]:
        name = f"@{row[0]}" if row[0] else f"id{row[1]}"
        refs_text += f"  • {name}: *{row[2]}* чел.\n"

    # Последние платежи
    payments_text = ""
    for row in stats["last_payments"]:
        name = f"@{row[0]}" if row[0] else "?"
        date = str(row[3])[:10]
        payments_text += f"  • {name} — *{row[1]}₽* / {row[2]} мес. ({date})\n"

    await cb.message.edit_text(
        f"📊 *Статистика KomoVPN*\n\n"
        f"👥 *Пользователи:*\n"
        f"  Всего: *{stats['total']}* | Активных: *{stats['active']}*\n"
        f"  За 24ч: *+{stats['new_24h']}* | За 7д: *+{stats['new_7d']}* | За 30д: *+{stats['new_30d']}*\n"
        f"  Триал использовали: *{stats['trials']}*\n\n"
        f"💰 *Доход:*\n"
        f"  За 7д: *{stats['rev_7d']}₽* | За 30д: *{stats['rev_30d']}₽*\n"
        f"  Всего: *{stats['total_revenue']}₽* ({stats['total_payments']} платежей)\n"
        f"  ⏳ Ожидают оплаты: *{stats['pending_payments']}*\n\n"
        f"⚠️ *Истекают:*\n"
        f"  Через 3 дня: *{stats['expiring_3d']}* | Через 7 дней: *{stats['expiring_7d']}*\n\n"
        f"📅 *Длительность подписок (активные):*\n"
        f"  < 1 месяца: *{stats['sub_lt1m']}*\n"
        f"  1–2 месяца: *{stats['sub_1to2m']}*\n"
        f"  2–3 месяца: *{stats['sub_2to3m']}*\n"
        f"  > 3 месяцев: *{stats['sub_gt3m']}*\n\n"
        f"🌐 *Трафик:*\n"
        f"  Суммарно: *{stats['total_traffic']} ГБ*\n"
        + (f"  Топ пользователи:\n{traffic_text}" if traffic_text else "") +
        f"\n👥 *Рефералы:*\n"
        f"  Всего пришло по ссылке: *{stats['total_refs']}*\n"
        + (f"  Топ рефереры:\n{refs_text}" if refs_text else "") +
        f"\n🤖 *KomoGPT:*\n"
        f"  Пользователей: *{stats['gpt_users']}* | Сообщений: *{stats['gpt_msgs']}*\n\n"
        f"🎟 *Промокоды использовано:* *{stats['promo_uses']}*\n\n"
        + (f"💳 *Последние платежи:*\n{payments_text}" if payments_text else ""),
        parse_mode="Markdown", reply_markup=admin_menu()
    )
    await cb.answer()

@router.callback_query(F.data == "admin_users")
async def admin_users(cb: CallbackQuery):
    if not admin_guard(cb): return
    users = await get_all_users()
    if not users:
        return await cb.message.edit_text("Нет пользователей", reply_markup=admin_menu())
    lines = ["👥 Пользователи:\n"]
    for u in users:
        icon = "✅" if u["active"] else "❌"
        username = (u["username"] or "").replace("_","").replace("*","").replace("[","").replace("`","")
        name = f"@{username}" if username else f"id{u['user_id']}"
        lines.append(f"{icon} {name} | {u['paid_until'] or '—'} | {u['traffic_used_gb']:.1f}GB")
    text = "\n".join(lines)[:4000]
    await cb.message.edit_text(text, reply_markup=admin_menu())
    await cb.answer()

@router.callback_query(F.data == "admin_pending")
async def admin_pending(cb: CallbackQuery):
    if not admin_guard(cb): return
    payments = await get_pending_payments()
    if not payments:
        return await cb.answer("Нет ожидающих платежей", show_alert=True)
    rows = []
    for p in payments:
        name = f"@{p['username']}" if p["username"] else f"id{p['user_id']}"
        months = p["months"] if "months" in p.keys() else 1
        rows.append([
            InlineKeyboardButton(text=f"✅ #{p['id']} {name} {p['amount']}₽ ({months}м)", callback_data=f"confirm_{p['id']}_{p['user_id']}"),
            InlineKeyboardButton(text="❌", callback_data=f"reject_{p['id']}_{p['user_id']}"),
        ])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
    await cb.message.edit_text(
        "⏳ *Ожидают подтверждения:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

@router.callback_query(F.data == "admin_expiring")
async def admin_expiring(cb: CallbackQuery):
    if not admin_guard(cb): return
    users = await get_expiring_users(3)
    if not users:
        return await cb.answer("Нет истекающих подписок", show_alert=True)
    lines = ["⚠️ *Истекают в ближайшие 3 дня:*\n"]
    for u in users:
        name = f"@{u['username']}" if u["username"] else f"id{u['user_id']}"
        lines.append(f"• {name} — до {u['paid_until']}")
    await cb.message.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_deactivate")
async def admin_deactivate(cb: CallbackQuery):
    if not admin_guard(cb): return
    expired = await get_expired_users()
    if not expired:
        return await cb.answer("Нет истёкших подписок", show_alert=True)
    count = 0
    for u in expired:
        await deactivate_user(u["user_id"])
        # Удаляем все 3 конфига + прокси
        uuids = [uid for uid in [u["uuid"], u["uuid2"], u["uuid3"]] if uid]
        await remove_client_multi_async(uuids)
        await remove_proxy_client_async(u["user_id"])
        count += 1
    await cb.answer(f"✅ Деактивировано {count} пользователей", show_alert=True)

@router.callback_query(F.data == "admin_requisites")
async def admin_requisites(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    current = await get_setting("requisites") or "не установлены"
    await cb.message.edit_text(f"💳 Текущие реквизиты:\n`{current}`\n\nОтправьте новые:", parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_requisites)

@router.message(AdminStates.waiting_requisites)
async def save_requisites(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await set_setting("requisites", msg.text)
    await state.clear()
    await msg.answer("✅ Реквизиты сохранены!", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_price")
async def admin_price(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    current = await get_setting("price") or str(PRICE)
    await cb.message.edit_text(f"💰 Текущая цена: *{current}₽/мес*\n\nОтправьте новую цену (число):", parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_price)

@router.message(AdminStates.waiting_price)
async def save_price(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    if not msg.text.isdigit():
        return await msg.answer("❌ Введите число")
    new_price = msg.text
    await set_setting("price", new_price)

    # Обновляем .env чтобы значение применилось после рестарта
    import re, os
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = os.path.abspath(env_path)
    with open(env_path) as f:
        content = f.read()
    if re.search(r"^PRICE=", content, re.MULTILINE):
        content = re.sub(r"^PRICE=.*$", f"PRICE={new_price}", content, flags=re.MULTILINE)
    else:
        content += f"\nPRICE={new_price}"
    with open(env_path, "w") as f:
        f.write(content)

    # Применяем в текущем процессе без рестарта
    import config
    config.PRICE = int(new_price)

    await state.clear()
    await msg.answer(f"✅ Цена обновлена: {new_price}₽/мес", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    await cb.message.edit_text("📢 Отправьте текст рассылки (Markdown поддерживается):")
    await state.set_state(AdminStates.waiting_broadcast)

@router.message(AdminStates.waiting_broadcast)
async def admin_broadcast_send(msg: Message, state: FSMContext, bot):
    if msg.from_user.id != ADMIN_ID: return
    await state.clear()
    users = await get_all_users()
    sent = failed = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], msg.text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
    await msg.answer(f"📢 Рассылка завершена\n✅ {sent} | ❌ {failed}", reply_markup=admin_menu())

@router.callback_query(F.data.startswith("confirm_"))
async def confirm_pay(cb: CallbackQuery, bot):
    if not admin_guard(cb): return
    parts = cb.data.split("_")
    payment_id, user_id = int(parts[1]), int(parts[2])
    payment = await get_payment(payment_id)
    if not payment or payment["status"] != "pending":
        return await cb.answer("Платёж уже обработан", show_alert=True)
    user = await get_user(user_id)
    months = payment["months"] if "months" in payment.keys() else 1

    from handlers.user import PLANS
    days = PLANS[months]["days"] if months in PLANS else months * 30

    # Продление: если подписка ещё активна — добавляем к текущей дате
    base = datetime.now()
    if user["paid_until"] and user["active"]:
        try:
            base = max(base, datetime.strptime(user["paid_until"], "%Y-%m-%d"))
        except Exception:
            pass
    paid_until = (base + timedelta(days=days)).strftime("%Y-%m-%d")
    # Суммарный лимит пропорционально дням
    traffic_limit = int(TRAFFIC_LIMITS.get(months, TRAFFIC_LIMITS.get(1, 50)) * days / 30)

    await confirm_payment(payment_id)
    await activate_user(user_id, paid_until, traffic_limit)
    # Добавляем все 3 конфига в xray
    uuids = [uid for uid in [user["uuid"], user["uuid2"], user["uuid3"]] if uid]
    await add_client_multi_async(uuids, str(user_id))
    await add_proxy_client_async(user_id)

    # Бонус рефереру: +7 дней
    if user["referred_by"]:
        referrer = await get_user(user["referred_by"])
        if referrer and referrer["active"] and referrer["paid_until"]:
            try:
                ref_until = datetime.strptime(referrer["paid_until"], "%Y-%m-%d") + timedelta(days=7)
                await activate_user(user["referred_by"], ref_until.strftime("%Y-%m-%d"))
                await bot.send_message(
                    user["referred_by"],
                    "🎁 *Ваш друг оплатил подписку!*\nВы получили +7 дней к подписке.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await bot.send_message(
        user_id,
        f"🎉 *Оплата подтверждена!*\n\n"
        f"✅ Подписка активна до *{paid_until}*\n\n"
        f"Нажмите /start → 🔑 *Мой конфиг*",
        parse_mode="Markdown"
    )
    # Удаляем сообщение "ожидайте"
    try:
        if payment["waiting_msg_id"] and payment["waiting_chat_id"]:
            await bot.delete_message(payment["waiting_chat_id"], payment["waiting_msg_id"])
    except Exception:
        pass
    await cb.message.edit_text(f"✅ Платёж #{payment_id} подтверждён ({months} мес.)", reply_markup=admin_menu())

@router.callback_query(F.data.startswith("reject_"))
async def reject_pay(cb: CallbackQuery, bot):
    if not admin_guard(cb): return
    parts = cb.data.split("_")
    payment_id, user_id = int(parts[1]), int(parts[2])
    payment = await get_payment(payment_id)
    # Удаляем сообщение "ожидайте"
    try:
        if payment and payment["waiting_msg_id"] and payment["waiting_chat_id"]:
            await bot.delete_message(payment["waiting_chat_id"], payment["waiting_msg_id"])
    except Exception:
        pass
    await bot.send_message(user_id, "❌ *Оплата не подтверждена.*\nОбратитесь к администратору.", parse_mode="Markdown")
    await cb.message.edit_text(f"❌ Платёж #{payment_id} отклонён", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_support")
async def admin_support(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    current = await get_setting("support_username", "@admin")
    await cb.message.edit_text(f"🆘 Текущий username поддержки: `{current}`\n\nОтправьте новый (например @myusername):", parse_mode="Markdown")
    await state.set_state(AdminStates.waiting_support)

@router.message(AdminStates.waiting_support)
async def save_support(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await set_setting("support_username", msg.text)
    await state.clear()
    await msg.answer("✅ Username поддержки сохранён!", reply_markup=admin_menu())

@router.callback_query(F.data == "admin_back")
async def admin_back(cb: CallbackQuery):
    if not admin_guard(cb): return
    await cb.message.edit_text("🔧 *Админ-панель*", parse_mode="Markdown", reply_markup=admin_menu())

# ─── Статус сервера ───────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin_server")
async def admin_server(cb: CallbackQuery):
    if not admin_guard(cb): return
    await cb.answer("⏳ Собираю данные...")
    import subprocess, time, psutil, platform

    # Сервисы
    services = {}
    for svc in ["vpn-bot", "vpn-api", "xray", "nginx", "messenger"]:
        r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
        services[svc] = "✅" if r.stdout.strip() == "active" else "❌"
    # MTProto через Docker
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "mtproto"], capture_output=True, text=True)
    services["mtproto-proxy"] = "✅" if r.stdout.strip() == "true" else "❌"

    # Системные метрики
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    boot = psutil.boot_time()
    uptime_s = int(time.time() - boot)
    uptime = f"{uptime_s//86400}д {(uptime_s%86400)//3600}ч {(uptime_s%3600)//60}м"

    # Пинг до xray
    try:
        import socket
        t = time.time()
        s = socket.create_connection(("127.0.0.1", 4443), timeout=1)
        s.close()
        xray_ping = f"{round((time.time()-t)*1000)} мс"
    except:
        xray_ping = "❌"

    # Активные соединения
    conns = len(psutil.net_connections())

    # Топ процессов по CPU
    top = sorted(psutil.process_iter(['name','cpu_percent','memory_percent']),
                 key=lambda p: p.info['cpu_percent'], reverse=True)[:3]
    top_str = "\n".join(f"  • {p.info['name'][:15]}: CPU {p.info['cpu_percent']:.1f}% RAM {p.info['memory_percent']:.1f}%" for p in top)

    # Load average
    load = psutil.getloadavg()
    cpu_count = psutil.cpu_count()

    # Docker контейнеры
    dr = subprocess.run(["docker", "ps", "--format", "{{.Names}} {{.Status}}"], capture_output=True, text=True)
    docker_str = "\n".join(f"  🐳 {l}" for l in dr.stdout.strip().splitlines()) or "  нет"

    # Пинг до xray и MTProto
    import socket, time as _time
    def _tcp_ping(host, port):
        try:
            t = _time.monotonic()
            s = socket.create_connection((host, port), timeout=2)
            s.close()
            return f"{round((_time.monotonic()-t)*1000)} мс"
        except:
            return "❌"

    xray_ping = _tcp_ping("127.0.0.1", 4443)
    mtproto_ping = _tcp_ping("127.0.0.1", 2443)

    text = (
        "🖥 *Статус сервера*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*Сервисы:*\n"
        f"{services['xray']} xray  {services['vpn-bot']} бот  {services['vpn-api']} API\n"
        f"{services['nginx']} nginx  {services['mtproto-proxy']} MTProto  {services['messenger']} чат\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*Ресурсы:*\n"
        f"🔥 CPU: *{cpu}%* (ядер: {cpu_count})\n"
        f"📊 Load avg: *{load[0]:.2f} {load[1]:.2f} {load[2]:.2f}*\n"
        f"💾 RAM: *{ram.percent}%* ({ram.used//1024**2} / {ram.total//1024**2} МБ)\n"
        f"💿 Диск: *{disk.percent}%* ({disk.used//1024**3:.1f} / {disk.total//1024**3:.1f} ГБ)\n"
        f"⏱ Uptime: *{uptime}*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "*Сеть:*\n"
        f"📤 Отправлено: *{net.bytes_sent/1024**3:.2f} ГБ*\n"
        f"📥 Получено: *{net.bytes_recv/1024**3:.2f} ГБ*\n"
        f"🔌 TCP соединений: *{conns}*\n"
        f"📡 Пинг xray: *{xray_ping}*\n"
        f"📡 Пинг MTProto: *{mtproto_ping}*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"*Docker:*\n{docker_str}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"*Топ процессов:*\n{top_str}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_server")],
        [InlineKeyboardButton(text="🔁 Рестарт xray", callback_data="admin_restart_xray"),
         InlineKeyboardButton(text="🔁 Рестарт бота", callback_data="admin_restart_bot")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")],
    ])
    try:
        await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await cb.message.answer(text, parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "admin_restart_xray")
async def admin_restart_xray(cb: CallbackQuery):
    if not admin_guard(cb): return
    import subprocess
    subprocess.run(["systemctl", "restart", "xray"])
    await cb.answer("✅ xray перезапущен", show_alert=True)

@router.callback_query(F.data == "admin_restart_bot")
async def admin_restart_bot(cb: CallbackQuery):
    if not admin_guard(cb): return
    await cb.answer("🔄 Перезапускаю бота...", show_alert=True)
    import subprocess, asyncio
    await asyncio.sleep(1)
    subprocess.Popen(["systemctl", "restart", "vpn-bot"])

# ─── Промокоды ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin_promo")
async def admin_promo(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    await cb.message.edit_text(
        "🎟 *Создать промокод*\n\n"
        "Отправьте в формате:\n"
        "`КОД ДНЕЙ [ИСПОЛЬЗОВАНИЙ]`\n\n"
        "Примеры:\n"
        "`WELCOME7 7` — 7 дней, безлимит\n"
        "`VIP30 30 1` — 30 дней, 1 использование\n"
        "`PROMO0 0 100` — скидка без дней, 100 использований",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]])
    )
    await state.set_state(AdminStates.waiting_promo)

@router.message(AdminStates.waiting_promo)
async def save_promo(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await state.clear()
    parts = msg.text.strip().split()
    if len(parts) < 2:
        return await msg.answer("❌ Формат: КОД ДНЕЙ [ИСПОЛЬЗОВАНИЙ]")
    code = parts[0].upper()
    try:
        days = int(parts[1])
        uses = int(parts[2]) if len(parts) > 2 else None
    except ValueError:
        return await msg.answer("❌ Дни и использования должны быть числами")
    await create_promo_code(code, days, uses)
    await msg.answer(
        f"✅ Промокод создан!\n\n"
        f"Код: `{code}`\n"
        f"Дней: *{days}*\n"
        f"Использований: *{'∞' if uses is None else uses}*",
        parse_mode="Markdown", reply_markup=admin_menu()
    )

# ─── Масс промокоды ───────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin_mass_promo")
async def admin_mass_promo(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    await cb.message.edit_text(
        "📦 *Генерация промокодов*\n\n"
        "Отправьте в формате:\n"
        "`КОЛИЧЕСТВО ДНЕЙ`\n\n"
        "Примеры:\n"
        "`10 7` — 10 промокодов по 7 дней\n"
        "`50 30` — 50 промокодов по 30 дней\n\n"
        "Каждый промокод одноразовый (1 использование)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]])
    )
    await state.set_state(AdminStates.waiting_mass_promo)

@router.message(AdminStates.waiting_mass_promo)
async def generate_mass_promo(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await state.clear()
    parts = msg.text.strip().split()
    if len(parts) != 2:
        return await msg.answer("❌ Формат: КОЛИЧЕСТВО ДНЕЙ")
    try:
        count = int(parts[0])
        days = int(parts[1])
    except ValueError:
        return await msg.answer("❌ Количество и дни должны быть числами")
    if count < 1 or count > 100:
        return await msg.answer("❌ Количество от 1 до 100")
    if days < 1:
        return await msg.answer("❌ Дни должны быть больше 0")
    
    codes = []
    for _ in range(count):
        code = ''.join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
        await create_promo_code(code, days, 1)
        codes.append(code)
    
    codes_text = '\n'.join(f"`{c}`" for c in codes)
    await msg.answer(
        f"✅ Создано *{count}* промокодов по *{days}* дней:\n\n{codes_text}",
        parse_mode="Markdown", reply_markup=admin_menu()
    )


# ─── Ручная активация пользователя ───────────────────────────────────────────
@router.callback_query(F.data == "admin_activate")
async def admin_activate_start(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    await cb.message.edit_text(
        "👤 *Активировать пользователя*\n\n"
        "Отправьте в формате:\n"
        "`USER_ID МЕСЯЦЕВ`\n\n"
        "Пример: `123456789 1`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")]])
    )
    await state.set_state(AdminStates.waiting_activate_id)

@router.message(AdminStates.waiting_activate_id)
async def admin_activate_do(msg: Message, state: FSMContext, bot):
    if msg.from_user.id != ADMIN_ID: return
    await state.clear()
    parts = msg.text.strip().split()
    if len(parts) < 2:
        return await msg.answer("❌ Формат: USER_ID МЕСЯЦЕВ")
    try:
        user_id = int(parts[0])
        months = int(parts[1])
    except ValueError:
        return await msg.answer("❌ Неверный формат")
    user = await get_user(user_id)
    if not user:
        return await msg.answer("❌ Пользователь не найден")
    base = datetime.now()
    if user["paid_until"] and user["active"]:
        try:
            base = max(base, datetime.strptime(user["paid_until"], "%Y-%m-%d"))
        except Exception:
            pass
    paid_until = (base + timedelta(days=30 * months)).strftime("%Y-%m-%d")
    traffic_limit = TRAFFIC_LIMITS.get(months, 50) * months
    await activate_user(user_id, paid_until, traffic_limit)
    uuids = [uid for uid in [user["uuid"], user["uuid2"], user["uuid3"]] if uid]
    await add_client_multi_async(uuids, str(user_id))
    await add_proxy_client_async(user_id)
    try:
        await bot.send_message(user_id, f"🎉 *Подписка активирована на {months} мес.!*\n\nДо: *{paid_until}*", parse_mode="Markdown")
    except Exception:
        pass
    await msg.answer(f"✅ Пользователь {user_id} активирован до {paid_until}", reply_markup=admin_menu())

# ─── Экспорт пользователей ────────────────────────────────────────────────────
@router.callback_query(F.data == "admin_export")
async def admin_export(cb: CallbackQuery):
    if not admin_guard(cb): return
    users = await get_all_users()
    lines = ["ID,Username,Active,PaidUntil,TrafficGB,CreatedAt"]
    for u in users:
        lines.append(f"{u['user_id']},{u['username'] or ''},{u['active']},{u['paid_until'] or ''},{u['traffic_used_gb']:.2f},{u['created_at'] or ''}")
    csv_data = "\n".join(lines).encode()
    from aiogram.types import BufferedInputFile
    await cb.message.answer_document(
        BufferedInputFile(csv_data, "users_export.csv"),
        caption=f"📤 Экспорт пользователей ({len(users)} чел.)"
    )
    await cb.answer()

@router.callback_query(F.data == "admin_backup")
async def admin_backup(cb: CallbackQuery):
    if not admin_guard(cb): return
    await cb.answer("⏳ Создаю архив...")
    import zipfile, io, os
    from aiogram.types import BufferedInputFile
    from datetime import datetime

    DIRS = ["/root/vpn_bot", "/root/vpn_web", "/root/messenger"]
    EXCLUDE_DIRS = {"venv", "__pycache__", ".git", "node_modules", ".gradle", ".idea", "build",
                    "vendor", "pkg", "bin", "obj", "dist", "cache", ".cache", "go"}
    EXCLUDE_EXTS = {".pyc", ".tgz", ".gz", ".db-shm", ".db-wal", ".wasm", ".so", ".a", ".o",
                    ".class", ".jar", ".aar", ".apk", ".exe", ".bin"}
    EXCLUDE_FILES = {"messenger", "messenger_bin", "messenger_new", "rnnoise.wasm",
                     "go.sum", "vpn.db"}
    MAX_FILE_MB = 2

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for base in DIRS:
            if not os.path.exists(base): continue
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
                for fname in files:
                    if fname in EXCLUDE_FILES: continue
                    if any(fname.endswith(e) for e in EXCLUDE_EXTS): continue
                    fpath = os.path.join(root, fname)
                    try:
                        if os.path.getsize(fpath) > MAX_FILE_MB * 1024 * 1024: continue
                        zf.write(fpath, os.path.relpath(fpath, "/root"))
                    except Exception:
                        continue

    size_mb = buf.tell() / 1024 / 1024
    buf.seek(0)
    ts = datetime.now().strftime("%Y%m%d_%H%M")

    if size_mb > 49:
        await cb.message.answer(f"⚠️ Архив слишком большой ({size_mb:.1f} МБ), не могу отправить через Telegram.")
        return

    await cb.message.answer_document(
        BufferedInputFile(buf.read(), f"backup_{ts}.zip"),
        caption=f"Бэкап {ts}, размер {size_mb:.1f} МБ",
        parse_mode=None
    )


# ─── Регионы для выбора ───────────────────────────────────────────────────────
REGIONS = [
    ("🇩🇪", "Germany"),    ("🇳🇱", "Netherlands"), ("🇫🇷", "France"),
    ("🇬🇧", "UK"),         ("🇵🇱", "Poland"),       ("🇨🇿", "Czech Republic"),
    ("🇦🇹", "Austria"),    ("🇨🇭", "Switzerland"),  ("🇸🇪", "Sweden"),
    ("🇳🇴", "Norway"),     ("🇩🇰", "Denmark"),      ("🇧🇪", "Belgium"),
    ("🇱🇹", "Lithuania"),  ("🇱🇻", "Latvia"),       ("🇪🇪", "Estonia"),
    ("🇺🇸", "USA"),        ("🇨🇦", "Canada"),       ("🇯🇵", "Japan"),
    ("🇸🇬", "Singapore"),  ("🇦🇺", "Australia"),    ("🇧🇷", "Brazil"),
    ("🇹🇷", "Turkey"),     ("🇺🇦", "Ukraine"),      ("🇲🇩", "Moldova"),
]

def _regions_keyboard():
    rows = []
    for i in range(0, len(REGIONS), 3):
        chunk = REGIONS[i:i+3]
        rows.append([
            InlineKeyboardButton(text=f"{flag} {name}", callback_data=f"srv_region_{flag}_{name}")
            for flag, name in chunk
        ])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="admin_servers")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ─── Список серверов ──────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin_servers")
async def admin_servers_list(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    await state.clear()
    servers = await get_servers()
    rows = []
    for s in servers:
        rows.append([InlineKeyboardButton(
            text=f"{s['flag']} {s['name']} — {s['ip']}",
            callback_data=f"srv_info_{s['id']}"
        )])
    rows.append([InlineKeyboardButton(text="➕ Добавить сервер", callback_data="srv_add")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
    await cb.message.edit_text(
        f"🌍 *Серверы VPN* ({len(servers)} шт.)\n\nВыберите сервер или добавьте новый:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )

@router.callback_query(F.data.startswith("srv_info_"))
async def srv_info(cb: CallbackQuery):
    if not admin_guard(cb): return
    server_id = int(cb.data.split("_")[2])
    s = await get_server(server_id)
    if not s:
        return await cb.answer("Сервер не найден", show_alert=True)
    await cb.message.edit_text(
        f"{s['flag']} *{s['name']}*\n\n"
        f"🖥 IP: `{s['ip']}`\n"
        f"👤 SSH: `{s['ssh_user']}`\n"
        f"🔑 Public key: `{s['public_key']}`\n"
        f"📅 Добавлен: {s['added_at'][:10]}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Удалить сервер", callback_data=f"srv_delete_{server_id}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_servers")],
        ])
    )

@router.callback_query(F.data.startswith("srv_delete_"))
async def srv_delete(cb: CallbackQuery):
    if not admin_guard(cb): return
    server_id = int(cb.data.split("_")[2])
    s = await get_server(server_id)
    if not s:
        return await cb.answer("Сервер не найден", show_alert=True)
    await delete_server(server_id)
    # Обновляем sub-файлы всех активных пользователей
    from database import get_all_users
    import asyncio
    users = await get_all_users()
    loop = asyncio.get_event_loop()
    for u in users:
        if u["active"] and u["sub_token"]:
            try:
                from database import _generate_sub_file
                await loop.run_in_executor(None, _generate_sub_file,
                    u["user_id"], u["uuid"], u["uuid2"], u["uuid3"], u["sub_token"])
            except Exception:
                pass
    await cb.message.edit_text(
        f"✅ Сервер {s['flag']} {s['name']} удалён из подписок.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К серверам", callback_data="admin_servers")]
        ])
    )

# ─── Добавление сервера (FSM) ─────────────────────────────────────────────────
@router.callback_query(F.data == "srv_add")
async def srv_add_start(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    await cb.message.edit_text(
        "🖥 *Добавление сервера*\n\nВведите IP-адрес нового VPS:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_servers")
        ]])
    )
    await state.set_state(AdminStates.server_ip)

@router.message(AdminStates.server_ip)
async def srv_add_ip(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await state.update_data(ip=msg.text.strip())
    await msg.answer(
        "👤 Введите SSH-пользователя (обычно `root`):",
        parse_mode="Markdown"
    )
    await state.set_state(AdminStates.server_ssh_user)

@router.message(AdminStates.server_ssh_user)
async def srv_add_user(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await state.update_data(ssh_user=msg.text.strip())
    await msg.answer("🔑 Введите SSH-пароль:")
    await state.set_state(AdminStates.server_ssh_pass)

@router.message(AdminStates.server_ssh_pass)
async def srv_add_pass(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await state.update_data(ssh_pass=msg.text.strip())
    await msg.answer(
        "🌍 Выберите регион сервера:",
        reply_markup=_regions_keyboard()
    )
    await state.set_state(AdminStates.server_region)

@router.callback_query(F.data.startswith("srv_region_"), AdminStates.server_region)
async def srv_add_region(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    # формат: srv_region_{flag}_{name}
    parts = cb.data.split("_", 3)
    flag, name = parts[2], parts[3]
    data = await state.get_data()
    await state.clear()

    ip = data["ip"]
    ssh_user = data["ssh_user"]
    ssh_pass = data["ssh_pass"]

    await cb.message.edit_text(
        f"⏳ *Добавление сервера {flag} {name}*\n\n"
        f"🔗 IP: `{ip}`\n\n"
        f"1️⃣ Генерация ключей...",
        parse_mode="Markdown"
    )

    # Собираем клиентов всех активных пользователей
    from database import get_all_users
    import asyncio
    users = await get_all_users()
    clients = []
    for u in users:
        if u["active"]:
            for i, uid in enumerate([u["uuid"], u["uuid2"], u["uuid3"]]):
                if uid:
                    email = str(u["user_id"]) if i == 0 else f"{u['user_id']}_c{i+1}"
                    clients.append({"id": uid, "email": email, "flow": "xtls-rprx-vision"})

    try:
        from xray import install_xray_server, sync_clients_to_server
        loop = asyncio.get_event_loop()

        await cb.message.edit_text(
            f"⏳ *Добавление сервера {flag} {name}*\n\n"
            f"🔗 IP: `{ip}`\n\n"
            f"✅ Ключи сгенерированы\n"
            f"2️⃣ Подключение к серверу и установка xray (~2 мин)...",
            parse_mode="Markdown"
        )

        result = await loop.run_in_executor(
            None, install_xray_server, ip, ssh_user, ssh_pass, clients
        )
        public_key = result["public_key"]
        short_id = result["short_id"]
    except Exception as e:
        await cb.message.edit_text(
            f"❌ Ошибка установки:\n`{e}`",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="◀️ К серверам", callback_data="admin_servers")
            ]])
        )
        return

    await cb.message.edit_text(
        f"⏳ *Добавление сервера {flag} {name}*\n\n"
        f"🔗 IP: `{ip}`\n\n"
        f"✅ Ключи сгенерированы\n"
        f"✅ xray установлен и запущен\n"
        f"3️⃣ Сохранение в БД и обновление подписок...",
        parse_mode="Markdown"
    )

    await add_server(name, flag, ip, ssh_user, ssh_pass, public_key, short_id)

    # Обновляем sub-файлы всех активных пользователей
    for u in users:
        if u["active"] and u["sub_token"]:
            try:
                from database import _generate_sub_file
                await loop.run_in_executor(None, _generate_sub_file,
                    u["user_id"], u["uuid"], u["uuid2"], u["uuid3"], u["sub_token"])
            except Exception:
                pass

    await cb.message.edit_text(
        f"✅ Сервер {flag} *{name}* добавлен!\n\n"
        f"🖥 IP: `{ip}`\n"
        f"🔑 Public key: `{public_key}`\n\n"
        f"Подписки всех активных пользователей обновлены.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ К серверам", callback_data="admin_servers")
        ]])
    )

# ─── Проверка пользователя по UUID ───────────────────────────────────────────
@router.callback_query(F.data == "admin_check_uuid")
async def admin_check_uuid_start(cb: CallbackQuery, state: FSMContext):
    if not admin_guard(cb): return
    await cb.message.edit_text(
        "🔍 *Проверка пользователя*\n\n"
        "Отправьте user\\_id, @username или UUID:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")
        ]])
    )
    await state.set_state(AdminStates.waiting_check_uuid)

@router.message(Command("checkuser"))
async def cmd_checkuser(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await msg.answer("🔍 Отправьте user_id, @username или UUID:")
    await state.set_state(AdminStates.waiting_check_uuid)

@router.message(AdminStates.waiting_check_uuid)
async def admin_check_uuid_do(msg: Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID: return
    await state.clear()
    query = msg.text.strip().lstrip("@").lower()

    import aiosqlite
    from database import DB
    from xray import get_user_traffic_detail
    from balance import get_balance

    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT * FROM users WHERE
               CAST(user_id AS TEXT) = ?
               OR lower(username) = ?
               OR lower(uuid)  LIKE ?
               OR lower(uuid2) LIKE ?
               OR lower(uuid3) LIKE ?""",
            (query, query, f"%{query}%", f"%{query}%", f"%{query}%")
        ) as cur:
            users = await cur.fetchall()

    if not users:
        return await msg.answer("❌ Пользователь не найден.")

    for u in users:
        uid = u["user_id"]

        # Трафик из xray
        try:
            detail = await asyncio.get_event_loop().run_in_executor(
                None, get_user_traffic_detail, str(uid)
            )
            vpn_gb   = detail["vpn"]
            proxy_gb = detail["proxy"]
            total_gb = detail["total"]
        except Exception:
            vpn_gb = proxy_gb = total_gb = 0.0

        # Баланс
        bal = await get_balance(uid)

        # Промокоды
        async with aiosqlite.connect(DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT code, used_at FROM promo_uses WHERE user_id=? ORDER BY used_at DESC",
                (uid,)
            ) as cur:
                promos = await cur.fetchall()
            async with db.execute(
                "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC LIMIT 5",
                (uid,)
            ) as cur:
                payments = await cur.fetchall()

        # Дней до истечения
        days_str = "—"
        if u["paid_until"]:
            try:
                delta = (datetime.strptime(u["paid_until"], "%Y-%m-%d").date() - datetime.now().date()).days
                days_str = f"{delta} дн." if delta >= 0 else f"истекла {abs(delta)} дн. назад"
            except Exception:
                days_str = u["paid_until"]

        # Реферал
        ref_str = "—"
        if u["referred_by"]:
            ref_str = f"`{u['referred_by']}`"

        # Промокоды строкой
        promo_str = "\n".join(f"  • `{p['code']}` ({str(p['used_at'])[:10]})" for p in promos) or "  нет"

        # Платежи строкой
        pay_str = "\n".join(
            f"  • #{p['id']} {p['amount']}₽ / {p['months']}м — {p['status']} ({str(p['created_at'])[:10]})"
            for p in payments
        ) or "  нет"

        text = (
            f"👤 *Пользователь*\n\n"
            f"🆔 ID: `{uid}`\n"
            f"📛 Username: @{u['username'] or '—'}\n"
            f"📅 Зарегистрирован: {str(u['created_at'])[:10]}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Подписка:*\n"
            f"  Статус: {'✅ активна' if u['active'] else '❌ не активна'}\n"
            f"  До: {u['paid_until'] or '—'} ({days_str})\n"
            f"  Триал: {'использован' if u['trial_used'] else 'не использован'}\n\n"
            f"*Трафик:*\n"
            f"  Лимит: {u['traffic_limit_gb'] or 0} ГБ\n"
            f"  VPN: {vpn_gb:.2f} ГБ | Прокси: {proxy_gb:.2f} ГБ\n"
            f"  Итого: {total_gb:.2f} ГБ\n"
            f"  Заблокирован по трафику: {'да' if u['traffic_blocked'] else 'нет'}\n\n"
            f"*UUID:*\n"
            f"  1: `{u['uuid']}`\n"
            f"  2: `{u['uuid2'] or '—'}`\n"
            f"  3: `{u['uuid3'] or '—'}`\n\n"
            f"*Sub-token:* `{u['sub_token'] or '—'}`\n\n"
            f"💰 Баланс: *{bal}₽*\n"
            f"👥 Реферал от: {ref_str}\n\n"
            f"*Промокоды:*\n{promo_str}\n\n"
            f"*Платежи (последние 5):*\n{pay_str}"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Активировать", callback_data=f"admin_act1_{uid}"),
                InlineKeyboardButton(text="❌ Деактивировать", callback_data=f"admin_deact_{uid}"),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")],
        ])
        await msg.answer(text, parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data.startswith("admin_act1_"))
async def quick_activate(cb: CallbackQuery):
    if not admin_guard(cb): return
    user_id = int(cb.data.split("_")[2])
    user = await get_user(user_id)
    if not user:
        return await cb.answer("Пользователь не найден", show_alert=True)
    base = datetime.now()
    if user["paid_until"] and user["active"]:
        try:
            base = max(base, datetime.strptime(user["paid_until"], "%Y-%m-%d"))
        except Exception:
            pass
    paid_until = (base + timedelta(days=30)).strftime("%Y-%m-%d")
    await activate_user(user_id, paid_until, TRAFFIC_LIMITS.get(1, 100))
    uuids = [u for u in [user["uuid"], user["uuid2"], user["uuid3"]] if u]
    await add_client_multi_async(uuids, str(user_id))
    await add_proxy_client_async(user_id)
    await cb.answer(f"✅ Активирован до {paid_until}", show_alert=True)

@router.callback_query(F.data.startswith("admin_deact_"))
async def quick_deactivate(cb: CallbackQuery):
    if not admin_guard(cb): return
    user_id = int(cb.data.split("_")[2])
    user = await get_user(user_id)
    if not user:
        return await cb.answer("Пользователь не найден", show_alert=True)
    await deactivate_user(user_id)
    uuids = [u for u in [user["uuid"], user["uuid2"], user["uuid3"]] if u]
    await remove_client_multi_async(uuids)
    await remove_proxy_client_async(user_id)
    await cb.answer("❌ Деактивирован", show_alert=True)
