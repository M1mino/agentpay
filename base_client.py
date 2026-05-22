"""AgentPay — интеграция с Base (read-only для старта)."""

from web3 import Web3
from config import BASE_RPC, USDC_CONTRACT, AGENTPAY_WALLET

w3 = Web3(Web3.HTTPProvider(BASE_RPC))

# USDC contract ABI — минимум для проверки баланса и транзакций
USDC_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "value", "type": "uint256"},
        ],
        "name": "Transfer",
        "type": "event",
    },
]

usdc_contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_CONTRACT), abi=USDC_ABI)


def is_connected() -> bool:
    return w3.is_connected()


def get_usdc_balance(address: str) -> float:
    """Баланс USDC на адресе."""
    checksum = Web3.to_checksum_address(address)
    balance = usdc_contract.functions.balanceOf(checksum).call()
    return balance / 10**6  # USDC имеет 6 decimals


def check_incoming_usdc(agent_address: str, expected_amount: float) -> bool:
    """Проверяет, пришёл ли USDC от агента на наш кошелёк.
    Read-only — не требует приватного ключа."""
    our_balance = get_usdc_balance(AGENTPAY_WALLET)
    # Для старта: просто проверяем что баланс вырос
    # В реальности: парсим Transfer events
    return our_balance >= expected_amount


def build_withdraw_tx(recipient: str, amount_usdc: int) -> dict:
    """Собирает транзакцию для отправки USDC.
    Не подписывает — только строит."""
    checksum = Web3.to_checksum_address(recipient)
    tx = usdc_contract.functions.transfer(
        checksum, amount_usdc
    ).build_transaction({
        "from": Web3.to_checksum_address(AGENTPAY_WALLET),
        "nonce": w3.eth.get_transaction_count(
            Web3.to_checksum_address(AGENTPAY_WALLET)
        ),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
    })
    return tx
