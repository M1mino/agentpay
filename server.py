"""AgentPay — FastAPI сервер."""

import uuid
import time
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Request
from decimal import Decimal

from config import (
    PORT, HOST, AGENTPAY_WALLET, PAY_FEE_PERCENT, WITHDRAW_FEE_PERCENT,
    MIN_TOPUP, MAX_TOPUP, MIN_PAY, MAX_PAY, MAX_PAY_DAY,
    MIN_WITHDRAW, MAX_WITHDRAW, MAX_WITHDRAW_DAY,
)
from database import (
    init_db, register_agent, get_agent, get_balance,
    update_balance, add_transaction, get_transactions,
    get_agent_nonce, increment_agent_nonce,
    is_event_processed, mark_event_processed,
    get_wallet_state, update_wallet_state,
)
from models import (
    RegisterRequest, RegisterResponse, BalanceResponse,
    PayRequest, PayResponse, TopupRequest, TopupResponse,
    TopupConfirmRequest,
    WithdrawRequest, WithdrawResponse, HistoryResponse, ErrorResponse,
)
from base_client import (
    is_connected, get_usdc_balance,
    verify_signature, verify_topup_transfer,
    send_usdc,
)

app = FastAPI(title="AgentPay", version="0.2.0")


# ─── Rate limiter (in-memory) ─────────────────────────────────


RATE_LIMIT_REQUESTS = 20
RATE_LIMIT_WINDOW = 1  # секунда
_rate_store: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(ip: str):
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    timestamps = [t for t in _rate_store[ip] if t > window_start]
    timestamps.append(now)
    _rate_store[ip] = timestamps
    if len(timestamps) > RATE_LIMIT_REQUESTS:
        raise HTTPException(status_code=429, detail={
            "code": 2001, "message": "Слишком много запросов. Попробуйте через секунду."
        })


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE"):
        ip = request.client.host if request.client else "unknown"
        try:
            check_rate_limit(ip)
        except HTTPException:
            raise
    return await call_next(request)


# ─── Startup ──────────────────────────────────────────────────


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


# ─── Topup (запрос на пополнение) ──────────────────────────


@app.post("/topup", response_model=TopupResponse)
def topup(req: TopupRequest):
    if req.amount < MIN_TOPUP:
        make_error(1004, f"Минимальная сумма topup: {MIN_TOPUP} USDC")
    if req.amount > MAX_TOPUP:
        make_error(1005, f"Максимальная сумма topup: {MAX_TOPUP} USDC")

    return TopupResponse(
        deposit_address=AGENTPAY_WALLET,
        amount=req.amount,
        status="pending",
    )


# ─── Topup confirm (через Transfer event) ────────────────────


@app.post("/topup/confirm/{address}")
def confirm_topup(address: str, req: TopupConfirmRequest):
    agent = get_agent(address)
    if not agent:
        make_error(1002, "Агент не зарегистрирован")

    # Проверяем что tx_hash ещё не обработан
    if is_event_processed(req.tx_hash):
        make_error(1011, "Транзакция уже обработана")

    # Верифицируем Transfer event на Base
    transfer = verify_topup_transfer(req.tx_hash, address, 0)
    if not transfer:
        make_error(1012, "Перевод USDC не найден. Проверьте tx_hash и адрес отправителя.")

    amount = round(transfer["value"], 2)
    if amount < MIN_TOPUP:
        make_error(1004, f"Минимальная сумма topup: {MIN_TOPUP} USDC")
    if amount > MAX_TOPUP:
        make_error(1005, f"Максимальная сумма topup: {MAX_TOPUP} USDC")

    # Комиссия 0% на topup
    fee = 0.0
    credit_amount = amount
    new_balance = agent["balance"] + credit_amount

    tx_id = f"topup_{uuid.uuid4().hex[:12]}"
    update_balance(address, new_balance)
    add_transaction(tx_id, "topup", None, address, amount, fee, "completed",
                    {"tx_hash": req.tx_hash, "block": transfer["block_number"]})
    mark_event_processed(req.tx_hash, "topup")

    # Обновляем состояние кошелька
    balance_now = get_usdc_balance(AGENTPAY_WALLET)
    update_wallet_state(balance_now, transfer["block_number"])

    return {
        "tx_id": tx_id,
        "amount": amount,
        "credited": credit_amount,
        "new_balance": round(new_balance, 2),
        "status": "completed",
        "tx_hash": req.tx_hash,
    }


