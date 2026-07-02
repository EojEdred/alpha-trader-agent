"""
Configuration loader for Alpha Trader.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import yaml
import os
from dotenv import load_dotenv


@dataclass
class RiskLimits:
    max_position_pct: float = 5.0
    max_daily_loss_pct: float = 2.0
    max_open_positions: int = 10
    min_risk_reward: float = 2.0


@dataclass
class BrokerConfig:
    primary: str = "interactive_brokers"
    fallback: str = "schwab"
    ib_host: str = "127.0.0.1"
    ib_port: int = 7497
    ib_client_id: int = 1


@dataclass
class LLMConfig:
    provider: str = "openai"
    model: str = "gpt-4-turbo"
    fallback_model: str = "gpt-3.5-turbo"
    api_key: Optional[str] = None


@dataclass
class ScheduleConfig:
    research_cycle_cron: str = "0 4 * * *"  # 4 AM ET
    morning_report_cron: str = "0 6 * * *"  # 6 AM ET
    monitoring_interval_seconds: int = 300  # 5 minutes


@dataclass
class NotificationConfig:
    email_enabled: bool = True
    email_to: str = ""
    sms_enabled: bool = False
    sms_to: str = ""
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None


@dataclass
class Config:
    risk_limits: RiskLimits = field(default_factory=RiskLimits)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)

    # Watchlists
    options_watchlist: List[str] = field(default_factory=lambda: ["SPY", "QQQ", "TSLA"])
    futures_watchlist: List[str] = field(default_factory=lambda: ["ES", "NQ", "CL", "GC"])
    crypto_watchlist: List[str] = field(default_factory=lambda: ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    crypto_exchanges: List[str] = field(default_factory=lambda: ["binance", "coinbase"])

    # Paths
    data_dir: Path = field(default_factory=lambda: Path("data"))
    workflows_dir: Path = field(default_factory=lambda: Path("workflows"))
    tools_dir: Path = field(default_factory=lambda: Path("tools"))

    @classmethod
    def load(cls, config_path: str | Path) -> "Config":
        """Load configuration from YAML file."""
        config_path = Path(config_path)

        # Load .env file if exists
        env_path = config_path.parent / "secrets.env"
        if env_path.exists():
            load_dotenv(env_path)

        # Load YAML config
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        # Build config with defaults
        config = cls()

        # Override with file values
        if 'risk_limits' in data:
            config.risk_limits = RiskLimits(**data['risk_limits'])
        if 'broker' in data:
            config.broker = BrokerConfig(**data['broker'])
        if 'llm' in data:
            config.llm = LLMConfig(**data['llm'])
        if 'schedule' in data:
            config.schedule = ScheduleConfig(**data['schedule'])
        if 'notifications' in data:
            config.notifications = NotificationConfig(**data['notifications'])

        # Watchlists
        if 'watchlists' in data:
            wl = data['watchlists']
            if 'options' in wl:
                config.options_watchlist = wl['options']
            if 'futures' in wl:
                config.futures_watchlist = wl['futures']
            if 'crypto' in wl:
                config.crypto_watchlist = wl['crypto']

        # Override with environment variables
        config.llm.api_key = os.getenv('OPENAI_API_KEY', config.llm.api_key)
        config.notifications.twilio_account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        config.notifications.twilio_auth_token = os.getenv('TWILIO_AUTH_TOKEN')

        return config

    def save(self, config_path: str | Path):
        """Save configuration to YAML file."""
        config_path = Path(config_path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            'risk_limits': {
                'max_position_pct': self.risk_limits.max_position_pct,
                'max_daily_loss_pct': self.risk_limits.max_daily_loss_pct,
                'max_open_positions': self.risk_limits.max_open_positions,
            },
            'broker': {
                'primary': self.broker.primary,
                'fallback': self.broker.fallback,
            },
            'llm': {
                'provider': self.llm.provider,
                'model': self.llm.model,
            },
            'watchlists': {
                'options': self.options_watchlist,
                'futures': self.futures_watchlist,
                'crypto': self.crypto_watchlist,
            }
        }

        with open(config_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False)
