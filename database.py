import aiosqlite, os, base64, sqlite3
from datetime import datetime, date as _date


def calc_traffic_limit(paid_until_str: str) -> int:
    """Лимит трафика на месяц исходя из оставшихся месяцев подписки."""
    try:
        days_left = (datetime.strptime(paid_until_str, "%Y-%m-%d").date() - _date.today()).days
    except Exception:
        return 100
    months_left = days_left / 30
    if months_left >= 12: return 300
    if months_left >= 6:  return 250
    if months_left >= 3:  return 200
    if months_left >= 1:  return 150
    return 100

DB = os.path.join(os.path.dirname(__file__), "vpn.db")
SUB_DIR = "/opt/xray-sub"

# WAL mode для параллельных чтений без блокировок
def _enable_wal():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=10000")
    conn.close()

try:
    _enable_wal()
except Exception:
    pass

IP = "193.17.182.23"
PBK = "zXXtFmDQ_roZgOXXB4N7JxnTnSKqNn-S-YJq0BTL628"
SID = "7687f251aabd2b05"

def _generate_sub_file(user_id: int, uuid: str, uuid2: str, uuid3: str, token: str):
    import sqlite3 as _sqlite3

    # Получаем дополнительные серверы напрямую через sqlite3 (без asyncio)
    extra_servers = []
    try:
        conn = _sqlite3.connect(DB)
        conn.row_factory = _sqlite3.Row
        extra_servers = conn.execute("SELECT * FROM servers WHERE active=1").fetchall()
        conn.close()
    except Exception:
        pass

    uuids = [uuid, uuid2 or uuid, uuid3 or uuid]
    lines = []
    for i, (fp, sni, name) in enumerate([
        ("chrome",  "www.microsoft.com", "🇫🇮 Finland-Chrome"),
        ("firefox", "www.cloudflare.com","🇫🇮 Finland-Firefox"),
        ("safari",  "www.apple.com",     "🇫🇮 Finland-Safari"),
    ]):
        lines.append(f"vless://{uuids[i]}@{IP}:443?type=tcp&security=reality&pbk={PBK}&fp={fp}&sni={sni}&sid={SID}&flow=xtls-rprx-vision&encryption=none#{name}")

    # XHTTP + Reality
    for i, (fp, name) in enumerate([
        ("chrome",  "🇫🇮 XHTTP-Chrome"),
        ("firefox", "🇫🇮 XHTTP-Firefox"),
        ("safari",  "🇫🇮 XHTTP-Safari"),
    ]):
        lines.append(f"vless://{uuids[i]}@{IP}:444?type=xhttp&security=reality&pbk={PBK}&fp={fp}&sni=lklunallm.icu&sid={SID}&path=%2Fassets%2Fimg&mode=stream-one&encryption=none#{name}")

    # Дополнительные серверы (TCP + XHTTP)
    for s in extra_servers:
        lines.append(
            f"vless://{uuid}@{s['ip']}:443"
            f"?type=tcp&security=reality&pbk={s['public_key']}"
            f"&fp=chrome&sni=lklunallm.icu&sid={s['short_id']}"
            f"&flow=xtls-rprx-vision&encryption=none"
            f"#{s['flag']} {s['name']} - TCP"
        )
        lines.append(
            f"vless://{uuid}@{s['ip']}:444"
            f"?type=xhttp&security=reality&pbk={s['public_key']}"
            f"&fp=chrome&sni=lklunallm.icu&sid={s['short_id']}"
            f"&path=%2Fassets%2Fimg&mode=stream-one&encryption=none"
            f"#{s['flag']} {s['name']} - XHTTP"
        )
    os.makedirs(SUB_DIR, exist_ok=True)
    with open(f"{SUB_DIR}/{token}.sub", "w") as f:
        f.write(base64.b64encode("\n".join(lines).encode()).decode())

    # Sing-box JSON конфиг
    import json as _json
    singbox = {
        "log": {"level": "warn"},
        "dns": {
            "servers": [
                {"tag": "dns-direct", "address": "https://dns.google/dns-query", "detour": "direct"},
                {"tag": "dns-proxy",  "address": "https://1.1.1.1/dns-query",   "detour": "proxy"}
            ],
            "rules": [
                {"rule_set": ["ru", "ru-site"], "server": "dns-direct"}
            ]
        },
        "inbounds": [{"type": "tun", "tag": "tun-in", "interface_name": "utun0",
                      "inet4_address": "172.19.0.1/30", "stack": "system",
                      "auto_route": True, "strict_route": True, "sniff": True, "sniff_override_destination": True}],
        "outbounds": [
            {"type": "vless", "tag": "proxy", "server": IP, "server_port": 443,
             "uuid": uuids[0], "flow": "xtls-rprx-vision",
             "tls": {"enabled": True, "server_name": "www.microsoft.com",
                     "utls": {"enabled": True, "fingerprint": "chrome"},
                     "reality": {"enabled": True, "public_key": PBK, "short_id": SID}}},
            {"type": "direct", "tag": "direct"},
            {"type": "block",  "tag": "block"}
        ],
        "route": {
            "rule_set": [
                {"type": "remote", "tag": "ru",      "format": "binary", "download_detour": "direct",
                 "url": "https://github.com/runetfreedom/russia-v2ray-rules-dat/raw/release/sing-box/srs/geoip-ru.srs"},
                {"type": "remote", "tag": "ru-site", "format": "binary", "download_detour": "direct",
                 "url": "https://github.com/runetfreedom/russia-v2ray-rules-dat/raw/release/sing-box/srs/geosite-ru.srs"}
            ],
            "rules": [
                {"ip_is_private": True, "outbound": "direct"},
                {"rule_set": ["ru", "ru-site"], "outbound": "direct"},
                {"domain_suffix": [".ru"], "outbound": "direct"}
            ],
            "final": "proxy"
        }
    }
    os.makedirs(f"{SUB_DIR}/full-config", exist_ok=True)
    with open(f"{SUB_DIR}/full-config/{token}.json", "w") as f:
        _json.dump(singbox, f, indent=2, ensure_ascii=False)

