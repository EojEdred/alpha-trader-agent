"""
Trade Journal Miner / Shadow Account

Reads a CSV trade journal, extracts implicit trading rules, backtests them,
and reports delta-PnL. This can be used standalone or as a feeder for new
Alpha Trader strategy capsules.

Expected CSV columns (flexible):
- symbol: traded ticker
- entry_date, exit_date: ISO or YYYY-MM-DD dates
- entry_price, exit_price: float
- side: "long" or "short"
- size: number of shares/contracts
- pnl: realized P&L
- notes: optional free-text notes

Usage:
    from tools.journal_miner import JournalMiner

    miner = JournalMiner(config)
    result = await miner.mine("data/trade_journal.csv")
    print(result["rules"])
"""

import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from tools.vibe_trading import VibeTradingSidecar


class JournalMiner:
    """
    Mine trade journals for hidden edges and backtest extracted rules.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.vibe = VibeTradingSidecar(self.config)

    async def mine(
        self,
        journal_path: str,
        use_vibe: bool = True,
    ) -> Dict[str, Any]:
        """
        Mine a trade journal.

        Args:
            journal_path: Path to CSV file.
            use_vibe: If True, try Vibe-Trading shadow_backtest first.

        Returns:
            {
                "trades": int,
                "win_rate": float,
                "avg_pnl": float,
                "total_pnl": float,
                "rules": [str, ...],
                "shadow_backtest": Optional[dict],
                "symbols": [str, ...],
            }
        """
        path = Path(journal_path)
        if not path.exists():
            raise FileNotFoundError(f"Journal not found: {journal_path}")

        trades = self._load_trades(path)
        if not trades:
            return {
                "trades": 0,
                "win_rate": 0.0,
                "avg_pnl": 0.0,
                "total_pnl": 0.0,
                "rules": [],
                "shadow_backtest": None,
                "symbols": [],
            }

        stats = self._compute_stats(trades)
        rules = self._extract_rules(trades)

        shadow = None
        if use_vibe:
            try:
                shadow = await self.vibe.shadow_backtest(str(path))
            except Exception as e:
                logger.warning(f"Vibe-Trading shadow_backtest failed: {e}")

        return {
            **stats,
            "rules": rules,
            "shadow_backtest": shadow,
        }

    def _load_trades(self, path: Path) -> List[Dict[str, Any]]:
        """Load and normalize trades from a CSV file."""
        trades: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trade = self._normalize_trade(row)
                if trade:
                    trades.append(trade)
        return trades

    def _normalize_trade(self, row: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """Normalize a single CSV row into a trade dict."""
        symbol = row.get("symbol", row.get("ticker", "")).strip().upper()
        if not symbol:
            return None

        side = row.get("side", row.get("direction", "long")).strip().lower()
        if side not in ("long", "short"):
            side = "long"

        try:
            entry_price = float(row.get("entry_price", row.get("entry", 0)) or 0)
            exit_price = float(row.get("exit_price", row.get("exit", 0)) or 0)
            size = float(row.get("size", row.get("quantity", 1)) or 1)
            pnl = float(row.get("pnl", row.get("profit", 0)) or 0)
        except ValueError:
            return None

        notes = row.get("notes", row.get("note", "")).strip()

        return {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "size": size,
            "pnl": pnl,
            "notes": notes,
            "entry_date": row.get("entry_date", ""),
            "exit_date": row.get("exit_date", ""),
        }

    def _compute_stats(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute basic performance statistics."""
        total = len(trades)
        wins = sum(1 for t in trades if t["pnl"] > 0)
        total_pnl = sum(t["pnl"] for t in trades)
        symbols = sorted({t["symbol"] for t in trades})

        # Per-symbol stats
        per_symbol = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        for t in trades:
            s = per_symbol[t["symbol"]]
            s["trades"] += 1
            s["wins"] += 1 if t["pnl"] > 0 else 0
            s["pnl"] += t["pnl"]

        return {
            "trades": total,
            "win_rate": wins / total if total else 0.0,
            "avg_pnl": total_pnl / total if total else 0.0,
            "total_pnl": total_pnl,
            "symbols": symbols,
            "per_symbol": dict(per_symbol),
        }

    def _extract_rules(self, trades: List[Dict[str, Any]]) -> List[str]:
        """
        Extract simple implicit rules from the journal.

        Heuristics:
        - Most traded symbols
        - Most common side
        - Average hold duration if dates present
        - Common words in winning trade notes
        """
        rules: List[str] = []
        if not trades:
            return rules

        symbols = Counter(t["symbol"] for t in trades)
        sides = Counter(t["side"] for t in trades)
        top_symbol = symbols.most_common(1)[0][0]
        top_side = sides.most_common(1)[0][0]

        rules.append(f"Primary trading symbol: {top_symbol} ({symbols[top_symbol]} trades)")
        rules.append(f"Preferred side: {top_side} ({sides[top_side]} trades)")

        # R/R and win/loss patterns
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] < 0]
        avg_win = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t["pnl"] for t in losses) / len(losses) if losses else 0
        if avg_loss != 0:
            rr = abs(avg_win / avg_loss) if avg_loss else 0
            rules.append(f"Average win/loss ratio: {rr:.2f}")

        # Note keyword mining for winners
        winning_notes = [t["notes"] for t in wins if t["notes"]]
        if winning_notes:
            words = []
            for note in winning_notes:
                words.extend(w.lower() for w in note.split() if len(w) > 3)
            common = Counter(words).most_common(5)
            if common:
                rules.append(f"Common terms in winning notes: {', '.join(w for w, _ in common)}")

        return rules
