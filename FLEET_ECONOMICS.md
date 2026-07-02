# DEXTER: High-Leverage Futures Fleet Economics

This document outlines the capital requirements and profit potential for scaling Dexter across professional 20-account fleets using Mini Futures contracts.

---

## 1. Professional Asset Class Metrics (Mini Contracts)
Minis offer 10x the leverage of Micro contracts. These are the primary targets for the high-leverage fleet.

| Contract | Symbol | Value per Point | Day Trade Margin | Notional Value (Approx) |
| :--- | :--- | :--- | :--- | :--- |
| **E-mini Nasdaq 100** | **NQ** | **$20.00 / pt** | $1,000 | ~$400,000 |
| **E-mini S&P 500** | **ES** | **$50.00 / pt** | $500 | ~$250,000 |
| Crude Oil | CL | $1,000 / pt | $1,000 | ~$75,000 |
| Gold | GC | $100 / pt | $1,000 | ~$200,000 |

*   **Most Capital Efficient:** **ES** ($500 margin per contract).
*   **Highest Volatility/Yield:** **NQ** ($20/pt with fast movement).

---

## 2. Setup Costs: The "Master Fleet" (20 Accounts)
Calculated using **Apex Trader Funding ($50k Accounts)** as the primary vehicle.

| Item | Cost per Account | Fleet of 20 (x20) |
| :--- | :--- | :--- |
| **Evaluation Fee** (90% Promo) | $15.00 | $300.00 |
| **PA Activation Fee** (Lifetime) | $140.00 | $2,800.00 |
| **ProjectX API Subscription** | $29 / mo | $29.00 |
| **TOTAL INITIAL CAPITAL** | **$305.00** | **$3,129.00** |

---

## 3. Scaling Potential: Profit Projections
Assumes trading **1 Mini NQ Contract ($20/pt)** per account.  
Target performance: **40 – 80 points per week** via Dexter's A+ Liquidity Sweep strategy.

| Fleet Count | Total Accounts | Weekly Profit (40 pts) | Weekly Profit (80 pts) | Monthly Profit (Est.) |
| :--- | :--- | :--- | :--- | :--- |
| **1 Fleet** | 20 | **$16,000** | **$32,000** | **$64,000 – $128,000** |
| **5 Fleets** | 100 | **$80,000** | **$160,000** | **$320,000 – $640,000** |
| **10 Fleets** | 200 | **$160,000** | **$320,000** | **$640,000 – $1,280,000** |

---

## 4. Compliance & "Hidden" Operations
Scaling to 200 accounts (10 fleets) requires institutional-grade management:

1.  **The "30% Rule":** No single trading day can account for >30% of total profit for payout eligibility. Dexter automatically caps daily wins to maintain compliance.
2.  **LLC Architecture:** To remain compliant with Apex's household limits, each 20-account fleet should be registered to a separate **Legal Entity (LLC)**.
3.  **Hardware Requirements:** Running 200 concurrent Rithmic/Tradovate streams requires a dedicated **high-performance VM** (32GB RAM+ / 8 Cores) to prevent execution lag.
4.  **Slippage Buffer:** Expect 1-2 ticks of slippage across 200 accounts. Dexter is tuned to target high-liquidity zones to minimize this impact.

---
**Status:** Financial Model Validated (Order of 10).
