# AgentPay

Payment layer for AI agents.

Internal currency CREDIT (1 CREDIT = 1 USDC). Base USDC on ramp / off ramp.

## Features

- **Topup (/topup)** — send USDC on Base, get CREDIT
- **Pay (/pay)** — instant transfers between agents, zero gas
- **Withdraw (/withdraw)** — convert CREDIT back to USDC
- **History (/history)** — all transactions

## Status

🚧 Work in progress. First commit — May 22, 2026.

## Structure

```
agentpay/
├── SKILL.md          # Skill description for AI agents
├── README.md         # This file
├── server.py         # FastAPI backend
├── database.py       # SQLite
├── base_client.py    # Base (web3.py) integration
├── models.py         # Pydantic schemas
├── config.py         # Settings
└── requirements.txt  # Dependencies
```

## Tech Stack

- **Python** / FastAPI
- **SQLite** (WAL mode)
- **web3.py** (Base / USDC)
- **Pydantic** (validation)

## License

MIT
