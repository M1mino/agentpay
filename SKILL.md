---
name: agentpay
description: Payment layer for AI agents. Register agents, topup CREDIT balance by sending USDC on Base, pay other agents with signed EIP-191 transactions, and withdraw CREDIT back to USDC. Use when an agent needs to pay another agent or service for data, API access, or tools — or when building agent-to-agent payment flows. Triggers: "pay agent", "send payment", "topup balance", "withdraw funds", "agent transaction", "agent-to-agent payment".
allowed-tools:
  - "Bash(execute) for curl HTTP requests"
  - "Read for checking SKILL.md reference files"
version: "1.0.0"
author: "Anfisa <anfisa@agentpay.dev>"
license: MIT
compatibility: "Requires Python 3.11+, web3.py 7+, access to Base network (mainnet or sepolia). Agent needs an Ethereum wallet (private key) for signing transactions."
tags:
  - payments
  - agents
  - base
  - usdc
  - crypto
  - blockchain
  - agent-to-agent
  - microtransactions
---

# AgentPay

AgentPay is a REST API payment layer for AI agents. Agents register with a Base address, receive CREDIT (1 CREDIT = 1 USDC) when a user sends USDC to the AgentPay wallet, and transfer CREDIT to other registered agents via signed EIP-191 transactions. Withdrawals convert CREDIT back to USDC on Base.

## Overview

AgentPay provides instant, gasless payments between AI agents using an internal CREDIT currency pegged 1:1 to USDC. On-chain settlements happen only on deposit (topup) and withdrawal — intra-agent transfers are database operations with cryptographic signature verification.

**Key concepts:**
- **CREDIT** — internal currency, 1 CREDIT = 1 USDC (fixed peg)
- **Nonce** — per-agent counter that increments on each transaction, prevents replay attacks
- **Signature** — every pay and withdraw request must be signed with the agent's Ethereum private key (EIP-191 personal_sign)
- **Audit** — the `/audit` endpoint publishes total CREDIT vs on-chain USDC balance for transparency

**Fee structure:**
| Operation | Fee |
|-----------|-----|
| Topup (USDC → CREDIT) | 0% |
| Pay (CREDIT transfer) | 0.5% |
| Withdraw (CREDIT → USDC) | 3% |

## Prerequisites

Before using AgentPay, ensure the following are available:

1. **AgentPay server running** — deployed and accessible at `http://{host}:8004`
2. **Agent Ethereum wallet** — the agent must have a Base address and its private key
3. **USDC on Base** — the user must have USDC to topup the agent's CREDIT balance
4. **Network access** — ability to make HTTP requests to the AgentPay server
5. **Python 3.11+ with web3.py** — for signing transactions (or any Ethereum-compatible signing tool)

## Instructions

### 1. Register the Agent

Register the agent's Base address to create an AgentPay account:

```bash
curl -X POST http://localhost:8004/register \
  -H "Content-Type: application/json" \
  -d '{"address": "0xAgentAddressHere..."}'
```

**Response:** Returns `agent_id`, `address`, and `created_at`.

### 2. Check Balance

```bash
curl http://localhost:8004/balance/0xAgentAddressHere...
```

### 3. Topup (Deposit USDC)

Send USDC to the AgentPay wallet address (retrieved from `/topup`), then confirm:

```bash
# Step 1: Get deposit address
curl -X POST http://localhost:8004/topup \
  -H "Content-Type: application/json" \
  -d '{"address": "0xAgentAddressHere...", "amount": 100}'

# Step 2: After sending USDC on Base, confirm with tx_hash
curl -X POST http://localhost:8004/topup/confirm/0xAgentAddressHere... \
  -H "Content-Type: application/json" \
  -d '{"tx_hash": "0xTransactionHashOnBase..."}'
```

### 4. Pay Another Agent

This is the core operation. The agent must sign the request with its private key.

**Step 4a:** Get the current nonce:
```bash
curl http://localhost:8004/nonce/0xAgentAddressHere...
```

**Step 4b:** Sign the message using EIP-191 (personal_sign):
```python
from web3 import Web3
from eth_account.messages import encode_defunct

w3 = Web3()
message = "agentpay_v1:pay:0xSender:0xRecipient:10.50:0"
message_encoded = encode_defunct(text=message)
signed = w3.eth.account.sign_message(message_encoded, private_key="0xPrivateKey")
signature = signed.signature.hex()  # 132 hex chars
```

**Step 4c:** Send the signed request:
```bash
curl -X POST http://localhost:8004/pay \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "0xSender...",
    "recipient": "0xRecipient...",
    "amount": 10.50,
    "nonce": 0,
    "signature": "0xSignature..."
  }'
```

The sender loses `amount` CREDIT. The recipient receives `amount - (amount * 0.5%)`. The sender's nonce increments by 1.

### 5. Withdraw

Same signing flow as pay. Convert CREDIT back to USDC:

```bash
curl -X POST http://localhost:8004/withdraw \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "0xSender...",
    "amount": 100.0,
    "recipient": "0xRecipientOnBase...",
    "nonce": 1,
    "signature": "0xSignature..."
  }'
```

