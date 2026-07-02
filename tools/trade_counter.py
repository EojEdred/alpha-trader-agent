"""
Daily Trade Counter

Tracks trade counts per venue per day for prop firm compliance.
Some prop firms enforce max trades per day (e.g., 30 trades).
"""

import sqlite3
from typing import Dict, Optional
from datetime import datetime, date
from pathlib import Path
from loguru import logger


class TradeCounter:
    """
    SQLite-backed daily trade counter.
    
    Usage:
        counter = TradeCounter()
        if counter.can_trade("topstep"):
            counter.record_trade("topstep")
            # Execute trade
    """
    
    DEFAULT_MAX_TRADES = {
        "topstep": 30,
        "apex": 30,
        "leeloo": 30,
        "oanda": 999999,  # No limit
        "schwab": 999999,
        "kalshi": 999999,
    }
    
    def __init__(self, db_path: str = "data/trade_counter.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_trades (
                    venue TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    trade_count INTEGER DEFAULT 0,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (venue, trade_date)
                )
            """)
            conn.commit()
    
    def _today(self) -> str:
        """Return today's date as string in ET."""
        import pytz
        et = pytz.timezone("US/Eastern")
        return datetime.now(et).strftime("%Y-%m-%d")
    
    def get_count(self, venue: str) -> int:
        """Get today's trade count for a venue."""
        venue = venue.lower()
        today = self._today()
        
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT trade_count FROM daily_trades WHERE venue = ? AND trade_date = ?",
                (venue, today)
            ).fetchone()
            
            return row[0] if row else 0
    
    def get_max_trades(self, venue: str) -> int:
        """Get max trades allowed for a venue."""
        return self.DEFAULT_MAX_TRADES.get(venue.lower(), 999999)
    
    def can_trade(self, venue: str) -> bool:
        """Check if venue has remaining trade quota for today."""
        venue = venue.lower()
        count = self.get_count(venue)
        max_trades = self.get_max_trades(venue)
        
        if count >= max_trades:
            logger.warning(f"Daily trade limit reached for {venue}: {count}/{max_trades}")
            return False
        
        return True
    
    def record_trade(self, venue: str, count: int = 1):
        """Record a trade for a venue."""
        venue = venue.lower()
        today = self._today()
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO daily_trades (venue, trade_date, trade_count)
                VALUES (?, ?, ?)
                ON CONFLICT(venue, trade_date) DO UPDATE SET
                    trade_count = trade_count + ?,
                    last_updated = CURRENT_TIMESTAMP
            """, (venue, today, count, count))
            conn.commit()
        
        new_count = self.get_count(venue)
        logger.info(f"Recorded trade for {venue}. Daily count: {new_count}")
    
    def get_all_counts(self) -> Dict[str, Dict]:
        """Get all venue counts for today."""
        today = self._today()
        
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT venue, trade_count FROM daily_trades WHERE trade_date = ?",
                (today,)
            ).fetchall()
        
        result = {}
        for venue, count in rows:
            max_trades = self.get_max_trades(venue)
            result[venue] = {
                "count": count,
                "max": max_trades,
                "remaining": max(0, max_trades - count),
                "limited": count >= max_trades,
            }
        
        return result
