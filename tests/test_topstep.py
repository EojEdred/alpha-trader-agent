"""Unit tests for tools/topstep.py guardrails.

These tests verify the safety layer without touching live TopstepX accounts.
Run on the VPS where project-x-py is installed.
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure we load a controlled env for tests
os.environ["PROJECT_X_API_KEY"] = "test-key"
os.environ["PROJECT_X_USERNAME"] = "test-user"
os.environ["PROJECT_X_ACCOUNT_NAME"] = "TEST-ACCT"

from tools.topstep import TopstepClient, TopstepSafetyError


class DummyAccount:
    id = 12345
    name = "TEST-ACCT"
    balance = 50000.0
    canTrade = True


class DummyOrderResp:
    def __init__(self, order_id=999, success=True, error_code=0, error_message=None):
        self.orderId = order_id
        self.success = success
        self.errorCode = error_code
        self.errorMessage = error_message


class TestTopstepSafety(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TopstepClient()
        # Force safety defaults
        self.client.trading_enabled = False
        self.client.dry_run = False
        self.client.require_confirmation = True
        self.client.max_contracts = 2

    async def test_trading_disabled_blocks_order(self):
        with patch.object(self.client, "_ensure_client", new=AsyncMock(return_value=MagicMock())):
            result = await self.client.place_order("NQ", 1, "buy", confirmed=True)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("DISABLED", result["error"])

    async def test_confirmation_required_blocks_order(self):
        self.client.trading_enabled = True
        with patch.object(self.client, "_ensure_client", new=AsyncMock(return_value=MagicMock())):
            result = await self.client.place_order("NQ", 1, "buy", confirmed=False)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("confirmation required", result["error"].lower())

    async def test_dry_run_returns_simulated(self):
        self.client.trading_enabled = True
        self.client.dry_run = True
        self.client.require_confirmation = False
        with patch.object(
            self.client, "_ensure_client", new=AsyncMock(return_value=MagicMock())
        ), patch.object(
            self.client, "check_combine_compliance", new=AsyncMock(return_value={"compliant": True})
        ), patch.object(
            self.client, "_get_contract_id", new=AsyncMock(return_value="CON.F.US.ENQ.U26")
        ):
            result = await self.client.place_order("NQ", 2, "long", confirmed=False)
        self.assertEqual(result["status"], "simulated")
        self.assertEqual(result["side"], "LONG")

    async def test_side_mapping(self):
        self.assertEqual(self.client._normalize_side("buy"), self.client._normalize_side("long"))
        self.assertEqual(self.client._normalize_side("sell"), self.client._normalize_side("short"))
        with self.assertRaises(TopstepSafetyError):
            self.client._normalize_side("invalid")

    async def test_position_sizing_blocks_add_on(self):
        current = {"side": "long", "size": 2}
        with self.assertRaises(TopstepSafetyError):
            self.client._check_position_sizing("NQ", "buy", 1, current)

    async def test_position_sizing_blocks_reversal(self):
        current = {"side": "long", "size": 1}
        with self.assertRaises(TopstepSafetyError):
            self.client._check_position_sizing("NQ", "sell", 1, current)

    async def test_position_sizing_allows_flat(self):
        current = {"side": None, "size": 0}
        total = self.client._check_position_sizing("NQ", "buy", 2, current)
        self.assertEqual(total, 2)

    async def test_bracket_blocked_when_trading_disabled(self):
        with patch.object(self.client, "_ensure_client", new=AsyncMock(return_value=MagicMock())):
            result = await self.client.place_bracket_order(
                "NQ", 1, "buy", stop_loss=29000, take_profit=29500, confirmed=True
            )
        self.assertEqual(result["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
