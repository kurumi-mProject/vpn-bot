#!/bin/bash
# ============================================================
# KomoVPN — установка xray сервера на чистый Debian/Ubuntu
# Использование: bash setup_xray.sh
# ============================================================
set -e

XRAY_CONFIG="/usr/local/etc/xray/config.json"

echo "==> [1/6] Установка зависимостей..."
DEBIAN_FRONTEND=noninteractive apt-get install -y curl unzip 2>&1 | tail -2

echo "==> [2/6] Установка xray..."
bash <(curl -Ls https://raw.githubusercontent.com/XTLS/Xray-install/main/install-release.sh) install > /tmp/xray_install.log 2>&1
echo "xray установлен: $(/usr/local/bin/xray version 2>&1 | head -1)"

echo "==> [3/6] Генерация ключей Reality..."
KEYS=$(/usr/local/bin/xray x25519 2>&1)
PRIVATE_KEY=$(echo "$KEYS" | grep -i "PrivateKey\|Private key" | awk -F': ' '{print $2}' | tr -d ' ')
PUBLIC_KEY=$(echo "$KEYS"  | grep -i "Password\|Public key"   | head -1 | awk -F': ' '{print $2}' | tr -d ' ')
SHORT_ID=$(openssl rand -hex 8)

echo "  PrivateKey: $PRIVATE_KEY"
echo "  PublicKey:  $PUBLIC_KEY"
echo "  ShortID:    $SHORT_ID"

echo "==> [4/6] Запись конфига xray..."
mkdir -p /usr/local/etc/xray

cat > "$XRAY_CONFIG" << XRAYCFG
{
  "log": {"loglevel": "warning"},
  "api": {"tag": "api", "services": ["StatsService"]},
  "stats": {},
  "policy": {
    "levels": {"0": {"statsUserUplink": true, "statsUserDownlink": true}},
    "system": {"statsInboundUplink": true, "statsInboundDownlink": true}
  },
  "inbounds": [
    {
      "port": 443,
      "protocol": "vless",
      "tag": "vless-in",
      "settings": {"clients": [], "decryption": "none"},
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "lklunallm.icu:443",
          "xver": 0,
          "serverNames": ["lklunallm.icu", "www.microsoft.com"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SHORT_ID"]
        }
      },
      "sniffing": {"enabled": true, "destOverride": ["http", "tls"]}
    },
    {
      "port": 444,
      "protocol": "vless",
      "tag": "xhttp-in",
      "settings": {"clients": [], "decryption": "none"},
      "streamSettings": {
        "network": "xhttp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "lklunallm.icu:443",
          "xver": 0,
          "serverNames": ["lklunallm.icu"],
          "privateKey": "$PRIVATE_KEY",
          "shortIds": ["$SHORT_ID"]
        },
        "xhttpSettings": {"path": "/assets/img", "mode": "stream-one"}
      },
      "sniffing": {"enabled": true, "destOverride": ["http", "tls"]}
    },
    {
      "listen": "127.0.0.1",
      "port": 10085,
      "protocol": "dokodemo-door",
      "settings": {"address": "127.0.0.1"},
      "tag": "api"
    }
  ],
  "outbounds": [
    {"protocol": "freedom", "tag": "direct"},
    {"protocol": "blackhole", "tag": "block"}
  ],
  "routing": {
    "rules": [
      {"inboundTag": ["api"], "outboundTag": "api", "type": "field"},
      {"ip": ["geoip:private"], "outboundTag": "block", "type": "field"}
    ]
  }
}
XRAYCFG

echo "==> [5/6] Автозапуск и оптимизация сети..."

# Restart=always при падении
mkdir -p /etc/systemd/system/xray.service.d
cat > /etc/systemd/system/xray.service.d/restart.conf << EOF
[Service]
Restart=always
RestartSec=5
EOF

systemctl daemon-reload
systemctl enable xray
systemctl restart xray
sleep 2

# TCP/сетевые оптимизации
cat > /etc/sysctl.d/99-vpn.conf << EOF
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864
net.ipv4.tcp_rmem = 4096 87380 67108864
net.ipv4.tcp_wmem = 4096 65536 67108864
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_notsent_lowat = 16384
net.core.somaxconn = 32768
net.ipv4.tcp_max_syn_backlog = 32768
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_keepalive_time = 60
net.ipv4.tcp_keepalive_intvl = 10
net.ipv4.tcp_keepalive_probes = 3
fs.file-max = 1000000
EOF
sysctl -p /etc/sysctl.d/99-vpn.conf > /dev/null

echo "* soft nofile 1000000
* hard nofile 1000000" > /etc/security/limits.d/99-vpn.conf

echo "==> [6/6] Установка репортера трафика..."

cat > /usr/local/bin/traffic_reporter.sh << 'REPORTER'
#!/bin/bash
python3 - << 'PYEOF'
import json, re, subprocess, urllib.request, os, sys

r = subprocess.run(["/usr/local/bin/xray","api","statsquery","--server=127.0.0.1:10085","--pattern="],
    capture_output=True, text=True, timeout=5)
try:
    data = json.loads(r.stdout)
except:
    sys.exit(0)

traffic = {}
for e in data.get("stat", []):
    name = e.get("name","")
    val  = int(e.get("value",0))
    if not val: continue
    m = re.match(r"user>>>u?(\d+)(?:_c\d+)?>>>traffic", name)
    if m:
        uid = m.group(1)
        traffic[uid] = traffic.get(uid,0) + val

if not traffic: sys.exit(0)

payload = json.dumps({
    "secret": "komovpn_traffic_secret",
    "server_ip": os.popen("curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}'").read().strip(),
    "traffic": traffic
}).encode()

req = urllib.request.Request(
    "https://lklunallm.icu/api/internal/report-traffic",
    data=payload, headers={"Content-Type":"application/json"}, method="POST"
)
try:
    urllib.request.urlopen(req, timeout=10)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
PYEOF
REPORTER

chmod +x /usr/local/bin/traffic_reporter.sh
(crontab -l 2>/dev/null | grep -v traffic_reporter; echo "*/5 * * * * /usr/local/bin/traffic_reporter.sh") | crontab -

# Итог
STATUS=$(systemctl is-active xray)
SERVER_IP=$(curl -s ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "============================================"
echo "  IP:         $SERVER_IP"
echo "  PublicKey:  $PUBLIC_KEY"
echo "  ShortID:    $SHORT_ID"
echo "  xray:       $STATUS"
echo "============================================"