The agent loses `amount` CREDIT. The recipient receives `(amount * 0.97)` USDC on Base (3% fee).

### 6. Audit

Check system transparency — USDC on wallet vs total CREDIT in circulation:

```bash
curl http://localhost:8004/audit
```

## Output

All endpoints return JSON. Successful responses include a `status` field (`"completed"` or `"pending"`) and operation-specific data.

**Pay response example:**
```json
{
  "tx_id": "pay_a1b2c3d4e5f6",
  "sender": "0xSender...",
  "recipient": "0xRecipient...",
  "amount": 10.50,
  "fee": 0.05,
  "sender_balance_after": 89.50,
  "status": "completed"
}
```

**Audit response example:**
```json
{
  "usdc_balance": 500.00,
  "total_credit": 485.75,
  "difference": 14.25,
  "difference_note": "profit_buffer",
  "agent_count": 3
}
```

## Error Handling

| HTTP Code | Error Code | Cause | Solution |
|-----------|-----------|-------|----------|
| 400 | 1001 | Insufficient CREDIT balance | Check agent balance via `/balance` before paying |
| 400 | 1002 | Recipient not registered | Ensure recipient calls `/register` first |
| 400 | 1013 | Wrong nonce | Get fresh nonce from `/nonce/{address}` — nonce must match server state exactly |
| 400 | 1014 | Invalid signature | Verify message format: `agentpay_v1:{action}:{sender}:{recipient}:{amount}:{nonce}`. Check private key is correct |
| 400 | 1004 | Amount below minimum | Topup: min 1 USDC. Pay: min 0.01 CREDIT. Withdraw: min 10 CREDIT |
| 400 | 1005 | Amount exceeds maximum | Topup: max 10,000 USDC. Pay: max 1,000 CREDIT. Withdraw: max 5,000 CREDIT |
| 400 | 1012 | Transfer event not found | Verify tx_hash is valid on Base network and sender address matches |
| 429 | 2001 | Rate limit exceeded | Wait 10 seconds before retrying (20 POST requests per 10s window) |

**Missing environment variable:** If `X402_PRIVATE_KEY` is not set in the server's `.env`, withdraw returns `status: "pending_manual"` instead of `"completed"`. Withdrawals are queued but not executed.

**Network error:** If Base RPC is unreachable, `/health` returns `{"status": "base_disconnected"}`. Check that the server has internet access to the Base network.

## Examples

### Example 1: Two agents — Alice pays Bob 10 CREDIT

**Setup:**
```bash
# Alice registers
curl -X POST http://localhost:8004/register -H "Content-Type: application/json" \
  -d '{"address": "0xAliceAddress..."}'
# → {"agent_id": "Agent#A1A1", ...}

# Bob registers
curl -X POST http://localhost:8004/register -H "Content-Type: application/json" \
  -d '{"address": "0xBobAddress..."}'
# → {"agent_id": "Agent#B0B0", ...}

# Alice's balance is credited (by user sending USDC)
# Alice checks balance: 100 CREDIT
```

**Payment:**
```bash
# 1. Alice gets nonce: 0
nonce=$(curl -s http://localhost:8004/nonce/0xAliceAddress... | python3 -c "import json,sys; print(json.load(sys.stdin)['nonce'])")

# 2. Alice signs: agentpay_v1:pay:0xAlice...:0xBob...:10.0:0
# (signing happens off-chain with private key)

# 3. Alice sends pay request
curl -X POST http://localhost:8004/pay -H "Content-Type: application/json" \
  -d '{"sender": "0xAlice...", "recipient": "0xBob...", "amount": 10.0, "nonce": 0, "signature": "0xSignature..."}'
```

**Result:** Alice loses 10 CREDIT (balance: 90). Bob receives 9.95 CREDIT (10 - 0.05 fee). Nonce becomes 1.

### Example 2: Agent pays for API access

An AI agent needs to call a paid API:

```bash
# Agent pays the API provider agent 0.50 CREDIT per request
curl -X POST http://localhost:8004/pay -H "Content-Type: application/json" \
  -d '{
    "sender": "0xAgent...",
    "recipient": "0xApiProvider...",
    "amount": 0.50,
    "nonce": 3,
    "signature": "0x..."
  }'
```

The API provider agent verifies the payment via `/history`, then serves the request.

### Example 3: Full audit check

```bash
curl http://localhost:8004/audit
# → Shows: usdc_balance matches total_credit + fees collected (transparency)
```

## Resources

- **GitHub repository:** [github.com/M1mino/agentpay](https://github.com/M1mino/agentpay)
- **AgentPay SKILL.md:** Contains complete command reference and signing examples
- **Base network docs:** [base.org](https://base.org)
- **USDC on Base:** Native USDC contract `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- **EIP-191 (personal_sign):** [eips.ethereum.org/EIPS/eip-191](https://eips.ethereum.org/EIPS/eip-191)
- **SKILL.md specification:** [agentskills.io/specification](https://agentskills.io/specification)
