"""AgentPay — конфигурация."""

# Сервер
HOST = "0.0.0.0"
PORT = 8004

# База данных
DATABASE_URL = "sqlite:///agentpay.db"

# Base сеть
BASE_RPC = "https://mainnet.base.org"
BASE_CHAIN_ID = 8453

# Кошелёк AgentPay (приём USDC)
AGENTPAY_WALLET = "0x69D637b5a8317E78c5e561D7E94b234dDa551f47"

# USDC контракт на Base
USDC_CONTRACT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Комиссия
FEE_PERCENT = 0.5  # 0.5%

# Лимиты
MIN_TOPUP = 1       # 1 USDC
MAX_TOPUP = 10_000
MIN_PAY = 0.01
MAX_PAY = 1_000
MAX_PAY_DAY = 10_000
MIN_WITHDRAW = 10
MAX_WITHDRAW = 5_000
MAX_WITHDRAW_DAY = 10_000

# Nonce для snapshot'ов
NONCE_FILE = "nonce.txt"
