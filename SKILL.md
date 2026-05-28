---
name: agentpay
description: "AgentPay — agent registry for direct peer-to-peer USDC payments on Base. Agents register their wallet address, discover other agents, and transact directly (no intermediaries, no stored funds)."
trigger: user says "agentpay", "agent registry", "agent payments", "agent wallet", "agent address", "find agent", "pay agent"
---

# AgentPay — Agent Registry for Direct USDC Payments

## What it is

AgentPay is a **registry** that maps agent IDs to their Base wallet addresses. It does NOT hold funds, process payments, or charge fees. Every payment is a direct USDC transfer from one agent's wallet to another's on Base.

```
agent registry (lookup)
      │
      ▼
   Agent A  ───── USDC on Base ────→  Agent B
  (0xabc...)                          (0xdef...)
```

## How it works

1. **Register** — agent calls `/register` with their Base address (0x...)
2. **Lookup** — another agent calls `/resolve/{agent_id}` and gets the wallet address
3. **Pay** — agent sends USDC directly to that address on Base

No funds pass through AgentPay. No CREDIT tokens. No custody.

## Endpoints

| Endpoint | What it does |
|----------|-------------|
| POST /register | Register an agent by Base address |
| GET /agents | List all registered agents |
| GET /resolve/{agent_id} | Get wallet address for an agent |
| GET /resolve/by-address/{address} | Get agent ID by wallet address |

## Example flow

Agent A wants to pay Agent B 50 USDC:

1. Agent A calls `GET /resolve/AgentB`
   → Response: `{ "agent_id": "AgentB", "address": "0xdef..." }`

2. Agent A sends 50 USDC on Base to 0xdef...
   → Transaction appears on chain
   → Agent B's wallet receives 50 USDC

## Why direct payments?

| Feature | With AgentPay | With a payment processor |
|---------|--------------|-------------------------|
| Funds custody | **None** — you hold your keys | They hold your money |
| Fees | **Zero** | 0.5-3% |
| Trust | **Trustless** — verify on Base | Must trust the operator |
| Censorship | **Permissionless** | They can block you |

## Use cases

- Agent-to-agent payments for services (data, compute, API calls)
- Finding another agent's wallet to settle a collaboration
- DAO / multi-agent payroll — look up and pay many agents

## Deploy

```bash
git clone https://github.com/M1mino/agentpay
cd agentpay
pip install -r requirements.txt
python server.py  # starts on port 8004
```

## Example (Python)

```python
import requests

# Register your agent
r = requests.post("http://localhost:8004/register", json={
    "agent_id": "my-ai-agent",
    "address": "0xabc...def"
})

# Find another agent's address
r = requests.get("http://localhost:8004/resolve/target-agent")
address = r.json()["address"]

# Send USDC on Base using web3
# (user's own wallet, not AgentPay)
```

## Related

| Component | Repo | Purpose |
|-----------|------|---------|
| **AgentPay Registry** | github.com/M1mino/agentpay | Agent directory — register & resolve |
| **AgentPay MCP** | github.com/M1mino/agentpay-mcp | MCP proxy for agent-to-agent payments |

## Pitfalls

- Only Base (EIP-155:8453) — other chains not supported yet
- Registry is public — anyone can look up any agent's address
- No escrow, no dispute resolution — send at your own risk
- The registry is a single point of failure — consider running your own instance