def _delete_sub_file(token: str):
    path = f"{SUB_DIR}/{token}.sub"
    if os.path.exists(path):
        os.remove(path)

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                uuid TEXT,
                active INTEGER DEFAULT 0,
                paid_until TEXT,
                traffic_used_gb REAL DEFAULT 0,
                referred_by INTEGER DEFAULT NULL,
                trial_used INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                months INTEGER DEFAULT 1,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS login_codes (
                code TEXT PRIMARY KEY,
                user_id INTEGER,
                expires_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                days INTEGER DEFAULT 0,
                uses_left INTEGER,
                expires_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS promo_uses (
                code TEXT,
                user_id INTEGER,
                used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (code, user_id)
            )
        """)
        # Добавляем новые колонки если их нет (миграция)
        for col, definition in [
            ("referred_by", "INTEGER DEFAULT NULL"),
            ("trial_used", "INTEGER DEFAULT 0"),
            ("traffic_limit_gb", "INTEGER DEFAULT 50"),
            ("uuid2", "TEXT"),
            ("uuid3", "TEXT"),
            ("sub_token", "TEXT"),
        ]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except Exception:
                pass
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN months INTEGER DEFAULT 1")
        except Exception:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                flag TEXT,
                ip TEXT UNIQUE,
                ssh_user TEXT DEFAULT 'root',
                ssh_pass TEXT,
                public_key TEXT,
                short_id TEXT,
                active INTEGER DEFAULT 1,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col, definition in [
            ("traffic_blocked", "INTEGER DEFAULT 0"),
        ]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except Exception:
                pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS traffic_baseline (
                user_id INTEGER PRIMARY KEY,
                month TEXT,
                baseline_bytes INTEGER DEFAULT 0
            )
        """)
        await db.commit()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
            return await cur.fetchone()

async def create_user(user_id: int, username: str, uuid: str, referred_by: int = None):
    import secrets, uuid as _uuid
    sub_token = secrets.token_urlsafe(12)
    uuid2 = str(_uuid.uuid4())
    uuid3 = str(_uuid.uuid4())
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, uuid, uuid2, uuid3, referred_by, sub_token) VALUES (?,?,?,?,?,?,?)",
            (user_id, username, uuid, uuid2, uuid3, referred_by, sub_token)
        )
        await db.commit()

