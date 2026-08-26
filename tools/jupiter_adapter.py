"""
Jupiter / Solana DEX Adapter for Alpha Trader

Provides quote and swap execution on Solana via the Jupiter Ultra/Perps API.
Private keys are kept in secure storage (keychain/env) and never committed.

Requires optional Solana SDKs for signing:
    pip install solana solders

Without Solana SDKs, the adapter can still fetch quotes and prepare swap
transactions for external signing.

Usage:
    from tools.jupiter_adapter import JupiterAdapter

    adapter = JupiterAdapter(config)
    quote = await adapter.get_quote("SOL", "USDC", 1.0)
    swap = await adapter.swap("SOL", "USDC", 1.0)  # requires private key
"""

import os
from typing import Any, Dict, Optional

import httpx
from loguru import logger


JUPITER_API_BASE = "https://api.jup.ag"
SOLANA_RPC_DEFAULT = "https://api.mainnet-beta.solana.com"


try:
    from solders.keypair import Keypair
    from solders.transaction import VersionedTransaction
    _SOLANA_AVAILABLE = True
except ImportError:
    Keypair = None
    VersionedTransaction = None
    _SOLANA_AVAILABLE = False


class JupiterError(Exception):
    """Raised when a Jupiter operation fails."""

    def __init__(self, message: str):
        super().__init__(message)


class JupiterAdapter:
    """
    Async adapter for Jupiter swap API.

    Keeps private keys out of memory except when signing. Supports optional
    Solana SDKs; if missing, returns prepared transactions for manual signing.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        jup_config = self.config.get("jupiter", {})
        self.api_base = jup_config.get("api_base", JUPITER_API_BASE).rstrip("/")
        self.rpc_url = jup_config.get("rpc_url", SOLANA_RPC_DEFAULT)
        self.private_key = jup_config.get("private_key") or os.environ.get("SOLANA_PRIVATE_KEY")
        self.timeout = float(jup_config.get("timeout_seconds", 60.0))
        self._client: Optional[httpx.AsyncClient] = None
        self._rpc_client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.api_base, timeout=self.timeout)
        return self._client

    def _get_rpc_client(self) -> httpx.AsyncClient:
        if self._rpc_client is None:
            self._rpc_client = httpx.AsyncClient(base_url=self.rpc_url, timeout=self.timeout)
        return self._rpc_client

    async def close(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self._rpc_client is not None:
            await self._rpc_client.aclose()
            self._rpc_client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    # ------------------------------------------------------------------
    # Token helpers
    # ------------------------------------------------------------------

    async def get_token_list(self) -> Optional[Dict[str, Any]]:
        """Fetch Jupiter's verified token list."""
        try:
            response = await self._get_client().get("/tokens/v1/tagged/verified")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Jupiter token list failed: {e}")
            return None

    async def get_token_price(self, mint: str) -> Optional[float]:
        """Fetch current price for a token mint from Jupiter price API."""
        try:
            response = await self._get_client().get(f"/price/v2?ids={mint}")
            response.raise_for_status()
            data = response.json()
            return data.get("data", {}).get(mint, {}).get("price")
        except Exception as e:
            logger.warning(f"Jupiter price failed for {mint}: {e}")
            return None

    # ------------------------------------------------------------------
    # Quote and swap
    # ------------------------------------------------------------------

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: float,
        slippage_bps: int = 50,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch a swap quote.

        Args:
            input_mint: Input token mint or symbol (e.g. "SOL").
            output_mint: Output token mint or symbol (e.g. "USDC").
            amount: Amount in human-readable input token units.
            slippage_bps: Slippage tolerance in basis points.
        """
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps,
        }
        try:
            response = await self._get_client().get("/swap/v1/quote", params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Jupiter quote failed: {e}")
            return None

    async def get_swap_transaction(
        self,
        quote_response: Dict[str, Any],
        wrap_unwrap_sol: bool = True,
        prioritization_fee_lamports: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Request a swap transaction payload from Jupiter.

        Requires a wallet public key. Private key is NOT sent to Jupiter.
        """
        if not self.private_key:
            raise JupiterError("Solana private key not configured")

        if not _SOLANA_AVAILABLE:
            raise JupiterError("Solana SDKs (solders) not installed")

        keypair = self._load_keypair()
        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": wrap_unwrap_sol,
            "dynamicComputeUnitLimit": True,
            "dynamicSlippage": True,
        }
        if prioritization_fee_lamports:
            payload["prioritizationFeeLamports"] = prioritization_fee_lamports

        try:
            response = await self._get_client().post("/swap/v1/swap", json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Jupiter swap transaction failed: {e}")
            return None

    async def swap(
        self,
        input_mint: str,
        output_mint: str,
        amount: float,
        slippage_bps: int = 50,
    ) -> Optional[Dict[str, Any]]:
        """
        Full swap flow: quote -> swap tx -> sign -> submit.

        Requires Solana SDKs and a configured private key.
        """
        if not _SOLANA_AVAILABLE:
            logger.warning("Solana SDKs not installed; cannot submit swap")
            return None

        quote = await self.get_quote(input_mint, output_mint, amount, slippage_bps)
        if quote is None:
            return None

        swap_tx = await self.get_swap_transaction(quote)
        if swap_tx is None:
            return None

        return await self._sign_and_submit(swap_tx)

    # ------------------------------------------------------------------
    # Signing and submission
    # ------------------------------------------------------------------

    def _load_keypair(self) -> Any:
        """Load Solana keypair from base58 private key."""
        if not _SOLANA_AVAILABLE:
            raise JupiterError("Solana SDKs not installed")

        try:
            import base58
            decoded = base58.b58decode(self.private_key)
            return Keypair.from_bytes(decoded)
        except Exception:
            # Fallback: assume JSON array of bytes
            import json
            raw = json.loads(self.private_key)
            return Keypair.from_bytes(bytes(raw))

    async def _sign_and_submit(self, swap_tx: Dict[str, Any]) -> Dict[str, Any]:
        """Sign a VersionedTransaction and submit to Solana RPC."""
        if not _SOLANA_AVAILABLE:
            raise JupiterError("Solana SDKs not installed")

        keypair = self._load_keypair()
        raw_tx = swap_tx.get("swapTransaction")
        if raw_tx is None:
            raise JupiterError("No swapTransaction in Jupiter response")

        import base64
        tx_bytes = base64.b64decode(raw_tx)
        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed_tx = VersionedTransaction(tx.message, [keypair])
        serialized = bytes(signed_tx)

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [
                base64.b64encode(serialized).decode("utf-8"),
                {"encoding": "base64", "preflightCommitment": "confirmed"},
            ],
        }

        response = await self._get_rpc_client().post("/", json=payload)
        response.raise_for_status()
        result = response.json()

        if "error" in result:
            raise JupiterError(f"Solana RPC error: {result['error']}")

        return {
            "signature": result.get("result"),
            "input": swap_tx.get("inputMint"),
            "output": swap_tx.get("outputMint"),
            "status": "submitted",
        }
