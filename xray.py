import json, uuid, subprocess, hashlib
from config import XRAY_CONFIG, SERVER_IP, PUBLIC_KEY, SHORT_ID

def load_config():
    with open(XRAY_CONFIG) as f:
        return json.load(f)

def save_config(cfg):
    # Сохраняем трафик всех пользователей в файл перед перезапуском xray,
    # чтобы не потерять счётчики (xray сбрасывает stats при рестарте)
    _flush_traffic_to_db()
    with open(XRAY_CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)
    subprocess.run(["systemctl", "restart", "xray"], capture_output=True)

async def save_config_async(cfg):
    """Асинхронная версия — не блокирует event loop."""
    import asyncio
    await asyncio.to_thread(save_config, cfg)

def _parse_xray_stats(stdout: str) -> tuple[dict, dict]:
    """
    Парсит вывод xray statsquery.
    Возвращает (vpn_traffic, proxy_traffic) — dict[user_id_str -> bytes].
    
    Форматы имён в xray:
      VPN:   user>>>{uid}>>>traffic, user>>>u{uid}>>>traffic, user>>>{uid}_c2>>>traffic
      Proxy: inbound>>>socks-{uid}>>>traffic, inbound>>>http-{uid}>>>traffic
    """
    import re, json as _json
    
    # Парсим весь JSON сразу — надёжнее построчного разбора
    try:
        data = _json.loads(stdout)
        stats = data.get("stat", [])
    except Exception:
        return {}, {}
    
    vpn: dict[str, int] = {}
    proxy: dict[str, int] = {}
    
    for entry in stats:
        name = entry.get("name", "")
        value = int(entry.get("value", 0))
        if not value:
            continue
        
        # VPN: user>>>{email}>>>traffic>>>{up|down}link
        # email может быть: "123456", "u123456", "123456_c2", "123456_c3"
        m = re.match(r"user>>>u?(\d+)(?:_c\d+)?>>>traffic", name)
        if m:
            uid = m.group(1)
            vpn[uid] = vpn.get(uid, 0) + value
            continue
        
        # Proxy: inbound>>>{socks|http}-{uid}>>>traffic
        m = re.match(r"inbound>>>(?:socks|http)-(\d+)>>>traffic", name)
        if m:
            uid = m.group(1)
            proxy[uid] = proxy.get(uid, 0) + value
    
    return vpn, proxy

def _flush_traffic_to_db():
    """Читает текущий трафик всех пользователей и сохраняет в файл-кэш."""
    try:
        import json as _json
        result = subprocess.run(
            ["xray", "api", "statsquery", "--server=127.0.0.1:10085", "--pattern="],
            capture_output=True, text=True, timeout=5
        )
        vpn_traffic, proxy_traffic = _parse_xray_stats(result.stdout)
        if not vpn_traffic and not proxy_traffic:
            return
        cache_path = XRAY_CONFIG.replace("config.json", "traffic_cache.json")
        try:
            with open(cache_path) as f:
                existing = _json.load(f)
        except Exception:
            existing = {}
        for uid, val in vpn_traffic.items():
            existing[uid] = existing.get(uid, 0) + val
        for uid, val in proxy_traffic.items():
            existing[f"proxy_{uid}"] = existing.get(f"proxy_{uid}", 0) + val
        with open(cache_path, "w") as f:
            _json.dump(existing, f)
    except Exception:
        pass

def _get_inbound(cfg, tag: str) -> dict | None:
    return next((i for i in cfg["inbounds"] if i.get("tag") == tag), None)

# ─── VPN (VLESS) ──────────────────────────────────────────────────────────────
def add_client(user_uuid: str, email: str):
    cfg = load_config()
    clients = cfg["inbounds"][0]["settings"]["clients"]
    if not any(c["id"] == user_uuid for c in clients):
        clients.append({"id": user_uuid, "email": email, "flow": "xtls-rprx-vision"})
        save_config(cfg)

