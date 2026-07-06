from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from datetime import datetime, timedelta
import qrcode, io, asyncio, secrets

from database import (
    get_user, create_user, create_payment, get_setting,
    update_traffic, activate_trial, get_referral_count, get_payment,
    create_login_code, ensure_sub_token, extend_user_days, has_any_payment, DB,
    set_payment_waiting_msg
)
from xray import (
    new_uuid, generate_vless_link, generate_vless_configs,
    get_user_traffic_detail, add_client, add_client_multi,
    add_proxy_client, remove_proxy_client, get_proxy_credentials,
    remove_client, remove_client_multi,
    generate_ws_link, generate_grpc_link, generate_split_link,
    add_client_multi_async, remove_client_multi_async,
    add_proxy_client_async, remove_proxy_client_async,
)
from config import PRICE, TRAFFIC_LIMIT_GB, TRAFFIC_LIMITS, ADMIN_ID, MTPROTO_LINK, AITUNNEL_KEY, AITUNNEL_URL, GPT_MODEL

router = Router()

PLANS = {
    0:  {"label": "7 дней",      "months": 0,  "discount": 0, "days": 7},
    1:  {"label": "1 месяц",     "months": 1,  "discount": 0, "days": 30},
    3:  {"label": "3 месяца",    "months": 3,  "discount": 20, "days": 90},
    6:  {"label": "6 месяцев",   "months": 6,  "discount": 35, "days": 180},
    12: {"label": "12 месяцев",  "months": 12, "discount": 50, "days": 360},
}

def plan_price(months: int) -> int:
    import config
    p = PLANS[months]
    d = p["discount"]
    days = p["days"]
    return int(config.PRICE * days / 30 * (1 - d / 100))

def traffic_bar(used: float, limit: int, vpn_gb: float = None, proxy_gb: float = None) -> str:
    pct = min(used / limit, 1.0) if limit else 0
    filled = int(pct * 10)
    color = "🟥" if pct > 0.8 else ("🟨" if pct > 0.5 else "🟩")
    bar = f"{color * filled}{'⬜' * (10 - filled)}"
    remaining = max(0, limit - used)
    text = (
        f"{bar}\n"
        f"📤 Использовано: *{used:.2f} ГБ* из *{limit} ГБ*\n"
        f"📥 Осталось: *{remaining:.2f} ГБ* ({(1-pct)*100:.0f}%)"
    )
    if vpn_gb is not None and proxy_gb is not None:
        text += f"\n\n🔒 VPN: *{vpn_gb:.2f} ГБ*  |  🌍 Прокси: *{proxy_gb:.2f} ГБ*"
    return text

def days_left(paid_until: str | None) -> str:
    if not paid_until:
        return "—"
    try:
        delta = (datetime.strptime(paid_until, "%Y-%m-%d").date() - datetime.now().date()).days
        if delta < 0:  return "❌ подписка истекла"
        if delta == 0: return "⚠️ последний день"
        if delta <= 3: return f"⚠️ {delta} дн. (скоро истечёт!)"
        return f"{delta} дн."
    except Exception:
        return paid_until

def _home_text() -> str:
    import config
    return (
        "🌐 *KomoVPN — быстрый и надёжный доступ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 VPN: *VLESS + XTLS-Reality*\n"
        "🌍 Прокси: *SOCKS5 + HTTP*\n"
        "⚡️ Скорость: без ограничений\n"
        "📦 Трафик: *50–2400 ГБ* на период\n"
        f"💰 От *{config.PRICE}₽/мес* · скидки до 30%\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 *KomoGPT* — AI-чат прямо здесь или в отдельном боте [@luna\_komoku\_bot](https://t.me/luna_komoku_bot)\n\n"
        "Выберите действие 👇"
    )

def main_menu(active: bool = False):
    if active:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 VPN конфиг", callback_data="config"),
             InlineKeyboardButton(text="🌍 Прокси", callback_data="proxy")],
            [InlineKeyboardButton(text="🔗 Подписка", callback_data="sub_link"),
             InlineKeyboardButton(text="📊 Статус", callback_data="status")],
            [InlineKeyboardButton(text="🤖 KomoGPT", callback_data="gpt_chat"),
             InlineKeyboardButton(text="💳 Оплатить", callback_data="pay_plans")],
            [InlineKeyboardButton(text="📖 Инструкции", callback_data="howto"),
             InlineKeyboardButton(text="👥 Рефералы", callback_data="referral")],
            [InlineKeyboardButton(text="🎟 Промокод", callback_data="promo_input"),
             InlineKeyboardButton(text="🌐 Сайт", callback_data="web_login")],
            [InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
             InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Мой статус", callback_data="status"),
         InlineKeyboardButton(text="💳 Оплатить", callback_data="pay_plans")],
        [InlineKeyboardButton(text="📖 Инструкции", callback_data="howto"),
         InlineKeyboardButton(text="👥 Рефералы", callback_data="referral")],
        [InlineKeyboardButton(text="🎟 Промокод", callback_data="promo_input"),
         InlineKeyboardButton(text="🌐 Войти на сайт", callback_data="web_login")],
        [InlineKeyboardButton(text="💰 Баланс", callback_data="balance"),
         InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
    ])

def status_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить трафик", callback_data="refresh_traffic")],
        [InlineKeyboardButton(text="💳 Продлить", callback_data="pay_plans"),
         InlineKeyboardButton(text="🔑 VPN конфиг", callback_data="config")],
        [InlineKeyboardButton(text="🌍 Прокси", callback_data="proxy"),
         InlineKeyboardButton(text="🔗 Подписка", callback_data="sub_link")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ])

