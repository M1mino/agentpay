# AgentPay — Agent Registry for Direct USDC Payments

**AgentPay is a registry** that maps agent IDs to their Base wallet addresses. It does NOT hold funds, process payments, or charge fees. Every payment is a direct USDC transfer from one agent's wallet to another's on Base.

```
agent registry (lookup)
      │
      ▼
   Agent A  ───── USDC on Base ────→  Agent B
  (0xabc...)                          (0xdef...)
```

## Why?

AI agents need to pay each other for services — data, compute, API access. But existing payment systems either:
- Hold your money (custodial wallets, fees)
- Require complex smart contracts
- Don't have an agent-friendly interface

AgentPay solves this with one simple idea: **a phonebook for agent wallets.**

## How it works

1. **Register** — agent calls `/register` with their Base address
2. **Lookup** — another agent calls `/resolve/{agent_id}` and gets the wallet address
3. **Pay** — agent sends USDC directly to that address on Base

**No funds pass through AgentPay. No CREDIT tokens. No custody. Zero fees.**

## Quick Start

```bash
git clone https://github.com/M1mino/agentpay
cd agentpay
pip install -r requirements.txt
python server.py
```

Server starts on `http://localhost:8004`.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/register` | POST | Register an agent by Base address |
| `/agents` | GET | List all registered agents |
| `/resolve/{agent_id}` | GET | Get wallet address for an agent |
| `/resolve/by-address/{address}` | GET | Get agent ID by wallet address |

### Example

```python
import requests

# Register your agent
r = requests.post("http://localhost:8004/register", json={
    "agent_id": "my-agent",
    "address": "0xabc...def"
})
print(r.json())  # {"agent_id": "my-agent", "address": "0xabc...def", "created_at": "..."}

# Find another agent's address
r = requests.get("http://localhost:8004/resolve/target-agent")
print(r.json())  # {"agent_id": "target-agent", "address": "0xdef..."}

# Send USDC on Base directly — your wallet, your keys
```

## Comparison

| Feature | AgentPay | Payment processor |
|---------|----------|-------------------|
| Funds custody | **None** — you hold your keys | They hold your money |
| Fees | **Zero** | 0.5–3% |
| Trust model | **Trustless** — verify on Base | Must trust the operator |
| Censorship resistance | **Permissionless** | They can block you |
| Setup | One API call | KYC, approval, integration |

## Use Cases

- **Agent-to-agent payments** — agent A pays agent B for API access
- **Multi-agent payroll** — look up and pay many agents in a DAO
- **On-chain reputation** — registered agents build verifiable payment history
- **Agent service discovery** — find which wallet to pay for a service

## MCP Server

AgentPay also has an MCP server at [github.com/M1mino/agentpay-mcp](https://github.com/M1mino/agentpay-mcp) — connect any MCP-compatible agent (Claude, Codex, Hermes) directly.

## Deploy

```bash
# Docker
docker build -t agentpay .
docker run -p 8004:8004 agentpay

# Or systemd
cp deploy/agentpay.service /etc/systemd/system/
systemctl enable --now agentpay
```

## Limitations

- Only **Base** (EIP-155:8453) supported
- Registry is **public** — anyone can look up addresses
- **No escrow, no dispute resolution** — send at your own risk
- Single instance = single point of failure (deploy your own)

## License

MIT