async def ensure_sub_token(user_id: int) -> str:
    """Генерирует sub_token если его нет (миграция старых пользователей)."""
    import secrets
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT sub_token FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
        if row and row[0]:
            return row[0]
        token = secrets.token_urlsafe(16)
        await db.execute("UPDATE users SET sub_token=? WHERE user_id=?", (token, user_id))
        await db.commit()
        return token

async def set_user_uuids(user_id: int, uuid2: str, uuid3: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET uuid2=?, uuid3=? WHERE user_id=? AND (uuid2 IS NULL OR uuid3 IS NULL)",
            (uuid2, uuid3, user_id)
        )
        await db.commit()

async def activate_user(user_id: int, paid_until: str, traffic_limit_gb: int = 50):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET active=1, paid_until=?, traffic_limit_gb=?, traffic_used_gb=0 WHERE user_id=?",
            (paid_until, traffic_limit_gb, user_id)
        )
        await db.commit()
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT uuid, uuid2, uuid3, sub_token FROM users WHERE user_id=?", (user_id,)) as cur:
            u = await cur.fetchone()
        if u and u["sub_token"]:
            _generate_sub_file(user_id, u["uuid"], u["uuid2"], u["uuid3"], u["sub_token"])

async def activate_trial(user_id: int, paid_until: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET active=1, paid_until=?, trial_used=1, traffic_limit_gb=10, traffic_used_gb=0 WHERE user_id=?",
            (paid_until, user_id)
        )
        await db.commit()
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT uuid, uuid2, uuid3, sub_token FROM users WHERE user_id=?", (user_id,)) as cur:
            u = await cur.fetchone()
        if u and u["sub_token"]:
            _generate_sub_file(user_id, u["uuid"], u["uuid2"], u["uuid3"], u["sub_token"])

async def deactivate_user(user_id: int):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT sub_token FROM users WHERE user_id=?", (user_id,)) as cur:
            u = await cur.fetchone()
        await db.execute("UPDATE users SET active=0 WHERE user_id=?", (user_id,))
        await db.commit()
        if u and u["sub_token"]:
            _delete_sub_file(u["sub_token"])

async def update_traffic(user_id: int, traffic_gb: float):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET traffic_used_gb=? WHERE user_id=?",
            (traffic_gb, user_id)
        )
        await db.commit()

async def block_user_traffic(user_id: int):
    """Блокирует пользователя по трафику (удаляет из Xray)."""
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET traffic_blocked=1 WHERE user_id=?",
            (user_id,)
        )
        await db.commit()

async def unblock_user_traffic(user_id: int):
    """Разблокирует пользователя по трафику."""
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET traffic_blocked=0 WHERE user_id=?",
            (user_id,)
        )
        await db.commit()

async def set_traffic_reset_date(user_id: int, date_str: str):
    """Устанавливает дату следующего сброса трафика."""
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET traffic_reset_date=? WHERE user_id=?",
            (date_str, user_id)
        )
        await db.commit()

async def reset_monthly_traffic(user_id: int):
    """Сбрасывает месячный трафик и устанавливает новую дату сброса."""
    from datetime import datetime, timedelta
    next_month = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-01")
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE users SET traffic_month_used_gb=0, traffic_reset_date=?, traffic_blocked=0 WHERE user_id=?",
            (next_month, user_id)
        )
        await db.commit()

async def get_traffic_blocked_users():
    """Возвращает пользователей, заблокированных по трафику."""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE traffic_blocked=1"
        ) as cur:
            return await cur.fetchall()

async def get_users_for_traffic_check():
    """Возвращает активных пользователей для проверки трафика."""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE active=1 AND traffic_blocked=0"
        ) as cur:
            return await cur.fetchall()

async def create_payment(user_id: int, amount: int, months: int = 1) -> int:
    async with aiosqlite.connect(DB) as db:
        cur = await db.execute(
            "INSERT INTO payments (user_id, amount, months) VALUES (?,?,?)",
            (user_id, amount, months)
        )
        await db.commit()
        return cur.lastrowid

