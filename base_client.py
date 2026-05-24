"""AgentPay — интеграция с Base."""

import os
from web3 import Web3
from eth_account.messages import encode_defunct
from config import BASE_RPC, USDC_CONTRACT, AGENTPAY_WALLET, AGENTPAY_PRIVATE_KEY

w3 = Web3(Web3.HTTPProvider(BASE_RPC))

# USDC contract ABI — минимум для проверки баланса, Transfer events, allowance
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
        "inputs": [
            {"name": "recipient", "type": "address"},
            {"name": "amount", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "", "type": "bool"}],
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


# ─── Верификация подписи (EIP-191) ────────────────────────────


def build_message(action: str, sender: str, recipient: str, amount: float, nonce: int) -> str:
    """Собирает сообщение для подписи.

    Агент подписывает своим приватным ключом Ethereum.
    Формат: agentpay_v1:{action}:{sender}:{recipient}:{amount}:{nonce}
    """
    return f"agentpay_v1:{action}:{sender}:{recipient}:{amount}:{nonce}"


def recover_signer(message: str, signature: str) -> str:
    """Восстанавливает адрес отправителя из подписи EIP-191.

    Возвращает: 0x-адрес, который подписал сообщение.
    """
    msg_encoded = encode_defunct(text=message)
    recovered = w3.eth.account.recover_message(msg_encoded, signature=signature)
    return recovered


def verify_signature(action: str, sender: str, recipient: str, amount: float, nonce: int, signature: str) -> bool:
    """Проверяет подпись. Возвращает True если подпись верна."""
    message = build_message(action, sender, recipient, amount, nonce)
    try:
        recovered = recover_signer(message, signature)
        return recovered.lower() == sender.lower()
    except Exception:
        return False


# ─── Transfer events (для верификации topup) ───────────────────


def get_usdc_transfers(since_block: int | None = None) -> list[dict]:
    """Получает Transfer events USDC на наш кошелёк.

    Возвращает список: [{from, to, value, tx_hash, block_number}]
    """
    to_checksum = Web3.to_checksum_address(AGENTPAY_WALLET)

    if since_block is None:
        since_block = w3.eth.block_number - 5000  # ~24 часов

    to_block = w3.eth.block_number

    event_filter = usdc_contract.events.Transfer.create_filter(
        argument_filters={"to": to_checksum},
        from_block=since_block,
        to_block=to_block,
    )

    events = []
    for entry in event_filter.get_all_entries():
        events.append({
            "from": entry["args"]["from"],
            "to": entry["args"]["to"],
            "value": entry["args"]["value"] / 10**6,
            "tx_hash": entry["transactionHash"].hex(),
            "block_number": entry["blockNumber"],
        })

    return events


def verify_topup_transfer(tx_hash: str, expected_from: str, expected_value: float) -> dict | None:
    """Проверяет конкретную USDC Transfer транзакцию.

    Ищет событие Transfer(from, AGENTPAY_WALLET, value) с данным tx_hash.
    Проверяет что отправитель совпадает с expected_from и сумма достаточна.
    Возвращает детали транзакции или None если не найдена/не совпадает.
    """
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception:
        return None

    if not receipt:
        return None

    logs = usdc_contract.events.Transfer().process_receipt(receipt)
    for log in logs:
        args = log["args"]
        if (args["to"].lower() == AGENTPAY_WALLET.lower()
                and args["from"].lower() == expected_from.lower()
                and args["value"] / 10**6 >= expected_value):
            return {
                "from": args["from"],
                "to": args["to"],
                "value": args["value"] / 10**6,
                "tx_hash": tx_hash,
                "block_number": receipt["blockNumber"],
            }

    return None


# ─── Withdraw ─────────────────────────────────────────────────


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


def send_usdc(recipient: str, amount_usdc: int) -> str:
    """Подписывает и отправляет USDC на адрес получателя.
    Возвращает tx hash."""
    if not AGENTPAY_PRIVATE_KEY:
        raise ValueError("AGENTPAY_PRIVATE_KEY не задан. Укажи X402_PRIVATE_KEY в .env")

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
        "chainId": 8453,
    })

    signed = w3.eth.account.sign_transaction(tx, AGENTPAY_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()
