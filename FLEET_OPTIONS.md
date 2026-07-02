# DEXTER: Multi-Account Fleet Options

These are the pre-researched architectures for scaling Dexter across multiple accounts simultaneously.

## 🚀 Option 1: TopstepX Native Fleet
*   **Target:** NQ/ES Futures (Combine & Express Funded)
*   **Technology:** ProjectX API + TopstepX Internal Copier
*   **Capacity:** Multiple accounts (Follower accounts mirror the Lead)
*   **Pros:** Native server-side execution (lowest slippage), no third-party software needed.
*   **Cons:** Monthly API subscription (~$29).

## 🥷 Option 2: Apex/NinjaTrader Fleet
*   **Target:** NQ/ES Futures (Apex Performance Accounts)
*   **Technology:** Rithmic/Tradovate API + NinjaTrader + Replikanto
*   **Capacity:** Up to 20 accounts.
*   **Pros:** Most robust industry standard, allows "Grouping" across different brokers.
*   **Cons:** Requires NinjaTrader to be running locally on your Mac.

## 🌍 Option 3: OANDA Forex Fleet
*   **Target:** Forex (EUR/USD, GBP/USD, etc.)
*   **Technology:** OANDA v20 API (Custom Loop)
*   **Capacity:** Up to 19 sub-accounts per master login.
*   **Pros:** Easy to scale small accounts, native API support for all sub-accounts.
*   **Cons:** US residents limited to Forex and Spot Crypto (No Gold/Indices).

## 🏦 Option 4: The Schwab Hybrid Fleet
*   **Target:** SPY/QQQ Options
*   **Technology:** `schwab-py` API (Custom Loop)
*   **Capacity:** Limited by Schwab's authentication tokens.
*   **Pros:** Trade high-leverage options directly from your bank.
*   **Cons:** Most complex to automate across multiple distinct logins due to OAuth security.

---
**Status:** Architecture Researched. Ready for `fleet_config.yaml` implementation upon selection.