async def confirm_payment(payment_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "UPDATE payments SET status='confirmed' WHERE id=?", (payment_id,)
        )
        await db.commit()

async def set_payment_waiting_msg(payment_id: int, msg_id: int, chat_id: int):
    async with aiosqlite.connect(DB) as db:
        try:
            await db.execute("ALTER TABLE payments ADD COLUMN waiting_msg_id INTEGER")
            await db.execute("ALTER TABLE payments ADD COLUMN waiting_chat_id INTEGER")
            await db.commit()
        except Exception:
            pass
        await db.execute(
            "UPDATE payments SET waiting_msg_id=?, waiting_chat_id=? WHERE id=?",
            (msg_id, chat_id, payment_id)
        )
        await db.commit()

async def get_payment(payment_id: int):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)) as cur:
            return await cur.fetchone()

async def get_setting(key: str, default: str = None):
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value)
        )
        await db.commit()

async def get_all_users():
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users") as cur:
            return await cur.fetchall()

async def get_pending_payments():
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT p.*, u.username FROM payments p JOIN users u ON p.user_id=u.user_id WHERE p.status='pending'"
        ) as cur:
            return await cur.fetchall()

async def extend_user_days(user_id: int, days: int):
    """Добавляет дни к подписке (или создаёт с нуля от сегодня)."""
    from datetime import datetime, timedelta
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT paid_until, uuid, uuid2, uuid3, sub_token FROM users WHERE user_id=?", (user_id,)) as cur:
            u = await cur.fetchone()
        if not u:
            return
        base = datetime.now()
        if u["paid_until"]:
            try:
                base = max(base, datetime.strptime(u["paid_until"], "%Y-%m-%d"))
            except Exception:
                pass
        new_until = (base + timedelta(days=days)).strftime("%Y-%m-%d")
        await db.execute(
            "UPDATE users SET active=1, paid_until=? WHERE user_id=?",
            (new_until, user_id)
        )
        await db.commit()
        if u["sub_token"]:
            _generate_sub_file(user_id, u["uuid"], u["uuid2"], u["uuid3"], u["sub_token"])

async def has_any_payment(user_id: int) -> bool:
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT COUNT(*) FROM payments WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            return (row[0] if row else 0) > 0

async def get_referral_count(user_id: int) -> int:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def get_revenue(days: int = 30) -> int:
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='confirmed' AND created_at >= datetime('now', ?)",
            (f"-{days} days",)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def get_expiring_users(days: int = 3):
    """Пользователи, у которых подписка истекает через <= days дней."""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE active=1 AND paid_until BETWEEN date('now') AND date('now', ?)",
            (f"+{days} days",)
        ) as cur:
            return await cur.fetchall()

async def get_expired_users():
    """Активные пользователи с истёкшей подпиской."""
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE active=1 AND paid_until < date('now')"
        ) as cur:
            return await cur.fetchall()

async def create_login_code(user_id: int, code: str):
    async with aiosqlite.connect(DB) as db:
        # Удаляем старые коды этого пользователя
        await db.execute("DELETE FROM login_codes WHERE user_id=?", (user_id,))
        await db.execute(
            "INSERT INTO login_codes (code, user_id, expires_at) VALUES (?, ?, datetime('now', '+10 minutes'))",
            (code, user_id)
        )
        await db.commit()

async def use_login_code(code: str):
    """Возвращает user_id если код валиден, иначе None. Удаляет код после использования."""
    async with aiosqlite.connect(DB) as db:
        async with db.execute(
            "SELECT user_id FROM login_codes WHERE code=? AND expires_at > datetime('now')",
            (code,)
        ) as cur:
            row = await cur.fetchone()
        if row:
            await db.execute("DELETE FROM login_codes WHERE code=?", (code,))
            await db.commit()
            return row[0]
        return None

