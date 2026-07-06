#!/bin/bash
# Запускается на удалённом сервере каждые 5 минут через cron
# Репортит трафик на главный сервер

MAIN_API="https://lklunallm.icu/api/internal/report-traffic"
SECRET="komovpn_traffic_secret"
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

# Получаем статистику xray
STATS=$(/usr/local/bin/xray api statsquery --server=127.0.0.1:10085 --pattern= 2>/dev/null)
if [ -z "$STATS" ]; then exit 0; fi

# Парсим и отправляем
python3 - << 'PYEOF'
import json, re, subprocess, os, sys

stats_raw = subprocess.run(
    ["/usr/local/bin/xray", "api", "statsquery", "--server=127.0.0.1:10085", "--pattern="],
    capture_output=True, text=True, timeout=5
).stdout

try:
    data = json.loads(stats_raw)
except Exception:
    sys.exit(0)

traffic = {}
for entry in data.get("stat", []):
    name = entry.get("name", "")
    value = int(entry.get("value", 0))
    if not value:
        continue
    m = re.match(r"user>>>u?(\d+)(?:_c\d+)?>>>traffic", name)
    if m:
        uid = m.group(1)
        traffic[uid] = traffic.get(uid, 0) + value

if not traffic:
    sys.exit(0)

import urllib.request
payload = json.dumps({
    "secret": "komovpn_traffic_secret",
    "server_ip": os.popen("curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'").read().strip(),
    "traffic": traffic
}).encode()

req = urllib.request.Request(
    "https://lklunallm.icu/api/internal/report-traffic",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST"
)
try:
    urllib.request.urlopen(req, timeout=10)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
PYEOF
