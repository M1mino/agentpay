"""AgentPay — работа с SQLite."""

import sqlite3
import os
import json
from datetime import datetime
from decimal import Decimal


DB_PATH = "agentpay.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            address TEXT PRIMARY KEY,
            agent_id TEXT UNIQUE NOT NULL,
            balance REAL NOT NULL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transactions (
            tx_id TEXT PRIMARY KEY,
            tx_type TEXT NOT NULL,
            sender TEXT,
            recipient TEXT,
            amount REAL NOT NULL,
            fee REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            data TEXT
        );

        CREATE TABLE IF NOT EXISTS nonce (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            value INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO nonce (id, value) VALUES (1, 0);

        CREATE TABLE IF NOT EXISTS wallet_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_balance REAL NOT NULL DEFAULT 0.0,
            last_block INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO wallet_state (id, last_balance) VALUES (1, 0.0);

        CREATE TABLE IF NOT EXISTS agent_nonces (
            address TEXT PRIMARY KEY,
            nonce INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS processed_events (
            tx_hash TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            processed_at TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ─── Агенты ─────────────────────────────────────────────────


def register_agent(address: str) -> dict:
    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM agents WHERE address = ?", (address,)
    ).fetchone()
    if existing:
        conn.close()
        return dict(existing)

    # agent_id = Agent# + последние 4 символа адреса
    agent_id = f"Agent#{address[-4:].upper()}"
    now = datetime.utcnow().isoformat()

    conn.execute(
        "INSERT INTO agents (address, agent_id, balance, created_at, updated_at) VALUES (?, ?, 0.0, ?, ?)",
        (address, agent_id, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM agents WHERE address = ?", (address,)).fetchone()
    conn.close()
    return dict(row)


def get_agent(address: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM agents WHERE address = ?", (address,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_balance(address: str) -> float | None:
    conn = get_db()
    row = conn.execute("SELECT balance FROM agents WHERE address = ?", (address,)).fetchone()
    conn.close()
    return row["balance"] if row else None


def update_balance(address: str, new_balance: float):
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute(
        "UPDATE agents SET balance = ?, updated_at = ? WHERE address = ?",
        (new_balance, now, address),
    )
    conn.commit()
    conn.close()


# ─── Транзакции ─────────────────────────────────────────────


def add_transaction(tx_id: str, tx_type: str, sender: str | None, recipient: str | None,
                    amount: float, fee: float = 0.0, status: str = "completed", data: dict | None = None):
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO transactions (tx_id, tx_type, sender, recipient, amount, fee, status, created_at, data) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tx_id, tx_type, sender, recipient, amount, fee, status, now, json.dumps(data) if data else None),
    )
    conn.commit()
    conn.close()


def get_transactions(address: str, limit: int = 10) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM transactions WHERE sender = ? OR recipient = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (address, address, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─── Nonce ──────────────────────────────────────────────────


def next_nonce() -> int:
    conn = get_db()
    conn.execute("UPDATE nonce SET value = value + 1 WHERE id = 1")
    conn.commit()
    row = conn.execute("SELECT value FROM nonce WHERE id = 1").fetchone()
    conn.close()
    return row["value"]


# ─── Состояние кошелька ─────────────────────────────────────


def get_wallet_state() -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM wallet_state WHERE id = 1").fetchone()
    conn.close()
    return dict(row)


def update_wallet_state(last_balance: float, last_block: int = 0):
    conn = get_db()
    conn.execute(
        "UPDATE wallet_state SET last_balance = ?, last_block = ? WHERE id = 1",
        (last_balance, last_block),
    )
    conn.commit()
    conn.close()


# ─── Nonce для агентов ────────────────────────────────────────


def get_agent_nonce(address: str) -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT nonce FROM agent_nonces WHERE address = ?", (address,)
    ).fetchone()
    if not row:
        conn.execute("INSERT INTO agent_nonces (address, nonce) VALUES (?, 0)", (address,))
        conn.commit()
        conn.close()
        return 0
    conn.close()
    return row["nonce"]


def increment_agent_nonce(address: str) -> int:
    conn = get_db()
    conn.execute(
        "INSERT INTO agent_nonces (address, nonce) VALUES (?, 1) "
        "ON CONFLICT(address) DO UPDATE SET nonce = nonce + 1",
        (address,),
    )
    conn.commit()
    row = conn.execute("SELECT nonce FROM agent_nonces WHERE address = ?", (address,)).fetchone()
    conn.close()
    return row["nonce"]


# ─── Processed events (защита от повторной обработки) ─────────


def mark_event_processed(tx_hash: str, event_type: str):
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO processed_events (tx_hash, event_type, processed_at) VALUES (?, ?, ?)",
        (tx_hash, event_type, now),
    )
    conn.commit()
    conn.close()


# ─── Audit (балансовая сверка) ────────────────────────────────


def get_total_credit() -> float:
    """Сумма CREDIT всех агентов."""
    conn = get_db()
    row = conn.execute("SELECT COALESCE(SUM(balance), 0.0) as total FROM agents").fetchone()
    conn.close()
    return row["total"]


def get_agent_count() -> int:
    """Количество зарегистрированных агентов."""
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as count FROM agents").fetchone()
    conn.close()
    return row["count"]


def get_recent_transactions(limit: int = 10) -> list:
    """Последние транзакции (любые, без фильтра по адресу)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM transactions ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_event_processed(tx_hash: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM processed_events WHERE tx_hash = ?", (tx_hash,)
    ).fetchone()
    conn.close()
    return row is not None