# ─── Pay (подписанный перевод) ─────────────────────────────


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

    # Проверяем nonce (защита от double-spend)
    current_nonce = get_agent_nonce(req.sender)
    if req.nonce != current_nonce:
        make_error(1013, f"Неверный nonce. Текущий: {current_nonce}, получен: {req.nonce}")

    # Проверяем подпись
    if not verify_signature("pay", req.sender, req.recipient, req.amount, req.nonce, req.signature):
        make_error(1014, "Неверная подпись. Сообщение для подписи: "
                   f"agentpay_v1:pay:{req.sender}:{req.recipient}:{req.amount}:{req.nonce}")

    # Комиссия 0.5% на pay
    fee = round(req.amount * PAY_FEE_PERCENT / 100, 2)
    amount_after_fee = req.amount - fee
    sender_new = sender["balance"] - req.amount
    recipient_new = recipient["balance"] + amount_after_fee

    tx_id = f"pay_{uuid.uuid4().hex[:12]}"

    # Инкрементим nonce (атомарно)
    increment_agent_nonce(req.sender)

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


# ─── Withdraw (подписанный вывод) ──────────────────────────


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

    # Проверяем nonce
    current_nonce = get_agent_nonce(req.sender)
    if req.nonce != current_nonce:
        make_error(1013, f"Неверный nonce. Текущий: {current_nonce}, получен: {req.nonce}")

    # Проверяем подпись
    if not verify_signature("withdraw", req.sender, req.recipient, req.amount, req.nonce, req.signature):
        make_error(1014, "Неверная подпись. Сообщение для подписи: "
                   f"agentpay_v1:withdraw:{req.sender}:{req.recipient}:{req.amount}:{req.nonce}")

    fee = round(req.amount * WITHDRAW_FEE_PERCENT / 100, 2)
    amount_to_send = req.amount - fee
    new_balance = agent["balance"] - req.amount

    tx_id = f"withdraw_{uuid.uuid4().hex[:12]}"

    # Инкрементим nonce
    increment_agent_nonce(req.sender)

    # Списываем CREDIT сразу
    update_balance(req.sender, new_balance)

    # Отправляем USDC на Base
    try:
        tx_hash = send_usdc(req.recipient, int(amount_to_send * 10**6))
        status = "completed"
    except ValueError as e:
        if "AGENTPAY_PRIVATE_KEY" in str(e):
            status = "pending_manual"
            tx_hash = None
        else:
            raise

    add_transaction(tx_id, "withdraw", req.sender, req.recipient, req.amount, fee, status,
                    {"tx_hash": tx_hash or "", "withdraw_tx_hash": tx_hash or ""})

    return WithdrawResponse(
        tx_id=tx_id,
        amount=req.amount,
        fee=fee,
        recipient=req.recipient,
        status=status,
        tx_hash=tx_hash,
    )


# ─── Nonce (агент запрашивает текущий nonce) ───────────────


@app.get("/nonce/{address}")
def get_nonce(address: str):
    """Возвращает текущий nonce для агента. Нужен для подписи запроса."""
    nonce = get_agent_nonce(address)
    return {"address": address, "nonce": nonce}


# ─── История ─────────────────────────────────────────────


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


# ─── Статус сети ──────────────────────────────────────────


@app.get("/health")
def health():
    return {
        "status": "ok" if is_connected() else "base_disconnected",
        "base_rpc": is_connected(),
        "agentpay_wallet": AGENTPAY_WALLET,
        "version": "0.2.0",
    }


# ─── Запуск ────────────────────────────────────────────────


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)