async def apply_promo_code(user_id: int, code: str) -> dict:
    """Применяет промокод. Возвращает {"ok": True, "message": ...} или {"ok": False, "error": ...}."""
    from datetime import datetime, timedelta
    # Лимиты трафика по тарифам (ГБ/мес × месяцев)
    TRAFFIC_LIMITS = {1: 100, 3: 150, 6: 200, 12: 300}

    def days_to_traffic_gb(days: int) -> int:
        months = days / 30
        if months <= 1:   return TRAFFIC_LIMITS[1]  * 1
        elif months <= 3: return TRAFFIC_LIMITS[3]  * 3
        elif months <= 6: return TRAFFIC_LIMITS[6]  * 6
        else:             return TRAFFIC_LIMITS[12] * 12

    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM promo_codes WHERE code=? AND (uses_left IS NULL OR uses_left > 0) "
            "AND (expires_at IS NULL OR expires_at > datetime('now'))", (code,)
        ) as cur:
            promo = await cur.fetchone()
        if not promo:
            return {"ok": False, "error": "Промокод не найден или истёк"}
        async with db.execute("SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (code, user_id)) as cur:
            if await cur.fetchone():
                return {"ok": False, "error": "Промокод уже использован"}
        await db.execute("INSERT INTO promo_uses (code, user_id) VALUES (?,?)", (code, user_id))
        if promo["uses_left"] is not None:
            await db.execute("UPDATE promo_codes SET uses_left=uses_left-1 WHERE code=?", (code,))
        days = promo["days"] or 0
        if days > 0:
            async with db.execute("SELECT * FROM users WHERE user_id=?", (user_id,)) as cur:
                user = await cur.fetchone()
            if user:
                base = datetime.now()
                if user["paid_until"] and user["active"]:
                    try:
                        base = max(base, datetime.strptime(user["paid_until"], "%Y-%m-%d"))
                    except Exception:
                        pass
                new_until = (base + timedelta(days=days)).strftime("%Y-%m-%d")
                traffic_gb = days_to_traffic_gb(days)
                # Если уже есть активная подписка — суммируем трафик
                cur_limit = user["traffic_limit_gb"] or 0
                if user["active"] and cur_limit > 0:
                    traffic_gb = cur_limit + traffic_gb
                await db.execute(
                    "UPDATE users SET active=1, paid_until=?, traffic_limit_gb=? WHERE user_id=?",
                    (new_until, traffic_gb, user_id)
                )
                # Обновляем файл подписки
                async with db.execute("SELECT uuid, uuid2, uuid3, sub_token FROM users WHERE user_id=?", (user_id,)) as cur:
                    u = await cur.fetchone()
                if u and u["sub_token"]:
                    _generate_sub_file(user_id, u["uuid"], u["uuid2"], u["uuid3"], u["sub_token"])
        await db.commit()

    months_approx = round(days / 30, 1) if days else 0
    traffic_gb = days_to_traffic_gb(days) if days else 0
    msg = f"+{days} дней к подписке!\n📦 Трафик: {traffic_gb} ГБ\n⏱ ~{months_approx} мес."
    return {"ok": True, "message": msg, "days": days}

async def create_promo_code(code: str, days: int = 0, uses_left: int = None, expires_at: str = None):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO promo_codes (code, days, uses_left, expires_at) VALUES (?,?,?,?)",
            (code, days, uses_left, expires_at)
        )
        await db.commit()