async def add_client_async(user_uuid: str, email: str):
    import asyncio
    await asyncio.to_thread(add_client, user_uuid, email)

def add_client_multi(uuids: list[str], email: str):
    """Добавляет несколько uuid для одного пользователя (мульти-конфиг)."""
    cfg = load_config()
    clients = cfg["inbounds"][0]["settings"]["clients"]
    changed = False
    for i, uid in enumerate(uuids):
        tag = email if i == 0 else f"{email}_c{i+1}"
        if not any(c["id"] == uid for c in clients):
            clients.append({"id": uid, "email": tag, "flow": "xtls-rprx-vision"})
            changed = True
    if changed:
        save_config(cfg)

async def add_client_multi_async(uuids: list[str], email: str):
    import asyncio
    await asyncio.to_thread(add_client_multi, uuids, email)

def remove_client(user_uuid: str):
    cfg = load_config()
    cfg["inbounds"][0]["settings"]["clients"] = [
        c for c in cfg["inbounds"][0]["settings"]["clients"] if c["id"] != user_uuid
    ]
    save_config(cfg)

async def remove_client_async(user_uuid: str):
    import asyncio
    await asyncio.to_thread(remove_client, user_uuid)

def remove_client_multi(uuids: list[str]):
    """Удаляет все uuid пользователя."""
    cfg = load_config()
    uid_set = set(uuids)
    cfg["inbounds"][0]["settings"]["clients"] = [
        c for c in cfg["inbounds"][0]["settings"]["clients"] if c["id"] not in uid_set
    ]
    save_config(cfg)

async def remove_client_multi_async(uuids: list[str]):
    import asyncio
    await asyncio.to_thread(remove_client_multi, uuids)

# ─── Прокси (SOCKS5 + HTTP — отдельный inbound на пользователя) ──────────────
SOCKS_BASE_PORT = 11000  # 11000 + user_id % 1000 — уникальный порт
HTTP_BASE_PORT  = 12000

def _proxy_login(user_id: int) -> str:
    return f"u{user_id}"

def _proxy_pass(user_id: int) -> str:
    return hashlib.md5(f"vpn_proxy_{user_id}".encode()).hexdigest()[:12]

def _proxy_socks_tag(user_id: int) -> str:
    return f"socks-{user_id}"

def _proxy_http_tag(user_id: int) -> str:
    return f"http-{user_id}"

def add_proxy_client(user_id: int):
    cfg = load_config()
    login = _proxy_login(user_id)
    password = _proxy_pass(user_id)
    socks_tag = _proxy_socks_tag(user_id)
    http_tag  = _proxy_http_tag(user_id)
    socks_port = SOCKS_BASE_PORT + (user_id % 4000)
    http_port  = HTTP_BASE_PORT  + (user_id % 4000)
    changed = False

    if not any(i.get("tag") == socks_tag for i in cfg["inbounds"]):
        cfg["inbounds"].append({
            "port": socks_port,
            "protocol": "socks",
            "tag": socks_tag,
            "settings": {
                "auth": "password",
                "accounts": [{"user": login, "pass": password, "email": str(user_id)}],
                "udp": True
            }
        })
        changed = True

    if not any(i.get("tag") == http_tag for i in cfg["inbounds"]):
        cfg["inbounds"].append({
            "port": http_port,
            "protocol": "http",
            "tag": http_tag,
            "settings": {
                "accounts": [{"user": login, "pass": password, "email": str(user_id)}]
            }
        })
        changed = True

    if changed:
        save_config(cfg)

async def add_proxy_client_async(user_id: int):
    import asyncio
    await asyncio.to_thread(add_proxy_client, user_id)

def remove_proxy_client(user_id: int):
    cfg = load_config()
    tags = {_proxy_socks_tag(user_id), _proxy_http_tag(user_id)}
    before = len(cfg["inbounds"])
    cfg["inbounds"] = [i for i in cfg["inbounds"] if i.get("tag") not in tags]
    if len(cfg["inbounds"]) != before:
        save_config(cfg)