# ─── /start ───────────────────────────────────────────────────────────────────
@router.message(CommandStart())
async def start(msg: Message, state: FSMContext):
    args = msg.text.split()
    referred_by = None
    if len(args) > 1 and args[1].startswith("ref"):
        try:
            ref = int(args[1][3:])
            if ref != msg.from_user.id:
                referred_by = ref
        except ValueError:
            pass

    user = await get_user(msg.from_user.id)
    is_new = not user
    if not user:
        await create_user(msg.from_user.id, msg.from_user.username or "", new_uuid(), referred_by)
        user = await get_user(msg.from_user.id)

    # Сохраняем referred_by в state
    if referred_by:
        await state.update_data(referred_by=referred_by)

    extra = []
    if not user["trial_used"] and not user["active"] and not await has_any_payment(msg.from_user.id):
        extra = [[InlineKeyboardButton(text="🎁 Попробовать бесплатно (7 дней)", callback_data="trial")]]

    kb = InlineKeyboardMarkup(inline_keyboard=extra + main_menu(user["active"]).inline_keyboard)
    await msg.answer(_home_text(), parse_mode="Markdown", reply_markup=kb)

# ─── Пробный период ───────────────────────────────────────────────────────────
@router.callback_query(F.data == "trial")
async def trial(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user or user["trial_used"]:
        return await cb.answer("Пробный период уже использован.", show_alert=True)
    paid_until = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    await activate_trial(cb.from_user.id, paid_until)
    uuids = [uid for uid in [user["uuid"], user["uuid2"], user["uuid3"]] if uid]
    await add_client_multi_async(uuids, str(cb.from_user.id))
    await add_proxy_client_async(cb.from_user.id)
    await cb.message.edit_text(
        "🎁 *Пробный период активирован на 7 дней!*\n\n"
        "✅ VPN и Прокси доступны · 10 ГБ трафика\n\n"
        "Нажмите *🔑 VPN конфиг* или *🌍 Прокси* для подключения.",
        parse_mode="Markdown", reply_markup=main_menu(True)
    )

# ─── Акция: реф-бонус ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "begin")
async def ref_bonus(cb: CallbackQuery, state: FSMContext):
    user = await get_user(cb.from_user.id)
    if not user:
        return await cb.answer("Сначала нажми /start", show_alert=True)
    if user["trial_used"] or user["active"] or await has_any_payment(cb.from_user.id):
        return await cb.answer("Бонус уже недоступен.", show_alert=True)

    data = await state.get_data()
    referred_by = data.get("referred_by")

    # Активируем нового пользователя на 30 дней
    await extend_user_days(cb.from_user.id, 30)
    uuids = [uid for uid in [user["uuid"], user["uuid2"], user["uuid3"]] if uid]
    await add_client_multi_async(uuids, str(cb.from_user.id))
    await add_proxy_client_async(cb.from_user.id)
    import aiosqlite as _aio
    async with _aio.connect(DB) as db:
        await db.execute("UPDATE users SET trial_used=1 WHERE user_id=?", (cb.from_user.id,))
        await db.commit()
    await state.clear()

    if referred_by:
        referrer = await get_user(referred_by)
        if referrer:
            await extend_user_days(referred_by, 30)
            ref_uuids = [uid for uid in [referrer["uuid"], referrer["uuid2"], referrer["uuid3"]] if uid]
            await add_client_multi_async(ref_uuids, str(referred_by))
            try:
                await cb.bot.send_message(
                    referred_by,
                    "🎁 *Ваш друг принял приглашение!*\n\nВам начислен *+1 месяц* VPN доступа.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        bonus_text = "🎉 *Добро пожаловать!*\n\n✅ Доступ открыт · 100 ГБ трафика на 1 месяц"
    else:
        bonus_text = "🎉 *Добро пожаловать!*\n\n✅ Доступ открыт · 100 ГБ трафика на 1 месяц"

    await cb.message.edit_text(
        bonus_text + "\n\nНажмите *🔑 VPN конфиг* для подключения.",
        parse_mode="Markdown", reply_markup=main_menu(True)
    )

# ─── Статус ───────────────────────────────────────────────────────────────────
async def _status_text(user_id: int, refresh: bool = False) -> str:
    user = await get_user(user_id)
    if not user:
        return "Сначала нажми /start"
    limit = user["traffic_limit_gb"] if user["traffic_limit_gb"] else TRAFFIC_LIMIT_GB
    vpn_gb, proxy_gb = None, None

    if user["active"]:
        if refresh:
            detail = await asyncio.get_event_loop().run_in_executor(None, get_user_traffic_detail, str(user_id))
            detail = dict(detail)
        else:
            # Только кэш — быстро, без блокировки
            from xray import _parse_xray_stats
            import subprocess, json as _json
            from config import XRAY_CONFIG
            cache_path = XRAY_CONFIG.replace("config.json", "traffic_cache.json")
            try:
                with open(cache_path) as f:
                    cache = _json.load(f)
                vpn_b   = cache.get(str(user_id), 0) + cache.get(f"u{user_id}", 0)
                proxy_b = cache.get(f"proxy_{user_id}", 0)
                detail  = {
                    "vpn":   round(vpn_b   / 1024**3, 3),
                    "proxy": round(proxy_b / 1024**3, 3),
                    "total": round((vpn_b + proxy_b) / 1024**3, 3),
                }
            except Exception:
                detail = {"vpn": 0, "proxy": 0, "total": user["traffic_used_gb"]}

        traffic  = detail["total"]
        vpn_gb   = detail["vpn"]
        proxy_gb = detail["proxy"]
        if refresh:
            await update_traffic(user_id, traffic)
    else:
        traffic = user["traffic_used_gb"]

    active_str = "✅ *Активна*" if user["active"] else "❌ *Не активна*"
    bar = traffic_bar(traffic, limit, vpn_gb, proxy_gb)
    dl = days_left(user["paid_until"])
    refs = await get_referral_count(user_id)
    hint = " _(кэш, нажмите 🔄 для обновления)_" if user["active"] and not refresh else ""

    text = (
        f"📊 *Ваш статус*\n\n"
        f"Подписка: {active_str}\n"
        f"Действует ещё: *{dl}*\n"
        f"Оплачено до: {user['paid_until'] or '—'}\n\n"
        f"📶 *Трафик (VPN + Прокси):*{hint}\n{bar}\n\n"
        f"👥 Приглашено друзей: *{refs}*"
    )
    if not user["active"]:
        text += "\n\n💡 Нажмите *Оплатить* для активации."
    return text

@router.callback_query(F.data == "status")
async def status(cb: CallbackQuery):
    text = await _status_text(cb.from_user.id)
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=status_menu())
    await cb.answer()

@router.callback_query(F.data == "refresh_traffic")
async def refresh_traffic(cb: CallbackQuery):
    await cb.answer("⏳ Обновляю...")
    text = await _status_text(cb.from_user.id, refresh=True)
    try:
        await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=status_menu())
    except Exception:
        pass