async def get_stats() -> dict:
    """Расширенная статистика для админа."""
    async with aiosqlite.connect(DB) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c: total = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE active=1") as c: active = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE trial_used=1") as c: trials = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE created_at >= date('now', '-7 days')") as c: new7 = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE created_at >= date('now', '-1 days')") as c: new24h = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE created_at >= date('now', '-30 days')") as c: new30 = (await c.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='confirmed'") as c: total_rev = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM payments WHERE status='pending'") as c: pending = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM payments WHERE status='confirmed'") as c: total_payments = (await c.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='confirmed' AND created_at >= date('now', '-7 days')") as c: rev7 = (await c.fetchone())[0]
        async with db.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='confirmed' AND created_at >= date('now', '-30 days')") as c: rev30 = (await c.fetchone())[0]
        # Истекающие / длительность подписок
        async with db.execute("SELECT COUNT(*) FROM users WHERE active=1 AND paid_until BETWEEN date('now') AND date('now', '+3 days')") as c: expiring3 = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE active=1 AND paid_until BETWEEN date('now') AND date('now', '+7 days')") as c: expiring7 = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE active=1 AND paid_until BETWEEN date('now') AND date('now', '+30 days')") as c: sub_lt1m = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE active=1 AND paid_until BETWEEN date('now', '+30 days') AND date('now', '+60 days')") as c: sub_1to2m = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE active=1 AND paid_until BETWEEN date('now', '+60 days') AND date('now', '+90 days')") as c: sub_2to3m = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM users WHERE active=1 AND paid_until > date('now', '+90 days')") as c: sub_gt3m = (await c.fetchone())[0]
        # Трафик
        async with db.execute("SELECT COALESCE(SUM(traffic_used_gb),0) FROM users") as c: total_traffic = (await c.fetchone())[0]
        async with db.execute("SELECT username, user_id, traffic_used_gb FROM users WHERE active=1 ORDER BY traffic_used_gb DESC LIMIT 5") as c: top_traffic = await c.fetchall()
        # Рефералы
        async with db.execute("SELECT COUNT(*) FROM users WHERE referred_by IS NOT NULL") as c: total_refs = (await c.fetchone())[0]
        async with db.execute("""
            SELECT u.username, u.user_id, COUNT(*) as cnt
            FROM users r JOIN users u ON r.referred_by = u.user_id
            GROUP BY r.referred_by ORDER BY cnt DESC LIMIT 5
        """) as c: top_refs = await c.fetchall()
        # GPT
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM chat_history") as c: gpt_users = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM chat_history") as c: gpt_msgs = (await c.fetchone())[0]
        # Промокоды
        async with db.execute("SELECT COUNT(*) FROM promo_uses") as c: promo_uses = (await c.fetchone())[0]
        # Последние 5 платежей
        async with db.execute("""
            SELECT u.username, p.amount, p.months, p.created_at
            FROM payments p JOIN users u ON p.user_id=u.user_id
            WHERE p.status='confirmed' ORDER BY p.created_at DESC LIMIT 5
        """) as c: last_payments = await c.fetchall()

    return {
        "total": total, "active": active, "trials": trials,
        "new_24h": new24h, "new_7d": new7, "new_30d": new30,
        "total_revenue": total_rev, "rev_7d": rev7, "rev_30d": rev30,
        "total_payments": total_payments, "pending_payments": pending,
        "expiring_3d": expiring3, "expiring_7d": expiring7,
        "sub_lt1m": sub_lt1m, "sub_1to2m": sub_1to2m, "sub_2to3m": sub_2to3m, "sub_gt3m": sub_gt3m,
        "total_traffic": round(total_traffic, 1), "top_traffic": top_traffic,
        "total_refs": total_refs, "top_refs": top_refs,
        "gpt_users": gpt_users, "gpt_msgs": gpt_msgs,
        "promo_uses": promo_uses, "last_payments": last_payments,
        # оставляем для совместимости
        "refs_7d": 0, "refs_30d": 0, "ref_bonus_used": 0,
    }


# ─── Синхронизация трафика ─────────────────────────────────────────────────────
async def sync_user_traffic(user_id: int, traffic_gb: float):
    """Сохраняет трафик пользователя за текущий месяц."""
    month = datetime.now().strftime("%Y-%m")
    await db_exec("""
        INSERT INTO traffic_history (user_id, month, traffic_gb)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, month) DO UPDATE SET traffic_gb=excluded.traffic_gb
    """, (user_id, month, traffic_gb))
    await db_exec("UPDATE users SET traffic_month_used_gb=? WHERE user_id=?", (traffic_gb, user_id))

async def get_user_month_traffic(user_id: int) -> float:
    """Возвращает трафик пользователя за текущий месяц."""
    month = datetime.now().strftime("%Y-%m")
    row = await db_get("SELECT traffic_gb FROM traffic_history WHERE user_id=? AND month=?", (user_id, month))
    return row["traffic_gb"] if row else 0.0

async def get_user_total_traffic(user_id: int) -> float:
    """Возвращает общий трафик пользователя за всё время."""
    row = await db_get("SELECT SUM(traffic_gb) as total FROM traffic_history WHERE user_id=?", (user_id,))
    return row["total"] if row and row["total"] else 0.0