async def remove_proxy_client_async(user_id: int):
    import asyncio
    await asyncio.to_thread(remove_proxy_client, user_id)

def get_proxy_credentials(user_id: int) -> dict:
    return {
        "host": SERVER_IP,
        "socks5_port": SOCKS_BASE_PORT + (user_id % 4000),
        "http_port":   HTTP_BASE_PORT  + (user_id % 4000),
        "login": _proxy_login(user_id),
        "password": _proxy_pass(user_id),
    }

# ─── Трафик (VPN + прокси по user_id/email) ──────────────────────────────────
def get_user_traffic_gb(email: str) -> float:
    """Суммирует кэш + live трафик: VPN (user>>>email) + прокси (inbound>>>socks/http-uid)."""
    return get_user_traffic_detail(email)["total"]

def get_user_traffic_detail(email: str) -> dict:
    """
    Возвращает {'vpn': float, 'proxy': float, 'total': float} в ГБ.
    email = str(user_id).
    """
    import json as _json
    cache_path = XRAY_CONFIG.replace("config.json", "traffic_cache.json")
    
    cached_vpn, cached_proxy = 0, 0
    try:
        with open(cache_path) as f:
            cache = _json.load(f)
        # Поддержка обоих форматов ключей на случай старых записей
        cached_vpn   = cache.get(email, 0) + cache.get(f"u{email}", 0)
        cached_proxy = cache.get(f"proxy_{email}", 0)
    except Exception:
        pass

    result = subprocess.run(
        ["xray", "api", "statsquery", "--server=127.0.0.1:10085", "--pattern="],
        capture_output=True, text=True, timeout=5
    )
    live_vpn, live_proxy = _parse_xray_stats(result.stdout)

    vpn_bytes   = cached_vpn   + live_vpn.get(email, 0)
    proxy_bytes = cached_proxy + live_proxy.get(email, 0)
    total       = vpn_bytes + proxy_bytes
    return {
        "vpn":   round(vpn_bytes   / 1024**3, 3),
        "proxy": round(proxy_bytes / 1024**3, 3),
        "total": round(total       / 1024**3, 3),
    }

def generate_vless_link(user_uuid: str) -> str:
    return (
        f"vless://{user_uuid}@{SERVER_IP}:443"
        f"?type=tcp&security=reality&pbk={PUBLIC_KEY}"
        f"&fp=chrome&sni=www.microsoft.com&sid={SHORT_ID}&flow=xtls-rprx-vision"
        f"#VPN"
    )

# Конфиги с разными fingerprint — если один блокируется, другой работает
_CONFIGS_META = [
    {"name": "🇫🇮 Finland • Chrome",  "fp": "chrome",  "sni": "www.microsoft.com",      "tag": "🇫🇮 [FI] Finland - Chrome"},
    {"name": "🇫🇮 Finland • Firefox", "fp": "firefox", "sni": "www.cloudflare.com",      "tag": "🇫🇮 [FI] Finland - Firefox"},
    {"name": "🇫🇮 Finland • Safari",  "fp": "safari",  "sni": "www.apple.com",           "tag": "🇫🇮 [FI] Finland - Safari"},
]

DOMAIN = "lklunallm.icu"

_EXTRA_SNIS = [
    ("update.microsoft.com",  "MS-Update"),
    ("download.microsoft.com","MS-Download"),
    ("www.google.com",        "Google"),
    ("www.amd.com",           "AMD"),
    ("www.nvidia.com",        "NVIDIA"),
]


