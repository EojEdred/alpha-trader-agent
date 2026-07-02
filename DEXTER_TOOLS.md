# DEXTER TOOL MANIFEST

This manifest lists all capabilities available to the Dexter Agent.

## 📡 MARKET DATA TOOLS
| Tool ID | Capability | When to Use |
| :--- | :--- | :--- |
| `fetch_current_price` | Real-time price from Schwab/OANDA | To get the most recent quote for a symbol. |
| `fetch_ohlcv` | OHLCV Bar data (1m, 5m, 1h, 4h, Daily) | To analyze trend (Daily/4h) and entry precision (1m). |
| `get_option_chain` | Real-time Schwab Option Chain | To find liquid contracts for SPY and QQQ. |
| `topstep_get_price` | Real-time Futures Prices | To get quotes for NQ and ES from TopstepX. |
| `map_session_liquidity` | Session Extreme Mapping | To identify Asia/London/NY highs and untested targets. |

## 📐 ANALYSIS & SCORING TOOLS
| Tool ID | Capability | When to Use |
| :--- | :--- | :--- |
| `calculate_profile` | Volume Profile Engine | To find POC (Point of Control) and FVA (Fair Value Area). |
| `get_order_flow` | Institutional Tape Reading | To detect "Liquidity Grabs" and Volume Breakouts (>1000/1m). |
| `calculate_technicals` | SMA, RSI, MACD Engine | To determine current market regime and trend. |
| `score_setup` | Liquidity Sweep Scoring | To grade a setup (0-100) based on the "Fade vs Trend" matrix. |

## 🧠 INTELLIGENCE & REASONING
| Tool ID | Capability | When to Use |
| :--- | :--- | :--- |
| `reason_about_setup` | LLM Inference (GPT-4) | To synthesize all data into a "Trading Thesis." |
| `self_reflect` | Agent Learning Loop | To analyze past trades and improve future decision-making. |

## ⚖️ RISK & COMPLIANCE TOOLS
| Tool ID | Capability | When to Use |
| :--- | :--- | :--- |
| `check_pdt_compliance` | Real-time Schwab PDT Tracker | **MANDATORY** before any intraday trade to verify 3/5 day limit. |
| `topstep_check_compliance` | Topstep Combine Watchdog | To ensure futures trades don't violate Daily Loss or Drawdown. |
| `select_best_contract` | Expiration Guardrail | To select contracts with safe DTE (>=1 for scalp, >=3 for swing). |
| `evaluate_stops` | Expiration Watchdog | To identify positions that must be closed today due to 0DTE risk. |

## 🚀 EXECUTION TOOLS
| Tool ID | Capability | When to Use |
| :--- | :--- | :--- |
| `submit_trade` | Automated Order Routing | To place trades on Schwab, TopstepX, or OANDA. |
| `get_all_positions` | Portfolio Monitoring | To track live P&L across all brokers. |
| `emergency_close` | Market Exit (Circuit Breaker) | To liquidate a position immediately if a guardrail is tripped. |

---
**Configuration Source:** `tools/tool_registry.yaml`  
**Implementation Source:** `tools/*.py`
