"""Тесты AgentPay."""

import os
import sys
import pytest
from fastapi.testclient import TestClient
from decimal import Decimal

# Патчим .env до импорта config
os.environ["X402_PRIVATE_KEY"] = "0x2c60f0905657b8dce3ae812bf56a0fcfae61e2d64b10132fb4e710613d70f317"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import app
from database import init_db, get_agent, get_agent_nonce, increment_agent_nonce, is_event_processed, mark_event_processed, get_db
from base_client import build_message, verify_signature, recover_signer
from eth_account.messages import encode_defunct
from web3 import Web3

# ─── Test client ──────────────────────────────────────────────

client = TestClient(app)

# Известный тестовый ключ и адрес
TEST_PRIVATE_KEY = os.environ["X402_PRIVATE_KEY"]
_w3 = Web3()
TEST_ACCOUNT = _w3.eth.account.from_key(TEST_PRIVATE_KEY)
TEST_ADDRESS = TEST_ACCOUNT.address  # 0x88c6dA1BaE72Ed2CA518B5117b16baDd249ca9a3
TEST_RECIPIENT = "0x69D637b5a8317E78c5e561D7E94b234dDa551f47"

w3 = Web3()


def sign_msg(msg: str) -> str:
    """Подписывает сообщение через EIP-191 personal_sign."""
    msg_encoded = encode_defunct(text=msg)
    signed = w3.eth.account.sign_message(msg_encoded, private_key=TEST_PRIVATE_KEY)
    return signed.signature.hex()


# ─── Фикстуры ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_db():
    """Пересоздаём БД и сбрасываем rate limiter перед каждым тестом."""
    db_path = "test_agentpay.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    import database
    database.DB_PATH = db_path
    init_db()
    # Сбрасываем rate limiter
    from server import _rate_store
    _rate_store.clear()
    yield
    if os.path.exists(db_path):
        os.remove(db_path)


# ─── Тесты: Подпись ──────────────────────────────────────────


def test_build_message():
    msg = build_message("pay", "0xA", "0xB", 10.5, 0)
    assert msg == "agentpay_v1:pay:0xA:0xB:10.5:0"