def generate_vless_configs(uuids: list[str]) -> list[dict]:
    result = []
    uuid0 = uuids[0]

    # Finland Chrome (основной)
    result.append({"link": (
        f"vless://{uuid0}@{SERVER_IP}:443"
        f"?type=tcp&security=reality&pbk={PUBLIC_KEY}"
        f"&fp=chrome&sni=www.microsoft.com&sid={SHORT_ID}&flow=xtls-rprx-vision"
        f"#🇫🇮 [FI] Finland - Chrome"
    ), "name": "🇫🇮 Finland • Chrome"})

    # Finland XHTTP + Reality self-steal
    for uid, fp, tag in [
        (uuids[0], "chrome",  "🇫🇮 [FI] XHTTP-Chrome"),
        (uuids[1], "firefox", "🇫🇮 [FI] XHTTP-Firefox"),
    ]:
        result.append({"link": (
            f"vless://{uid}@{SERVER_IP}:444"
            f"?type=xhttp&security=reality&pbk={PUBLIC_KEY}"
            f"&fp={fp}&sni=lklunallm.icu&sid={SHORT_ID}"
            f"&path=%2Fassets%2Fimg&mode=stream-one&encryption=none"
            f"#{tag}"
        ), "name": tag})

    # Hysteria 2 — Finland (игровой UDP)
    result.append({"link": (
        f"hy2://Hy2-lkluna-2026@193.17.182.23:443"
        f"?insecure=0&sni=lklunallm.icu&obfs=salamander&obfs-password=Sal-lkluna-2026"
        f"#🇫🇮 [FI] UDP Game — Brawl Stars · ML · PUBG"
    ), "name": "🇫🇮 Finland • UDP Game"})

    # Hysteria 2 — Sweden (игровой UDP)
    result.append({"link": (
        f"hy2://Hy2-lkluna-2026@hy2.lklunallm.icu:443"
        f"?insecure=0&sni=hy2.lklunallm.icu&obfs=salamander&obfs-password=Sal-lkluna-2026"
        f"#🇸🇪 [SE] UDP Game — Brawl Stars · ML · PUBG"
    ), "name": "🇸🇪 Sweden • UDP Game"})

    return result

def generate_ws_link(user_uuid: str) -> str:
    return f"vless://{user_uuid}@{DOMAIN}:2053?type=ws&security=tls&path=%2Fvless-ws&host={DOMAIN}&sni={DOMAIN}&allowInsecure=1#KomoVPN-CDN-WS"

def generate_grpc_link(user_uuid: str) -> str:
    sni = "update.microsoft.com"
    return (
        f"vless://{user_uuid}@{SERVER_IP}:4444"
        f"?type=grpc&security=reality&pbk={PUBLIC_KEY}&fp=chrome"
        f"&sni={sni}&sid={SHORT_ID}&serviceName={sni}&authority={sni}"
        f"#KomoVPN-gRPC-MS-Update"
    )

def generate_split_link(user_uuid: str) -> str:
    return generate_grpc_link(user_uuid)

def new_uuid() -> str:
    return str(uuid.uuid4())

# ─── Удалённые серверы ────────────────────────────────────────────────────────

XRAY_INSTALL_SCRIPT = """#!/bin/bash
set -e
bash <(curl -Ls https://raw.githubusercontent.com/XTLS/Xray-install/main/install-release.sh) install
mkdir -p /usr/local/etc/xray
cat > /usr/local/etc/xray/config.json << 'XRAYCFG'
{CONFIG_JSON}
XRAYCFG
systemctl enable xray
systemctl restart xray
"""

def _remote_run(host: str, user: str, password: str, cmd: str, timeout: int = 60) -> tuple[int, str, str]:
    result = subprocess.run(
        ['sshpass', '-p', password, 'ssh', '-o', 'StrictHostKeyChecking=no',
         '-o', 'ConnectTimeout=10', f'{user}@{host}', cmd],
        capture_output=True, text=True, timeout=timeout
    )
    return result.returncode, result.stdout, result.stderr