# ─── VPN конфиг + QR ─────────────────────────────────────────────────────────
@router.callback_query(F.data == "config")
async def send_config(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user or not user["active"]:
        return await cb.answer("❌ Подписка не активна.", show_alert=True)

    sub_token = await ensure_sub_token(cb.from_user.id)
    sub_url = f"https://lklunallm.icu/sub/{sub_token}"
    sub_full_url = f"https://lklunallm.icu/sub-full/{sub_token}"
    main_link = generate_vless_link(user["uuid"])
    ws_link = generate_ws_link(user["uuid"])

    qr = qrcode.make(sub_url)
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    buf.seek(0)
    await cb.message.delete()
    await cb.message.answer_photo(
        BufferedInputFile(buf.read(), "qr.png"),
        caption=(
            "🔑 *Ваш VPN конфиг*\n\n"
            "📷 *QR-код* — ссылка на подписку (все 4 конфига)\n"
            "Отсканируйте в v2rayNG / Hiddify / Streisand\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔗 *Подписка (стандарт):*\n"
            f"`{sub_url}`\n\n"
            "🇷🇺 *Подписка Full (RU bypass — Ozon, Сбер, ВК...):*\n"
            f"`{sub_full_url}`\n\n"
            "🔒 *Основной VLESS (Reality):*\n"
            f"`{main_link}`\n\n"
            "🌐 *CDN / Белый список* (работает везде):\n"
            f"`{ws_link}`\n\n"
            "📱 *Android / iOS / PC:* Happ (рекомендуем)\n"
            "📱 *Android:* v2rayNG, NekoBox\n"
            "🍎 *iOS:* Streisand, Shadowrocket\n"
            "💻 *PC:* Hiddify"
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 CDN конфиг отдельно", callback_data="config_cdn")],
            [InlineKeyboardButton(text="🚫🇷🇺 Подписка без RU сайтов", callback_data="config_noru")],
            [InlineKeyboardButton(text="🔄 Переподключить VPN", callback_data="reconnect_vpn")],
            [InlineKeyboardButton(text="🌍 Прокси", callback_data="proxy_new")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home_new")],
        ])
    )
    await cb.answer()

@router.callback_query(F.data == "config_noru")
async def send_config_noru(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user or not user["active"]:
        return await cb.answer("❌ Подписка не активна.", show_alert=True)
    sub_token = await ensure_sub_token(cb.from_user.id)
    url = f"https://lklunallm.icu/sub-noru/{sub_token}"
    await cb.answer()
    await cb.message.answer(
        "🚫🇷🇺 *Подписка без RU сайтов*\n\n"
        "Российские сайты и приложения (ВК, Сбер, Озон, Wildberries...) идут *напрямую*, без VPN.\n"
        "Весь остальной трафик — через VPN.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔗 *Ссылка на подписку:*\n"
        f"`{url}`\n\n"
        "⚠️ *Работает только в Happ* — приложение автоматически применит правила маршрутизации.\n\n"
        "📱 Скачать Happ:\n"
        "• [Android](https://play.google.com/store/apps/details?id=com.happproxy)\n"
        "• [iOS](https://apps.apple.com/us/app/happ-proxy-utility/id6504287215)\n"
        "• [Windows](https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe)\n"
        "• [macOS](https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.macOS.universal.dmg)",
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_main")],
        ])
    )

@router.callback_query(F.data == "config_cdn")
async def send_config_cdn(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user or not user["active"]:
        return await cb.answer("❌ Подписка не активна.", show_alert=True)
    ws = generate_ws_link(user["uuid"])
    grpc = generate_grpc_link(user["uuid"])
    split = generate_split_link(user["uuid"])
    await cb.answer()
    await cb.message.answer(
        "🌐 *CDN конфиги — Белый список*\n\n"
        "Работают когда заблокированы обычные VPN.\n"
        "Трафик идёт через Cloudflare — не блокируется.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "4️⃣ *WebSocket* (универсальный):\n"
        f"`{ws}`\n\n"
        "5️⃣ *gRPC* (стабильный, РКН не трогает):\n"
        f"`{grpc}`\n\n"
        "6️⃣ *SplitHTTP* (максимальная маскировка):\n"
        f"`{split}`\n\n"
        "💡 Попробуй по порядку — какой работает у твоего оператора.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔑 Все конфиги", callback_data="config")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="home_new")],
        ])
    )

# ─── Переподключение VPN (пересоздаёт клиента в xray) ────────────────────────
@router.callback_query(F.data == "reconnect_vpn")
async def reconnect_vpn(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user or not user["active"]:
        return await cb.answer("❌ Подписка не активна.", show_alert=True)
    await cb.answer("⏳ Переподключаю...")
    uuids = [uid for uid in [user["uuid"], user["uuid2"], user["uuid3"]] if uid]
    await remove_client_multi_async(uuids)
    await add_client_multi_async(uuids, str(cb.from_user.id))
    await cb.message.edit_caption(
        cb.message.caption + "\n\n✅ *VPN переподключён!* Попробуйте подключиться снова.",
        parse_mode="Markdown",
        reply_markup=cb.message.reply_markup
    )

# ─── Утилита пинга ───────────────────────────────────────────────────────────
async def _ping_host(host: str, port: int) -> str:
    import asyncio, time
    try:
        t = time.monotonic()
        r, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3)
        ms = round((time.monotonic() - t) * 1000)
        w.close()
        await w.wait_closed()
        return f"🟢 {ms} мс"
    except Exception:
        return "🔴 недоступен"

