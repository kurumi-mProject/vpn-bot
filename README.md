# 🛡 KomoVPN Bot — Telegram Bot for VLESS VPN Sales

Telegram-бот для продажи VPN на базе Xray (VLESS + XTLS-Reality). Автоматическое управление клиентами, контроль трафика, баланс, GPT-поддержка.

## Возможности

- **Автоматическая выдача VPN** — генерация VLESS-конфига и QR-кода после оплаты
- **VLESS + XTLS-Reality** — современный протокол, обходит блокировки РКН
- **Контроль трафика** — лимиты по тарифам, автоблокировка при превышении
- **Тарифы** — 1 / 3 / 6 / 12 месяцев с разными лимитами трафика
- **Баланс и пополнение** — внутренний баланс пользователя
- **GPT-поддержка** — встроенный AI-помощник (Grok) для ответов на вопросы
- **Реферальная система** — привязка к MTProto прокси
- **Планировщик задач** — авто-уведомления об истечении, сброс трафика
- **Xray интеграция** — добавление/удаление клиентов через Xray API

## Стек

- Python 3.11+
- [aiogram 3](https://docs.aiogram.dev/)
- SQLite + aiosqlite
- Xray-core (VLESS + XTLS-Reality)
- qrcode + Pillow — генерация QR-кодов
- aitunnel.ru API (Grok) — AI-поддержка

## Установка

```bash
git clone https://github.com/kurumi-mProject/vpn-bot.git
cd vpn-bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env

# Установка и настройка Xray
bash install_xray.sh
bash setup_xray.sh

python bot.py
```

## Переменные окружения (.env)

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен от @BotFather |
| `ADMIN_ID` | Telegram ID администратора |
| `SERVER_IP` | IP адрес сервера |
| `XRAY_CONFIG` | Путь к конфигу Xray |
| `PUBLIC_KEY` | XTLS-Reality публичный ключ |
| `SHORT_ID` | XTLS-Reality short ID |
| `PRICE` | Цена за месяц (по умолчанию 250₽) |
| `TRAFFIC_LIMIT_GB` | Лимит трафика по умолчанию (ГБ) |
| `AITUNNEL_KEY` | API ключ для GPT-поддержки |

## Лимиты трафика по тарифам

| Тариф | Трафик |
|---|---|
| 1 месяц | 100 ГБ |
| 3 месяца | 150 ГБ |
| 6 месяцев | 200 ГБ |
| 12 месяцев | 300 ГБ |

## Структура проекта

```
vpn-bot/
├── bot.py              # Точка входа, планировщик задач
├── config.py           # Конфигурация из .env
├── database.py         # SQLite: пользователи, подписки, трафик
├── xray.py             # Xray API: добавление/удаление клиентов
├── balance.py          # Баланс пользователей
├── tasks.py            # Фоновые задачи
├── handlers/
│   ├── admin.py        # Команды администратора
│   └── user.py         # Команды пользователя
├── install_xray.sh     # Установка Xray
├── setup_xray.sh       # Настройка конфига Xray
└── traffic_reporter.sh # Отчёт по трафику
```
