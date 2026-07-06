#!/bin/bash
set -e

# Устанавливаем xray
bash <(curl -Ls https://raw.githubusercontent.com/XTLS/Xray-install/main/install-release.sh) install

# Копируем конфиг (уже загружен рядом)
cp /tmp/xray_config.json /usr/local/etc/xray/config.json

# Автозапуск при падении
mkdir -p /etc/systemd/system/xray.service.d
cat > /etc/systemd/system/xray.service.d/restart.conf << 'EOF'
[Service]
Restart=always
RestartSec=5
EOF

systemctl daemon-reload
systemctl enable xray
systemctl restart xray
sleep 2
systemctl is-active xray