# ─── Прокси ───────────────────────────────────────────────────────────────────
@router.callback_query(F.data.in_({"proxy", "proxy_new"}))
async def proxy_info(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user or not user["active"]:
        return await cb.answer("❌ Подписка не активна.", show_alert=True)
    back = "home_new" if cb.data == "proxy_new" else "back_main"

    # Пинг MTProto сервера
    ping = await _ping_host("46.226.164.14", 2443)

    detail = await asyncio.get_event_loop().run_in_executor(
        None, get_user_traffic_detail, str(cb.from_user.id)
    )
    limit = user["traffic_limit_gb"] if user["traffic_limit_gb"] else TRAFFIC_LIMIT_GB
    total_gb = detail["total"]
    bar = traffic_bar(total_gb, limit, detail["vpn"], detail["proxy"])

    mtproto_link = MTPROTO_LINK

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔌 Подключить MTProto в Telegram", url=mtproto_link)],
        [InlineKeyboardButton(text="🔄 Обновить пинг", callback_data=cb.data)],
        [InlineKeyboardButton(text="📊 Мой трафик", callback_data="status")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data=back)],
    ])
    await cb.message.edit_text(
        "📡 *MTProto прокси*\n\n"
        "Специальный прокси для Telegram — маскирует трафик под HTTPS.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🖥 Сервер: `46.226.164.14`\n"
        "🔌 Порт: `2443`\n"
        "🔑 Секрет: `ee8911e90ce8846aeeef83539091769c1b706574726f766963682e7275`\n"
        f"📡 Пинг: {ping}\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📶 *Трафик:*\n"
        f"{bar}\n\n"
        "Нажмите кнопку — Telegram подключится автоматически.",
        parse_mode="Markdown", reply_markup=kb
    )
    await cb.answer()

# ─── Переподключение прокси (пересоздаёт аккаунт в xray) ─────────────────────
@router.callback_query(F.data.startswith("reconnect_proxy_"))
async def reconnect_proxy(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user or not user["active"]:
        return await cb.answer("❌ Подписка не активна.", show_alert=True)
    await remove_proxy_client_async(cb.from_user.id)
    await add_proxy_client_async(cb.from_user.id)
    await cb.answer("✅ Прокси переподключён! Попробуйте снова.", show_alert=True)

# ─── IPv6 прокси ──────────────────────────────────────────────────────────────
@router.callback_query(F.data == "proxy_ipv6")
async def proxy_ipv6(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user or not user["active"]:
        return await cb.answer("❌ Подписка не активна.", show_alert=True)
    
    host = "185.105.90.127"
    port = 1080
    
    # Ссылка для Telegram (подключение по IPv4, выход через IPv6)
    tg_link = f"tg://socks?server={host}&port={port}"
    
    text = "🌐 *IPv6 SOCKS5 прокси*\n\n"
    text += f"📡 *Адрес:* `{host}:{port}`\n"
    text += "🔓 *Авторизация:* НЕТ\n\n"
    text += "━━━━━━━━━━━━━━━━━━━━\n"
    text += "💡 *Как использовать:*\n"
    text += "• Нажмите кнопку ниже для Telegram\n"
    text += "• Или настройте вручную в приложении\n\n"
    text += "✅ *Трафик выходит через IPv6*"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔌 Подключить в Telegram", url=tg_link)],
        [InlineKeyboardButton(text="◀️ Назад к прокси", callback_data="proxy")],
    ])
    
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await cb.answer()

@router.callback_query(F.data == "proxy_ipv6_change")
async def proxy_ipv6_change(cb: CallbackQuery):
    # Убираем функцию смены - оставляем один адрес
    await cb.answer("Используется один стабильный IPv6 адрес", show_alert=True)

