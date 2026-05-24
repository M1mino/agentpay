"""AgentPay — FastAPI сервер."""

import uuid
from datetime import datetime
from fastapi import FastAPI, HTTPException
from decimal import Decimal

from config import (
    PORT, HOST, AGENTPAY_WALLET, WITHDRAW_FEE_PERCENT,
    MIN_TOPUP, MAX_TOPUP, MIN_PAY, MAX_PAY, MAX_PAY_DAY,
    MIN_WITHDRAW, MAX_WITHDRAW, MAX_WITHDRAW_DAY,
)
from database import (
    init_db, register_agent, get_agent, get_balance,
    update_balance, add_transaction, get_transactions, next_nonce,
    get_wallet_state, update_wallet_state,
)
from models import (
    RegisterRequest, RegisterResponse, BalanceResponse,
    PayRequest, PayResponse, TopupRequest, TopupResponse,
    WithdrawRequest, WithdrawResponse, HistoryResponse, ErrorResponse,
)
from base_client import is_connected, get_usdc_balance, send_usdc

app = FastAPI(title="AgentPay", version="0.1.0")


@app.on_event("startup")
def startup():
    init_db()


def make_error(code: int, msg: str):
    raise HTTPException(status_code=400, detail={"code": code, "message": msg})


# ─── Регистрация ───────────────────────────────────────────


@app.post("/register", response_model=RegisterResponse)
def register(req: RegisterRequest):
    agent = register_agent(req.address)
    return RegisterResponse(
        agent_id=agent["agent_id"],
        address=agent["address"],
        created_at=agent["created_at"],
    )


# ─── Баланс ────────────────────────────────────────────────


@app.get("/balance/{address}", response_model=BalanceResponse)
def balance(address: str):
    agent = get_agent(address)
    if not agent:
        make_error(1002, "Агент не зарегистрирован")
    return BalanceResponse(
        address=address,
        balance=agent["balance"],
        updated_at=agent["updated_at"],
    )


# ─── Пополнение ─────────────────────────────────────────────


@app.post("/topup", response_model=TopupResponse)
def topup(req: TopupRequest):
    agent = get_agent(req.address)
    if not agent:
        make_error(1002, "Агент не зарегистрирован")

    if req.amount < MIN_TOPUP:
        make_error(1004, f"Минимальная сумма topup: {MIN_TOPUP} USDC")
    if req.amount > MAX_TOPUP:
        make_error(1005, f"Максимальная сумма topup: {MAX_TOPUP} USDC")

    return TopupResponse(
        deposit_address=AGENTPAY_WALLET,
        amount=req.amount,
        status="pending",
    )


# ─── Ончейн-верификация topup ───────────────────────────────


@app.post("/topup/confirm/{address}")
def confirm_topup(address: str):
    """Проверяет рост баланса кошелька и зачисляет CREDIT."""
    agent = get_agent(address)
    if not agent:
        make_error(1002, "Агент не зарегистрирован")

    wallet = get_wallet_state()
    last_balance = wallet["last_balance"]

    balance_now = get_usdc_balance(AGENTPAY_WALLET)
    if balance_now <= last_balance:
        make_error(1010, "Новых поступлений USDC не обнаружено")

    amount = balance_now - last_balance
    fee = 0.0  # topup — бесплатно
    credit_amount = amount
    new_balance = agent["balance"] + credit_amount

    # Обновляем состояние кошелька
    update_wallet_state(balance_now)

    tx_id = f"topup_{uuid.uuid4().hex[:12]}"
    update_balance(address, new_balance)
    add_transaction(tx_id, "topup", None, address, amount, fee)

    return {"tx_id": tx_id, "amount": round(amount, 2), "credited": round(credit_amount, 2),
            "new_balance": round(new_balance, 2), "status": "completed"}


# ─── Перевод (pay) ──────────────────────────────────────────


