# AgentPay Deploy

## Prerequisites

- Сервер с Python 3.11+
- Доступ к Base (mainnet или testnet)
- Приватный ключ с USDC на Base

## Установка

```bash
# Клонировать репозиторий
git clone https://github.com/M1mino/agentpay.git /opt/agentpay
cd /opt/agentpay

# Создать venv и установить зависимости
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Создать .env из примера
cp deploy/.env.example .env
# Отредактировать .env — вставить X402_PRIVATE_KEY
nano .env

# Установить systemd сервис
cp deploy/agentpay.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable agentpay
systemctl start agentpay

# Проверить
systemctl status agentpay
curl http://localhost:8004/health
curl http://localhost:8004/audit
```

## Структура

```
/opt/agentpay/
├── server.py         # FastAPI сервер (uvicorn)
├── config.py         # Конфигурация
├── database.py       # SQLite (WAL)
├── base_client.py    # web3.py / Base интеграция
├── models.py         # Pydantic схемы
├── requirements.txt  # Зависимости
├── .env              # secrets (не в репозитории!)
└── deploy/
    ├── agentpay.service  # systemd unit
    └── .env.example      # шаблон .env
```

## Порты

- `8004` — AgentPay FastAPI сервер