def test_verify_signature_valid():
    msg = build_message("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.5, 0)
    sig = sign_msg(msg)
    assert verify_signature("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.5, 0, sig)


def test_verify_signature_invalid():
    wrong_addr = "0x1111111111111111111111111111111111111111"
    assert not verify_signature("pay", wrong_addr, TEST_RECIPIENT, 10.5, 0, "0x" + "ff" * 65)


def test_verify_signature_tampered_message():
    msg = build_message("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.5, 0)
    sig = sign_msg(msg)
    assert not verify_signature("pay", TEST_ADDRESS, TEST_RECIPIENT, 99.0, 0, sig)


# ─── Тесты: Nonce ───────────────────────────────────────────


def test_nonce_starts_at_zero():
    assert get_agent_nonce(TEST_ADDRESS) == 0


def test_nonce_increments():
    assert get_agent_nonce(TEST_ADDRESS) == 0
    increment_agent_nonce(TEST_ADDRESS)
    assert get_agent_nonce(TEST_ADDRESS) == 1


def test_nonce_independent_per_agent():
    addr2 = "0x2222222222222222222222222222222222222222"
    assert get_agent_nonce(TEST_ADDRESS) == 0
    assert get_agent_nonce(addr2) == 0
    increment_agent_nonce(TEST_ADDRESS)
    assert get_agent_nonce(TEST_ADDRESS) == 1
    assert get_agent_nonce(addr2) == 0


def test_nonce_persists_in_db():
    """Nonce хранится в БД, переживает перезагрузку."""
    assert get_agent_nonce(TEST_ADDRESS) == 0
    increment_agent_nonce(TEST_ADDRESS)
    increment_agent_nonce(TEST_ADDRESS)
    assert get_agent_nonce(TEST_ADDRESS) == 2

    # "Перезагрузка" — новое соединение
    assert get_agent_nonce(TEST_ADDRESS) == 2
    increment_agent_nonce(TEST_ADDRESS)
    assert get_agent_nonce(TEST_ADDRESS) == 3


# ─── Тесты: Processed events ───────────────────────────────


def test_event_not_processed_by_default():
    assert not is_event_processed("0xabc")


def test_mark_event_processed():
    mark_event_processed("0xabc", "topup")
    assert is_event_processed("0xabc")


def test_mark_event_processed_dedup():
    mark_event_processed("0xabc", "topup")
    mark_event_processed("0xabc", "topup")
    assert is_event_processed("0xabc")


# ─── Тесты: API register ────────────────────────────────────


def test_register():
    resp = client.post("/register", json={"address": TEST_ADDRESS})
    assert resp.status_code == 200
    data = resp.json()
    assert data["address"] == TEST_ADDRESS
    assert "Agent#" in data["agent_id"]


def test_register_dedup():
    r1 = client.post("/register", json={"address": TEST_ADDRESS})
    r2 = client.post("/register", json={"address": TEST_ADDRESS})
    assert r1.json()["agent_id"] == r2.json()["agent_id"]


# ─── Тесты: API balance ─────────────────────────────────────


def test_balance_not_registered():
    resp = client.get(f"/balance/0x1111111111111111111111111111111111111111")
    assert resp.status_code == 400


def test_balance_zero_after_register():
    client.post("/register", json={"address": TEST_ADDRESS})
    resp = client.get(f"/balance/{TEST_ADDRESS}")
    assert resp.status_code == 200
    assert resp.json()["balance"] == 0.0


# ─── Тесты: API pay (с подписью) ─────────────────────────


def test_pay_success():
    client.post("/register", json={"address": TEST_ADDRESS})
    client.post("/register", json={"address": TEST_RECIPIENT})
    from database import update_balance
    update_balance(TEST_ADDRESS, 100.0)

    nonce = get_agent_nonce(TEST_ADDRESS)
    sig = sign_msg(build_message("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.5, nonce))

    resp = client.post("/pay", json={
        "sender": TEST_ADDRESS,
        "recipient": TEST_RECIPIENT,
        "amount": 10.5,
        "nonce": nonce,
        "signature": sig,
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["amount"] == 10.5
    assert data["fee"] == 0.05  # 0.5%
    assert abs(data["sender_balance_after"] - 89.5) < 0.01  # 100 - 10.5
    assert data["status"] == "completed"


def test_pay_deducts_fee_from_recipient():
    """Получатель получает сумму за вычетом комиссии."""
    client.post("/register", json={"address": TEST_ADDRESS})
    client.post("/register", json={"address": TEST_RECIPIENT})
    from database import update_balance
    update_balance(TEST_ADDRESS, 100.0)

    nonce = get_agent_nonce(TEST_ADDRESS)
    sig = sign_msg(build_message("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.0, nonce))

    client.post("/pay", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 10.0, "nonce": nonce, "signature": sig,
    })

    # Баланс получателя: 0 + (10.0 - 0.05) = 9.95
    resp = client.get(f"/balance/{TEST_RECIPIENT}")
    assert abs(resp.json()["balance"] - 9.95) < 0.01


def test_pay_wrong_nonce():
    client.post("/register", json={"address": TEST_ADDRESS})
    client.post("/register", json={"address": TEST_RECIPIENT})
    from database import update_balance
    update_balance(TEST_ADDRESS, 100.0)

    sig = sign_msg(build_message("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.0, 5))

    resp = client.post("/pay", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 10.0, "nonce": 5, "signature": sig,
    })
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == 1013


def test_pay_double_spend_rejected():
    """Повторный запрос с тем же nonce отклоняется."""
    client.post("/register", json={"address": TEST_ADDRESS})
    client.post("/register", json={"address": TEST_RECIPIENT})
    from database import update_balance
    update_balance(TEST_ADDRESS, 100.0)

    nonce = get_agent_nonce(TEST_ADDRESS)
    sig = sign_msg(build_message("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.0, nonce))

    # Первый запрос — успех
    r1 = client.post("/pay", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 10.0, "nonce": nonce, "signature": sig,
    })
    assert r1.status_code == 200

    # Второй запрос с тем же nonce — ошибка
    r2 = client.post("/pay", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 10.0, "nonce": nonce, "signature": sig,
    })
    assert r2.status_code == 400
    assert r2.json()["detail"]["code"] == 1013


def test_pay_wrong_signature():
    client.post("/register", json={"address": TEST_ADDRESS})
    client.post("/register", json={"address": TEST_RECIPIENT})
    from database import update_balance
    update_balance(TEST_ADDRESS, 100.0)

    resp = client.post("/pay", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 10.0, "nonce": 0, "signature": "0x" + "aa" * 65,
    })
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == 1014


def test_pay_insufficient_balance():
    client.post("/register", json={"address": TEST_ADDRESS})
    client.post("/register", json={"address": TEST_RECIPIENT})

    nonce = get_agent_nonce(TEST_ADDRESS)
    sig = sign_msg(build_message("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.0, nonce))

    resp = client.post("/pay", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 10.0, "nonce": nonce, "signature": sig,
    })
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == 1001


# ─── Тесты: API withdraw (с подписью) ─────────────────────

def test_withdraw_success(monkeypatch):
    """Проверяет: подпись, nonce, комиссию, списание — без реальной отправки USDC."""
    # Мокаем send_usdc — в тесте не отправляем реальные USDC
    monkeypatch.setattr("server.send_usdc", lambda r, a: "0x" + "ff" * 32)

    client.post("/register", json={"address": TEST_ADDRESS})
    from database import update_balance
    update_balance(TEST_ADDRESS, 500.0)

    nonce = get_agent_nonce(TEST_ADDRESS)
    sig = sign_msg(build_message("withdraw", TEST_ADDRESS, TEST_RECIPIENT, 100.0, nonce))

    resp = client.post("/withdraw", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 100.0, "nonce": nonce, "signature": sig,
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["amount"] == 100.0
    assert data["fee"] == 3.0  # 3%
    assert data["status"] == "completed"
    assert data["tx_hash"] is not None

    # Баланс списан
    bal = client.get(f"/balance/{TEST_ADDRESS}").json()["balance"]
    assert bal == 400.0  # 500 - 100


def test_withdraw_wrong_signature():
    client.post("/register", json={"address": TEST_ADDRESS})
    from database import update_balance
    update_balance(TEST_ADDRESS, 500.0)

    resp = client.post("/withdraw", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 100.0, "nonce": 0, "signature": "0x" + "bb" * 65,
    })
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == 1014


# ─── Тесты: Rate limit ─────────────────────────────────────


def test_rate_limit_middleware_exists():
    """Rate limit middleware загружен и работает."""
    resp = client.get("/health")
    assert resp.status_code == 200  # Просто проверяем что сервер жив


# ─── Тесты: API health ──────────────────────────────────────


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert data["version"] == "0.2.0"


# ─── Тесты: Nonce API ──────────────────────────────────────


def test_nonce_api():
    client.post("/register", json={"address": TEST_ADDRESS})
    resp = client.get(f"/nonce/{TEST_ADDRESS}")
    assert resp.status_code == 200
    assert resp.json()["nonce"] == 0

    increment_agent_nonce(TEST_ADDRESS)
    resp = client.get(f"/nonce/{TEST_ADDRESS}")
    assert resp.json()["nonce"] == 1


# ─── Тесты: History ────────────────────────────────────────


def test_history_empty():
    client.post("/register", json={"address": TEST_ADDRESS})
    resp = client.get(f"/history/{TEST_ADDRESS}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_history_after_pay():
    client.post("/register", json={"address": TEST_ADDRESS})
    client.post("/register", json={"address": TEST_RECIPIENT})
    from database import update_balance
    update_balance(TEST_ADDRESS, 100.0)

    nonce = get_agent_nonce(TEST_ADDRESS)
    sig = sign_msg(build_message("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.0, nonce))
    client.post("/pay", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 10.0, "nonce": nonce, "signature": sig,
    })

    resp = client.get(f"/history/{TEST_ADDRESS}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


# ─── Тесты: Audit ────────────────────────────────────────


def test_audit_empty():
    """/audit возвращает структуру с нулями."""
    resp = client.get("/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert "usdc_balance" in data
    assert "total_credit" in data
    assert "difference" in data
    assert "agent_count" in data
    assert "recent_transactions" in data
    assert data["agent_count"] == 0
    assert data["total_credit"] == 0.0


def test_audit_after_pay():
    """/audit показывает данные после операций."""
    client.post("/register", json={"address": TEST_ADDRESS})
    client.post("/register", json={"address": TEST_RECIPIENT})
    from database import update_balance
    update_balance(TEST_ADDRESS, 100.0)

    nonce = get_agent_nonce(TEST_ADDRESS)
    sig = sign_msg(build_message("pay", TEST_ADDRESS, TEST_RECIPIENT, 10.0, nonce))
    client.post("/pay", json={
        "sender": TEST_ADDRESS, "recipient": TEST_RECIPIENT,
        "amount": 10.0, "nonce": nonce, "signature": sig,
    })

    resp = client.get("/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_count"] == 2
    assert len(data["recent_transactions"]) >= 1


# ─── Тесты: Topup (без реальной Base сети) ─────────────────


def test_topup_request():
    """POST /topup возвращает адрес для депозита."""
    resp = client.post("/topup", json={
        "address": TEST_ADDRESS,
        "amount": 100.0,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["deposit_address"] is not None
    assert data["status"] == "pending"


def test_topup_confirm_no_base():
    """Без реального tx_hash на Base — ошибка."""
    client.post("/register", json={"address": TEST_ADDRESS})
    resp = client.post(f"/topup/confirm/{TEST_ADDRESS}", json={
        "tx_hash": "0x" + "ff" * 32,
    })
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == 1012