@app.post("/pay", response_model=PayResponse)
def pay(req: PayRequest):
    sender = get_agent(req.sender)
    if not sender:
        make_error(1002, "Отправитель не зарегистрирован")

    recipient = get_agent(req.recipient)
    if not recipient:
        make_error(1002, "Получатель не зарегистрирован")

    if req.amount < MIN_PAY:
        make_error(1004, f"Минимальная сумма pay: {MIN_PAY} CREDIT")
    if req.amount > MAX_PAY:
        make_error(1005, f"Максимальная сумма pay: {MAX_PAY} CREDIT")

    if sender["balance"] < req.amount:
        make_error(1001, f"Недостаточно средств. Баланс: {sender['balance']}, требуется: {req.amount}")

    # Комиссия 0% на pay
    fee = 0.0
    sender_new = sender["balance"] - req.amount
    recipient_new = recipient["balance"] + req.amount

    tx_id = f"pay_{uuid.uuid4().hex[:12]}"

    update_balance(req.sender, sender_new)
    update_balance(req.recipient, recipient_new)
    add_transaction(tx_id, "pay", req.sender, req.recipient, req.amount, fee)

    return PayResponse(
        tx_id=tx_id,
        sender=req.sender,
        recipient=req.recipient,
        amount=req.amount,
        fee=fee,
        sender_balance_after=sender_new,
    )


# ─── Вывод ──────────────────────────────────────────────────


@app.post("/withdraw", response_model=WithdrawResponse)
def withdraw(req: WithdrawRequest):
    agent = get_agent(req.sender)
    if not agent:
        make_error(1002, "Агент не зарегистрирован")

    if req.amount < MIN_WITHDRAW:
        make_error(1004, f"Минимальная сумма withdraw: {MIN_WITHDRAW} CREDIT")
    if req.amount > MAX_WITHDRAW:
        make_error(1005, f"Максимальная сумма withdraw: {MAX_WITHDRAW} CREDIT")

    if agent["balance"] < req.amount:
        make_error(1001, f"Недостаточно средств. Баланс: {agent['balance']}, требуется: {req.amount}")

    fee = round(req.amount * WITHDRAW_FEE_PERCENT / 100, 2)
    amount_to_send = req.amount - fee
    new_balance = agent["balance"] - req.amount

    tx_id = f"withdraw_{uuid.uuid4().hex[:12]}"

    # Списываем CREDIT сразу
    update_balance(req.sender, new_balance)

    # Отправляем USDC на Base
    try:
        tx_hash = send_usdc(req.recipient, int(amount_to_send * 10**6))
        status = "completed"
    except ValueError as e:
        if "AGENTPAY_PRIVATE_KEY" in str(e):
            # Ключ не задан — помечаем как manual
            status = "pending_manual"
            tx_hash = None
        else:
            raise

    add_transaction(tx_id, "withdraw", req.sender, req.recipient, req.amount, fee, status, {"tx_hash": tx_hash})

    return WithdrawResponse(
        tx_id=tx_id,
        amount=req.amount,
        fee=fee,
        recipient=req.recipient,
        status=status,
        tx_hash=tx_hash,
    )


# ─── История ────────────────────────────────────────────────


@app.get("/history/{address}", response_model=HistoryResponse)
def history(address: str, limit: int = 10):
    agent = get_agent(address)
    if not agent:
        make_error(1002, "Агент не зарегистрирован")

    if limit < 1:
        limit = 10
    if limit > 50:
        limit = 50

    txs = get_transactions(address, limit)
    return HistoryResponse(transactions=txs, total=len(txs))


# ─── Статус сети ────────────────────────────────────────────


@app.get("/health")
def health():
    return {
        "status": "ok" if is_connected() else "base_disconnected",
        "base_rpc": is_connected(),
        "agentpay_wallet": AGENTPAY_WALLET,
    }


# ─── Запуск ─────────────────────────────────────────────────


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