# ─── Обработчики для кнопок после фото (новое сообщение) ─────────────────────
@router.callback_query(F.data == "home_new")
async def home_new(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    active = user["active"] if user else False
    await cb.message.delete()
    await cb.message.answer(_home_text(), parse_mode="Markdown", reply_markup=main_menu(active))
    await cb.answer()

# ─── Тарифы ───────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "pay_plans")
async def pay_plans(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    is_active = user and user["active"]
    rows = []
    for months, p in PLANS.items():
        price = plan_price(months)
        disc = f" (-{p['discount']}%)" if p["discount"] else ""
        if is_active:
            rows.append([InlineKeyboardButton(
                text=f"{'⭐️ ' if p['discount'] else ''}+{p['label']} — {price}₽{disc}",
                callback_data=f"pay_{months}"
            )])
        else:
            gb = int(TRAFFIC_LIMITS.get(months, TRAFFIC_LIMITS.get(1, 50)) * p["days"] / 30)
            rows.append([InlineKeyboardButton(
                text=f"{'⭐️ ' if p['discount'] else ''}{p['label']} — {price}₽{disc} · {gb} ГБ",
                callback_data=f"pay_{months}"
            )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])

    if is_active:
        new_until = None
        if user["paid_until"]:
            try:
                from datetime import datetime, timedelta as _td
                base = max(datetime.now(), datetime.strptime(user["paid_until"], "%Y-%m-%d"))
                new_until = base.strftime("%Y-%m-%d")
            except Exception:
                pass
        text = (
            "🔄 *Продление подписки*\n\n"
            f"Текущая подписка активна до: *{user['paid_until']}*\n"
            "Дни добавятся к текущей дате окончания.\n\n"
            "⭐️ Скидка при оплате на 3+ месяца\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    else:
        traffic_desc = " / ".join(
            str(int(TRAFFIC_LIMITS.get(m, TRAFFIC_LIMITS.get(1, 50)) * PLANS[m]["days"] / 30))
            for m in PLANS
        )
        text = (
            "💳 *Выберите тариф*\n\n"
            "✅ Включает VPN + Прокси\n"
            f"📦 Трафик на период: *{traffic_desc} ГБ*\n"
            "⭐️ Скидка при оплате на 3+ месяца\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
    await cb.message.edit_text(text, parse_mode="Markdown",
                               reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@router.callback_query(F.data.regexp(r"^pay_\d+$"))
async def pay(cb: CallbackQuery):
    months = int(cb.data.split("_")[1])
    if months not in PLANS:
        return
    requisites = await get_setting("requisites")
    if not requisites:
        return await cb.answer("❌ Реквизиты не настроены.", show_alert=True)
    price = plan_price(months)
    payment_id = await create_payment(cb.from_user.id, price, months)
    plan = PLANS[months]
    disc_str = f"\n🎁 Скидка: *{plan['discount']}%*" if plan["discount"] else ""

    user = await get_user(cb.from_user.id)
    if user and user["active"] and user["paid_until"]:
        try:
            base = max(datetime.now(), datetime.strptime(user["paid_until"], "%Y-%m-%d"))
            new_until = (base + timedelta(days=plan["days"])).strftime("%Y-%m-%d")
        except Exception:
            new_until = "—"
        renewal_str = f"\n\n🔄 Подписка продлится до: *{new_until}*"
    else:
        renewal_str = ""

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"paid_{payment_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="pay_plans")],
    ])
    await cb.message.edit_text(
        f"💳 *{'Продление' if renewal_str else 'Оплата'} — {plan['label']}*\n\n"
        f"Сумма: *{price}₽*{disc_str}{renewal_str}\n\n"
        f"Реквизиты:\n`{requisites}`\n\n"
        f"1️⃣ Переведите *{price}₽*\n"
        f"2️⃣ Нажмите *«Я оплатил»*\n"
        f"3️⃣ Ожидайте подтверждения\n\n"
        f"🔖 Платёж: `#{payment_id}`",
        parse_mode="Markdown", reply_markup=kb
    )

@router.callback_query(F.data.startswith("paid_"))
async def paid_notify(cb: CallbackQuery, bot):
    payment_id = int(cb.data.split("_")[1])
    payment = await get_payment(payment_id)
    if not payment:
        return await cb.answer("❌ Платёж не найден.", show_alert=True)
    if payment["status"] != "pending":
        return await cb.answer("ℹ️ Этот платёж уже обработан.", show_alert=True)
    months = payment["months"] if "months" in payment.keys() else 1
    price = payment["amount"]
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"confirm_{payment_id}_{cb.from_user.id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject_{payment_id}_{cb.from_user.id}"),
    ]])
    await bot.send_message(
        ADMIN_ID,
        f"💰 *Новый платёж #{payment_id}*\n\n"
        f"👤 @{cb.from_user.username or '—'} (`{cb.from_user.id}`)\n"
        f"📅 Тариф: *{months} мес.*\n"
        f"💵 Сумма: *{price}₽*",
        parse_mode="Markdown", reply_markup=kb
    )
    # Удаляем старое сообщение, отправляем "ожидайте"
    try:
        await cb.message.delete()
    except Exception:
        pass
    waiting = await bot.send_message(
        cb.from_user.id,
        "⏳ *Запрос отправлен!*\n\nОжидайте подтверждения администратора.",
        parse_mode="Markdown"
    )
    await set_payment_waiting_msg(payment_id, waiting.message_id, cb.from_user.id)
    await cb.answer()

# ─── Реферальная программа (акция завершена) ─────────────────────────────────
@router.callback_query(F.data == "referral")
async def referral(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]])
    await cb.message.edit_text(
        "👥 *Реферальная программа*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Акция «Приведи друга» завершена.\n\n"
        "Следите за новыми акциями в боте! 🎉",
        parse_mode="Markdown", reply_markup=kb
    )
    await cb.answer()

# ─── Поддержка ────────────────────────────────────────────────────────────────
@router.callback_query(F.data == "support")
async def support(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]])
    admin_username = await get_setting("support_username", "@admin")
    await cb.message.edit_text(
        "🆘 *Поддержка*\n\n"
        f"По всем вопросам пишите: {admin_username}\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "❓ *Частые вопросы:*\n\n"
        "• *Не работает VPN?* — Проверьте, что подписка активна\n"
        "• *Медленная скорость?* — Попробуйте переподключиться\n"
        "• *Не работает прокси?* — Убедитесь в правильности логина/пароля\n"
        "• *Забыл конфиг?* — Нажмите 🔑 VPN конфиг в главном меню",
        parse_mode="Markdown", reply_markup=kb
    )
    await cb.answer()

# ─── Инструкция ───────────────────────────────────────────────────────────────
@router.callback_query(F.data == "howto")
async def howto(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Android", callback_data="howto_android"),
         InlineKeyboardButton(text="🍎 iOS", callback_data="howto_ios")],
        [InlineKeyboardButton(text="💻 Windows", callback_data="howto_windows"),
         InlineKeyboardButton(text="🍏 macOS", callback_data="howto_mac")],
        [InlineKeyboardButton(text="🌍 Прокси", callback_data="howto_proxy"),
         InlineKeyboardButton(text="🔗 Подписка", callback_data="howto_sub")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
    ])
    await cb.message.edit_text(
        "📖 *Инструкции по подключению*\n\n"
        "Выберите платформу или способ подключения 👇",
        parse_mode="Markdown", reply_markup=kb
    )
    await cb.answer()