async def reset_user_month_traffic(user_id: int):
    """Сбрасывает трафик пользователя за текущий месяц (для нового месяца)."""
    import json
    month = datetime.now().strftime("%Y-%m")
    # Создаём запись с нулевым трафиком для нового месяца
    await db_exec("""
        INSERT OR IGNORE INTO traffic_history (user_id, month, traffic_gb)
        VALUES (?, ?, 0)
    """, (user_id, month))
    # Обновляем baseline — текущий накопленный трафик из кэша становится новым baseline
    try:
        with open("/usr/local/etc/xray/traffic_cache.json") as f:
            cache = json.load(f)
        total_bytes = sum(v for k, v in cache.items()
                         if k == str(user_id) or k == f"proxy_{user_id}")
        await db_exec(
            "INSERT OR REPLACE INTO traffic_baseline (user_id, month, baseline_bytes) VALUES (?,?,?)",
            (user_id, month, total_bytes)
        )
    except Exception:
        pass
    # Пересчитываем лимит трафика исходя из оставшихся месяцев подписки
    row = await db_get("SELECT paid_until FROM users WHERE user_id=?", (user_id,))
    new_limit = calc_traffic_limit(row["paid_until"]) if row and row["paid_until"] else 100
    await db_exec(
        "UPDATE users SET traffic_month_used_gb=0, traffic_blocked=0, traffic_limit_gb=? WHERE user_id=?",
        (new_limit, user_id)
    )

async def sync_all_users_traffic():
    """Синхронизирует трафик всех пользователей из кэша в БД (месячная дельта)."""
    import json
    cache_path = "/usr/local/etc/xray/traffic_cache.json"
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except:
        return

    # Группируем по user_id (суммарный накопленный трафик в байтах)
    traffic_by_user = {}
    for key, value in cache.items():
        if key.startswith("proxy_"):
            uid = key.replace("proxy_", "")
        else:
            uid = key.lstrip("u")
        traffic_by_user[uid] = traffic_by_user.get(uid, 0) + value

    month = datetime.now().strftime("%Y-%m")
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        for uid, total_bytes in traffic_by_user.items():
            try:
                user_id = int(uid)
                # Получаем baseline для текущего месяца
                async with db.execute(
                    "SELECT baseline_bytes, month FROM traffic_baseline WHERE user_id=?", (user_id,)
                ) as cur:
                    row = await cur.fetchone()

                if not row or row["month"] != month:
                    # Новый месяц — baseline = текущий накопленный
                    await db.execute(
                        "INSERT OR REPLACE INTO traffic_baseline (user_id, month, baseline_bytes) VALUES (?,?,?)",
                        (user_id, month, total_bytes)
                    )
                    month_bytes = 0
                else:
                    month_bytes = max(0, total_bytes - row["baseline_bytes"])

                gb = round(month_bytes / 1024**3, 3)
                await db.execute("""
                    INSERT INTO traffic_history (user_id, month, traffic_gb)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, month) DO UPDATE SET traffic_gb=excluded.traffic_gb
                """, (user_id, month, gb))
                await db.execute(
                    "UPDATE users SET traffic_month_used_gb=?, traffic_used_gb=? WHERE user_id=?",
                    (gb, gb, user_id)
                )
            except:
                pass
        await db.commit()


# ─── Серверы ──────────────────────────────────────────────────────────────────
async def add_server(name: str, flag: str, ip: str, ssh_user: str, ssh_pass: str, public_key: str, short_id: str):
    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT OR REPLACE INTO servers (name, flag, ip, ssh_user, ssh_pass, public_key, short_id) VALUES (?,?,?,?,?,?,?)",
            (name, flag, ip, ssh_user, ssh_pass, public_key, short_id)
        )
        await db.commit()

async def get_servers():
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM servers WHERE active=1") as cur:
            return await cur.fetchall()

async def delete_server(server_id: int):
    async with aiosqlite.connect(DB) as db:
        await db.execute("UPDATE servers SET active=0 WHERE id=?", (server_id,))
        await db.commit()

async def get_server(server_id: int):
    async with aiosqlite.connect(DB) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM servers WHERE id=?", (server_id,)) as cur:
            return await cur.fetchone()
