"""AgentPay — Pydantic модели."""

from pydantic import BaseModel, Field
from typing import Optional
from decimal import Decimal
from datetime import datetime


class RegisterRequest(BaseModel):
    address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")


class RegisterResponse(BaseModel):
    agent_id: str
    address: str
    created_at: str


class BalanceResponse(BaseModel):
    address: str
    balance: float
    updated_at: str


class PayRequest(BaseModel):
    sender: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    recipient: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    amount: float = Field(..., gt=0)


class PayResponse(BaseModel):
    tx_id: str
    sender: str
    recipient: str
    amount: float
    fee: float
    sender_balance_after: float
    status: str = "completed"


class TopupRequest(BaseModel):
    address: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    amount: float = Field(..., gt=0)


class TopupResponse(BaseModel):
    deposit_address: str
    amount: float
    network: str = "Base"
    status: str = "pending"


class WithdrawRequest(BaseModel):
    sender: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")
    amount: float = Field(..., gt=0)
    recipient: str = Field(..., pattern=r"^0x[a-fA-F0-9]{40}$")


class WithdrawResponse(BaseModel):
    tx_id: str
    amount: float
    fee: float
    recipient: str
    status: str = "processing"


class HistoryResponse(BaseModel):
    transactions: list
    total: int


class ErrorResponse(BaseModel):
    code: int
    message: str