@router.callback_query(F.data == "howto_android")
async def howto_android(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать Happ (рекомендуем)", url="https://play.google.com/store/apps/details?id=com.happproxy")],
        [InlineKeyboardButton(text="🔑 Получить конфиг", callback_data="config")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="howto")],
    ])
    await cb.message.edit_text(
        "📱 *Android — Happ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Установите *Happ* из Google Play\n\n"
        "2️⃣ Нажмите *🔗 Подписка* в боте → скопируйте ссылку\n\n"
        "3️⃣ В Happ: ➕ → *Импорт по URL*\n\n"
        "4️⃣ Нажмите ▶️ для подключения\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Альтернативы:* v2rayNG, NekoBox\n\n"
        "✅ Проверьте подключение на [2ip.ru](https://2ip.ru)",
        parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb
    )
    await cb.answer()

@router.callback_query(F.data == "howto_ios")
async def howto_ios(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать Happ (iOS)", url="https://apps.apple.com/us/app/happ-proxy-utility/id6504287215")],
        [InlineKeyboardButton(text="🔑 Получить конфиг", callback_data="config")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="howto")],
    ])
    await cb.message.edit_text(
        "🍎 *iOS — Happ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Установите *Happ* из App Store\n\n"
        "2️⃣ Нажмите *🔗 Подписка* в боте → скопируйте ссылку\n\n"
        "3️⃣ В Happ: ➕ → *Import from URL*\n\n"
        "4️⃣ Нажмите *Connect*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Альтернативы:* Streisand, Shadowrocket ($2.99)\n\n"
        "✅ Проверьте подключение на [2ip.ru](https://2ip.ru)",
        parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb
    )
    await cb.answer()

@router.callback_query(F.data == "howto_windows")
async def howto_windows(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать Happ (Windows)", url="https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe")],
        [InlineKeyboardButton(text="🔑 Получить конфиг", callback_data="config")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="howto")],
    ])
    await cb.message.edit_text(
        "💻 *Windows — Happ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Скачайте *Happ* по кнопке ниже\n\n"
        "2️⃣ Установите и запустите\n\n"
        "3️⃣ Нажмите *🔗 Подписка* в боте → скопируйте ссылку\n\n"
        "4️⃣ В Happ: ➕ → *Add from URL* → вставьте ссылку\n\n"
        "5️⃣ Нажмите *Connect*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Альтернатива:* Hiddify (github.com/hiddify)\n\n"
        "✅ Проверьте подключение на [2ip.ru](https://2ip.ru)",
        parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb
    )
    await cb.answer()

@router.callback_query(F.data == "howto_mac")
async def howto_mac(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📥 Скачать Happ (macOS)", url="https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.macOS.universal.dmg")],
        [InlineKeyboardButton(text="🔑 Получить конфиг", callback_data="config")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="howto")],
    ])
    await cb.message.edit_text(
        "🍏 *macOS — Happ*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "1️⃣ Скачайте *Happ* по кнопке ниже (.dmg)\n\n"
        "2️⃣ Установите (перетащите в Applications)\n\n"
        "3️⃣ Нажмите *🔗 Подписка* в боте → скопируйте ссылку\n\n"
        "4️⃣ В Happ: ➕ → *Add from URL* → вставьте ссылку\n\n"
        "5️⃣ Нажмите *Connect*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Альтернативы:* Hiddify, V2Box (App Store)\n\n"
        "✅ Проверьте подключение на [2ip.ru](https://2ip.ru)",
        parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb
    )
    await cb.answer()

@router.callback_query(F.data == "howto_proxy")
async def howto_proxy(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌍 Мои данные прокси", callback_data="proxy")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="howto")],
    ])
    await cb.message.edit_text(
        "🌍 *Настройка прокси*\n\n"
        "Данные для подключения — в разделе *🌍 Прокси*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📱 *Telegram (все платформы):*\n"
        "Нажмите кнопку *🔌 Подключить SOCKS5* прямо в боте\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🖥 *Windows 10/11:*\n"
        "Пуск → Параметры → Сеть и интернет\n"
        "→ Прокси → Использовать прокси-сервер\n"
        "→ Адрес: хост, Порт: HTTP-порт\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🍏 *macOS:*\n"
        "Системные настройки → Сеть\n"
        "→ Дополнительно → Прокси → SOCKS5\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🌐 *Chrome / Firefox:*\n"
        "Расширение *Proxy SwitchyOmega*\n"
        "→ Новый профиль → SOCKS5 → введите данные\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📱 *Android:*\n"
        "Настройки Wi-Fi → Изменить сеть\n"
        "→ Прокси: вручную → введите данные",
        parse_mode="Markdown", reply_markup=kb
    )
    await cb.answer()

@router.callback_query(F.data == "howto_sub")
async def howto_sub(cb: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Моя ссылка на подписку", callback_data="sub_link")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="howto")],
    ])
    await cb.message.edit_text(
        "🔗 *Ссылка на подписку*\n\n"
        "Это специальная ссылка, которую вы вставляете в приложение *один раз* — "
        "и оно автоматически загружает все конфиги и обновляет их при изменениях.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *Поддерживаемые приложения:*\n\n"
        "📱 *Happ* (Android / iOS / Windows / macOS) — рекомендуем\n"
        "   ➕ → Import from URL\n\n"
        "📱 *v2rayNG* (Android)\n"
        "   ➕ → Импорт из URL подписки\n\n"
        "💻 *Hiddify* (Windows / macOS / Linux)\n"
        "   ➕ → Add profile from URL\n\n"
        "📦 *NekoBox* (Android / PC)\n"
        "   Группы → ➕ → вставьте ссылку\n\n"
        "🍎 *Streisand* (iOS)\n"
        "   ➕ → Import from URL\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 Ссылка персональная — не передавайте её другим",
        parse_mode="Markdown", reply_markup=kb
    )
    await cb.answer()


@router.callback_query(F.data == "web_login")
async def web_login(cb: CallbackQuery):
    code = secrets.token_urlsafe(12)
    await create_login_code(cb.from_user.id, code)
    await cb.message.edit_text(
        "🌐 *Вход на сайт*\n\n"
        "Скопируйте код и вставьте его на сайте в поле входа:\n\n"
        f"`{code}`\n\n"
        "⏱ Код действует *10 минут*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Открыть сайт", url="https://lklunallm.icu")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
        ])
    )
    await cb.answer()