def install_xray_server(ip: str, ssh_user: str, ssh_pass: str, clients: list[dict]) -> dict:
    """Устанавливает xray на чистый VPS через setup_xray.sh."""
    import json as _json, tempfile, os

    base = os.path.dirname(__file__)

    # Копируем скрипт на сервер
    subprocess.run(
        ["sshpass", "-p", ssh_pass, "scp", "-o", "StrictHostKeyChecking=no",
         os.path.join(base, "setup_xray.sh"), f"{ssh_user}@{ip}:/tmp/setup_xray.sh"],
        capture_output=True, timeout=15
    )

    # Запускаем — скрипт сам генерирует ключи, пишет конфиг, настраивает автозапуск
    rc, out, err = _remote_run(ip, ssh_user, ssh_pass,
        "bash /tmp/setup_xray.sh 2>&1", timeout=180)

    if rc != 0:
        raise RuntimeError(f"Ошибка установки: {out[-800:]}")

    # Читаем ключи из вывода скрипта
    public_key = short_id = ""
    for line in out.splitlines():
        if "PublicKey:" in line:
            public_key = line.split("PublicKey:")[1].strip()
        elif "ShortID:" in line:
            short_id = line.split("ShortID:")[1].strip()

    if not public_key:
        raise RuntimeError(f"Не удалось получить ключи из вывода:\n{out[-500:]}")

    # Заливаем клиентов через sync
    if clients:
        sync_clients_to_server(ip, ssh_user, ssh_pass, clients)

    return {"public_key": public_key, "short_id": short_id}

def sync_clients_to_server(ip: str, ssh_user: str, ssh_pass: str, clients: list[dict]):
    """Синхронизирует список клиентов на удалённый сервер."""
    import json as _json, tempfile, os
    rc, out, _ = _remote_run(ip, ssh_user, ssh_pass, "cat /usr/local/etc/xray/config.json", timeout=10)
    if rc != 0:
        return
    try:
        cfg = _json.loads(out)
        cfg["inbounds"][0]["settings"]["clients"] = clients
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            _json.dump(cfg, f, indent=2)
            tmp = f.name
        subprocess.run(
            ["sshpass", "-p", ssh_pass, "scp", "-o", "StrictHostKeyChecking=no",
             tmp, f"{ssh_user}@{ip}:/usr/local/etc/xray/config.json"],
            capture_output=True, timeout=15
        )
        os.unlink(tmp)
        _remote_run(ip, ssh_user, ssh_pass, "systemctl restart xray", timeout=10)
    except Exception:
        pass

def get_remote_traffic(ip: str, ssh_user: str, ssh_pass: str, user_id: str) -> float:
    """Получает трафик пользователя с удалённого сервера (ГБ)."""
    import json as _json
    rc, out, _ = _remote_run(ip, ssh_user, ssh_pass,
        "/usr/local/bin/xray api statsquery --server=127.0.0.1:10085 --pattern=", timeout=10)
    if rc != 0:
        return 0.0
    try:
        data = _json.loads(out)
        total = sum(
            s.get("value", 0) for s in data.get("stat", [])
            if f">>>{user_id}" in s.get("name", "") or f">>>{user_id}_c" in s.get("name", "")
        )
        return round(total / 1024**3, 3)
    except Exception:
        return 0.0

def block_client_on_server(ip: str, ssh_user: str, ssh_pass: str, uuids: list[str]):
    """Удаляет клиентов с удалённого сервера (блокировка по трафику)."""
    import json as _json, tempfile, os
    rc, out, _ = _remote_run(ip, ssh_user, ssh_pass, "cat /usr/local/etc/xray/config.json", timeout=10)
    if rc != 0:
        return
    try:
        cfg = _json.loads(out)
        uid_set = set(uuids)
        cfg["inbounds"][0]["settings"]["clients"] = [
            c for c in cfg["inbounds"][0]["settings"]["clients"] if c["id"] not in uid_set
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            _json.dump(cfg, f, indent=2)
            tmp = f.name
        subprocess.run(
            ["sshpass", "-p", ssh_pass, "scp", "-o", "StrictHostKeyChecking=no",
             tmp, f"{ssh_user}@{ip}:/usr/local/etc/xray/config.json"],
            capture_output=True, timeout=15
        )
        os.unlink(tmp)
        _remote_run(ip, ssh_user, ssh_pass, "systemctl restart xray", timeout=10)
    except Exception:
        pass