@router.callback_query(F.data == "sub_link")
async def sub_link(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    if not user or not user["active"]:
        return await cb.answer("❌ Подписка не активна.", show_alert=True)
    sub_token = await ensure_sub_token(cb.from_user.id)

    # Пересоздаём файл подписки если его нет
    import os
    sub_path = f"/opt/xray-sub/{sub_token}.sub"
    if not os.path.exists(sub_path):
        from database import activate_user
        from xray import generate_vless_configs
        # Регенерируем файл подписки
        from database import _generate_sub_file
        _generate_sub_file(cb.from_user.id, user["uuid"], user["uuid2"], user["uuid3"], sub_token)

    url = f"https://lklunallm.icu/sub/{sub_token}"
    url_full = f"https://lklunallm.icu/sub-full/{sub_token}"
    await cb.message.edit_text(
        "🔗 *Ссылка на подписку*\n\n"
        "Вставьте в приложение *один раз* — конфиги загрузятся и будут обновляться автоматически:\n\n"
        f"`{url}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ *Работает в:*\n"
        "📱 *Happ* (Android/iOS/PC) — ➕ → Import from URL\n"
        "📱 v2rayNG (Android) — ➕ → Импорт из URL\n"
        "💻 Hiddify (Win/Mac) — ➕ → Add from URL\n"
        "🍎 Streisand (iOS) — ➕ → Import from URL\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Ссылка персональная — не передавайте другим",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📖 Как использовать?", callback_data="howto_sub")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")],
        ])
    )
    await cb.answer()


@router.callback_query(F.data == "mtproto")
async def mtproto_info(cb: CallbackQuery):
    # MTProto теперь в разделе Прокси
    await proxy_info(cb)

@router.callback_query(F.data == "back_main")
async def back_main(cb: CallbackQuery):
    user = await get_user(cb.from_user.id)
    active = user["active"] if user else False
    try:
        await cb.message.edit_text(_home_text(), parse_mode="Markdown", reply_markup=main_menu(active))
    except Exception:
        try:
            await cb.message.delete()
        except Exception:
            pass
        await cb.message.answer(_home_text(), parse_mode="Markdown", reply_markup=main_menu(active))
    await cb.answer()

# ─── /status команда ──────────────────────────────────────────────────────────
@router.message(Command("status"))
async def cmd_status(msg: Message):
    text = await _status_text(msg.from_user.id)
    await msg.answer(text, parse_mode="Markdown", reply_markup=status_menu())

# ─── /traffic команда ─────────────────────────────────────────────────────────
@router.message(Command("traffic"))
async def cmd_traffic(msg: Message):
    user = await get_user(msg.from_user.id)
    if not user or not user["active"]:
        return await msg.answer("❌ Подписка не активна.")
    await msg.answer("⏳ Получаю данные о трафике...")
    text = await _status_text(msg.from_user.id, refresh=True)
    await msg.answer(text, parse_mode="Markdown", reply_markup=status_menu())

# ─── /promo команда ───────────────────────────────────────────────────────────
class PromoState(StatesGroup):
    waiting_code = State()

@router.message(Command("promo"))
async def cmd_promo(msg: Message, state: FSMContext):
    await msg.answer("🎟 Введите промокод:")
    await state.set_state(PromoState.waiting_code)

@router.callback_query(F.data == "promo_input")
async def promo_input(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "🎟 *Введите промокод*\n\nОтправьте код следующим сообщением:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
        ])
    )
    await state.set_state(PromoState.waiting_code)
    await cb.answer()

@router.message(PromoState.waiting_code)
async def handle_promo(msg: Message, state: FSMContext):
    from database import apply_promo_code, get_user
    await state.clear()
    code = msg.text.strip().upper()

    # Запоминаем был ли активен до применения
    user_before = await get_user(msg.from_user.id)
    was_active = user_before["active"] if user_before else False

    result = await apply_promo_code(msg.from_user.id, code)
    if result["ok"]:
        # Если стал активным — добавляем в xray
        if not was_active and result.get("days", 0) > 0:
            user = await get_user(msg.from_user.id)
            if user:
                uuids = [user["uuid"], user["uuid2"] or user["uuid"], user["uuid3"] or user["uuid"]]
                await add_client_multi_async(uuids, str(msg.from_user.id))
                await add_proxy_client_async(msg.from_user.id)
        await msg.answer(f"✅ *Промокод применён!*\n\n{result['message']}", parse_mode="Markdown", reply_markup=main_menu(True))
    else:
        await msg.answer(f"❌ {result['error']}", reply_markup=main_menu(True))

# ─── /help команда ────────────────────────────────────────────────────────────
@router.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "📖 *Команды KomoVPN*\n\n"
        "/start — Главное меню\n"
        "/status — Статус подписки\n"
        "/traffic — Обновить трафик\n"
        "/promo — Ввести промокод\n"
        "/help — Эта справка\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔑 VPN конфиг — в главном меню\n"
        "🌍 Прокси — в главном меню\n"
        "💳 Оплата — в главном меню",
        parse_mode="Markdown"
    )

# ─── /addtoken — регистрация токена Салюта для aLuna ─────────────────────────

class AddTokenState(StatesGroup):
    waiting_token = State()

@router.message(Command("addtoken"))
async def cmd_addtoken(msg: Message, state: FSMContext):
    await msg.answer(
        "🎙 *Регистрация токена SaluteSpeech*\n\n"
        "Отправь свой токен авторизации Салюта.\n\n"
        "Как получить токен:\n"
        "1. Зайди на developers.sber.ru\n"
        "2. Создай проект → SaluteSpeech\n"
        "3. Скопируй Authorization токен (Basic ...)\n\n"
        "Отправь токен следующим сообщением:",
        parse_mode="Markdown"
    )
    await state.set_state(AddTokenState.waiting_token)

@router.message(AddTokenState.waiting_token)
async def process_salute_token(msg: Message, state: FSMContext):
    await state.clear()
    token = msg.text.strip() if msg.text else ""
    if not token or len(token) < 20:
        await msg.answer("❌ Токен слишком короткий. Попробуй снова: /addtoken")
        return

    import hashlib, httpx
    from config import BOT_TOKEN
    bot_secret = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:16]

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "http://localhost:8000/api/alvoice/token/register",
                json={
                    "tg_user_id": msg.from_user.id,
                    "salute_token": token,
                    "bot_secret": bot_secret
                }
            )
        data = r.json()
        user_uuid = data.get("uuid", "")
        await msg.answer(
            f"✅ *Токен сохранён!*\n\n"
            f"Твой UUID для aLuna:\n`{user_uuid}`\n\n"
            f"Введи этот UUID в настройках приложения aLuna → Голос → UUID.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await msg.answer(f"❌ Ошибка сохранения: {e}")

# ─── Уведомление об истечении (вызывается из scheduler) ──────────────────────
async def notify_expiring(bot, user_id: int, days: int):
    if days == 0:
        text = "⚠️ *Подписка истекает сегодня!*\n\nПродлите сейчас, чтобы не потерять доступ."
    else:
        text = f"⚠️ *Подписка истекает через {days} дн.*\n\nПродлите заранее."
    try:
        await bot.send_message(
            user_id, text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Продлить", callback_data="pay_plans")]
            ])
        )
    except Exception:
        pass

# ─── KomoGPT чат ──────────────────────────────────────────────────────────────
import aiohttp as _aiohttp

# Хранилище истории: {user_id: [{"role": ..., "content": ...}]}
_gpt_history: dict[int, list] = {}

class GptState(StatesGroup):
    chatting = State()

@router.callback_query(F.data == "gpt_chat")
async def gpt_chat_start(cb: CallbackQuery, state: FSMContext):
    user = await get_user(cb.from_user.id)
    if not user or not user["active"]:
        return await cb.answer("❌ Нужна активная подписка для KomoGPT.", show_alert=True)
    _gpt_history.setdefault(cb.from_user.id, [])
    await state.set_state(GptState.chatting)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Отдельный бот KomoGPT", url="https://t.me/luna_komoku_bot")],
        [InlineKeyboardButton(text="🗑 Очистить историю", callback_data="gpt_clear")],
        [InlineKeyboardButton(text="◀️ Выйти из чата", callback_data="gpt_exit")],
    ])
    await cb.message.edit_text(
        "🤖 *KomoGPT* — AI чат\n\n"
        f"Модель: `{GPT_MODEL}`\n\n"
        "Просто напишите сообщение — я отвечу.\n"
        "История сохраняется в рамках сессии.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Хочешь больше?* В отдельном боте [@luna\_komoku\_bot](https://t.me/luna_komoku_bot):\n"
        "• 15+ моделей (GPT-5, Grok 4, DeepSeek R1...)\n"
        "• Голосовые сообщения 🎤\n"
        "• Режимы: переводчик, программист, аналитик\n"
        "• Inline-режим в любом чате\n"
        "• Экспорт истории в .md",
        parse_mode="Markdown", reply_markup=kb, disable_web_page_preview=True
    )
    await cb.answer()

@router.callback_query(F.data == "gpt_clear")
async def gpt_clear(cb: CallbackQuery):
    _gpt_history[cb.from_user.id] = []
    await cb.answer("✅ История очищена", show_alert=True)

@router.callback_query(F.data == "gpt_exit")
async def gpt_exit(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(cb.from_user.id)
    active = user["active"] if user else False
    await cb.message.edit_text(_home_text(), parse_mode="Markdown", reply_markup=main_menu(active))
    await cb.answer()

@router.message(GptState.chatting)
async def gpt_message(msg: Message, state: FSMContext):
    user = await get_user(msg.from_user.id)
    if not user or not user["active"]:
        await state.clear()
        return await msg.answer("❌ Подписка не активна.")

    history = _gpt_history.setdefault(msg.from_user.id, [])

    # Обработка фото
    if msg.photo:
        import base64 as _b64
        photo = msg.photo[-1]  # наибольшее разрешение
        file = await msg.bot.get_file(photo.file_id)
        file_bytes = await msg.bot.download_file(file.file_path)
        img_b64 = _b64.b64encode(file_bytes.read()).decode()
        caption = msg.caption or "Что на этом изображении?"
        user_content = [
            {"type": "text", "text": caption},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
        ]
    elif msg.text:
        user_content = msg.text
    else:
        return await msg.answer("❌ Поддерживаются только текст и фото.")

    history.append({"role": "user", "content": user_content})
    if len(history) > 20:
        history[:] = history[-20:]

    thinking = await msg.answer("⏳ _Думаю..._", parse_mode="Markdown")

    try:
        async with _aiohttp.ClientSession() as session:
            async with session.post(
                AITUNNEL_URL,
                headers={"Authorization": f"Bearer {AITUNNEL_KEY}", "Content-Type": "application/json"},
                json={"model": GPT_MODEL, "messages": history, "max_tokens": 2048},
                timeout=_aiohttp.ClientTimeout(total=60)
            ) as resp:
                data = await resp.json()
        answer = data["choices"][0]["message"]["content"].strip()
        history.append({"role": "assistant", "content": answer})

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🗑 Очистить историю", callback_data="gpt_clear"),
             InlineKeyboardButton(text="◀️ Выйти", callback_data="gpt_exit")],
        ])
        await thinking.delete()
        for i in range(0, len(answer), 4000):
            chunk = answer[i:i+4000]
            if i + 4000 >= len(answer):
                await msg.answer(chunk, reply_markup=kb)
            else:
                await msg.answer(chunk)
    except Exception as e:
        await thinking.delete()
        await msg.answer(f"❌ Ошибка: {e}")
