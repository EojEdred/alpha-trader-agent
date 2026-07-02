"""
Agent Brain - CLI-based Inference and Reasoning Engine

This module converts raw tool data into trading theses using
CLI wrappers for Kimi, Codex, and Gemini.
"""

import os
import json
import asyncio
import subprocess
import shutil
from datetime import datetime
from typing import Dict, List, Any, Optional
from loguru import logger
from dotenv import load_dotenv

try:
    import aiohttp
except Exception:  # pragma: no cover
    aiohttp = None

# Load environment variables
load_dotenv()

# AI / Inference Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "kimi-cli")  # "kimi-cli", "codex-cli", "gemini-cli"

# ─── CLI WRAPPERS ───

class KimiCLIWrapper:
    """Wrapper for the Kimi Code CLI (kimi) or legacy kimi-cli subprocess."""
    async def ainvoke(self, messages: list, **kwargs) -> "_SimpleCompletion":
        prompt = "\n\n".join(m.content for m in messages if hasattr(m, "content"))
        text = await self._run(prompt)
        return _SimpleCompletion(completion=text)

    async def _run(self, prompt: str) -> str:
        exe = os.getenv("KIMI_CLI_PATH")
        if not exe:
            exe = shutil.which("kimi") or shutil.which("kimi-cli")
        if not exe:
            raise RuntimeError("kimi CLI not found in PATH (set KIMI_CLI_PATH)")
        # The TypeScript `kimi` binary uses different flags than the legacy Python `kimi-cli`.
        is_ts = os.path.basename(exe) == "kimi"
        if is_ts:
            args = [exe, "-p", prompt, "--output-format", "text"]
        else:
            args = [exe, "--quiet", "-p", prompt]
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"kimi CLI failed: {err}")
        text = stdout.decode("utf-8", errors="replace")
        # Strip session resume footer printed by both binaries
        if "To resume this session:" in text:
            text = text.split("To resume this session:")[0].strip()
        # The TypeScript `kimi` prints reasoning bullets followed by a final answer bullet.
        # Grab the content of the last bullet as the actual response.
        if is_ts:
            text = text.strip()
            if "\n• " in text:
                text = text.split("\n• ")[-1].strip()
            if text.startswith("• "):
                text = text[2:].strip()
        return text.strip()


class CodexCLIWrapper:
    """Wrapper for codex CLI subprocess."""
    async def ainvoke(self, messages: list, **kwargs) -> "_SimpleCompletion":
        prompt = "\n\n".join(m.content for m in messages if hasattr(m, "content"))
        text = await self._run(prompt)
        return _SimpleCompletion(completion=text)

    async def _run(self, prompt: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "codex", "exec", "--skip-git-repo-check", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=b"\n"), timeout=120)
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"codex CLI failed: {err}")
        text = stdout.decode("utf-8", errors="replace").strip()
        # Codex may write metadata to stderr; response is usually in stdout
        # If stdout is empty, try extracting from stderr
        if not text:
            text = stderr.decode("utf-8", errors="replace")
            lines = text.split("\n")
            result_lines = []
            in_result = False
            for line in lines:
                if line.strip() == "codex":
                    in_result = True
                    continue
                if in_result and line.strip().startswith("tokens used"):
                    break
                if in_result:
                    result_lines.append(line)
            text = "\n".join(result_lines).strip()
        return text


class GeminiCLIWrapper:
    """Wrapper for gemini CLI subprocess."""
    async def ainvoke(self, messages: list, **kwargs) -> "_SimpleCompletion":
        prompt = "\n\n".join(m.content for m in messages if hasattr(m, "content"))
        text = await self._run(prompt)
        return _SimpleCompletion(completion=text)

    async def _run(self, prompt: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "gemini", "-p", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"gemini CLI failed: {err}")
        return stdout.decode("utf-8", errors="replace").strip()


class _SimpleCompletion:
    """Minimal completion object."""
    def __init__(self, completion: str):
        self.completion = completion
        self.usage = None
        self.thinking = None
        self.redacted_thinking = None
        self.stop_reason = None


class KimiAPIWrapper:
    """Direct OpenAI-compatible Kimi/Moonshot API wrapper.

    Uses env vars:
      KIMI_API_KEY / MOONSHOT_API_KEY - required
      KIMI_API_BASE - default https://api.moonshot.ai/v1
      KIMI_API_MODEL - default kimi-k2
    """

    async def ainvoke(self, messages: list, **kwargs) -> "_SimpleCompletion":
        if aiohttp is None:
            raise RuntimeError("aiohttp is not installed")
        api_key = os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")
        if not api_key:
            raise RuntimeError("KIMI_API_KEY / MOONSHOT_API_KEY not set")
        base_url = (os.getenv("KIMI_API_BASE") or "https://api.moonshot.ai/v1").rstrip("/")
        model = os.getenv("KIMI_API_MODEL", "kimi-k2")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "temperature": float(os.getenv("KIMI_API_TEMPERATURE", "0.3")),
        }
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/chat/completions", headers=headers, json=payload, timeout=timeout
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return _SimpleCompletion(completion=content.strip())


# ─── UNIVERSAL BRAIN CALLER ───

async def _try_provider(provider: str, prompt: str, system_instruction: str) -> str:
    """Try a single provider and return its response text."""
    if provider == "kimi-api":
        wrapper = KimiAPIWrapper()
        messages: List[Dict[str, str]] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        response = await wrapper.ainvoke(messages)
    else:
        full_prompt = f"{system_instruction}\n\n{prompt}".strip()
        if provider == "codex-cli":
            wrapper = CodexCLIWrapper()
        elif provider == "gemini-cli":
            wrapper = GeminiCLIWrapper()
        else:
            wrapper = KimiCLIWrapper()
        response = await wrapper.ainvoke([type("Msg", (), {"content": full_prompt})()])

    text = response.completion if hasattr(response, "completion") else str(response)
    logger.debug(f"🧠 Brain ({provider}) raw response ({len(text)} chars)")
    return text


async def call_brain(prompt: str, system_instruction: str = "") -> str:
    """Universal wrapper to call the brain via CLI/API with fallback."""
    providers = [LLM_PROVIDER]
    if LLM_PROVIDER != "kimi-api" and (os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")):
        providers.append("kimi-api")
    if LLM_PROVIDER not in ("kimi", "kimi-cli"):
        providers.extend(["kimi", "kimi-cli"])
    if LLM_PROVIDER != "codex-cli":
        providers.append("codex-cli")

    last_error = ""
    for provider in providers:
        try:
            text = await _try_provider(provider, prompt, system_instruction)
            if text and text.strip():
                return text
        except Exception as e:
            last_error = str(e)
            logger.warning(f"🧠 Brain ({provider}) failed: {e}")

    logger.error(f"🧠 Brain all providers failed. Last error: {last_error}")
    return ""


# ─── TRADING PERSONA ───

TRADING_PERSONA_PROMPT = """You are Dexter, a conservative NQ futures scalper using LIVE TopstepX data. We are passing a $50K Topstep combine and need ONLY $1,500/day for 2 days. Small, consistent wins. No home runs. Analyze the data and return ONLY a JSON object with no markdown, no code blocks, no extra text:
{"symbol":"SYMBOL","direction":"long|short|none","trade_type":"intraday","score":0-100,"thesis":"concise reasoning","risks":["risk1"],"stop_loss":0.0,"take_profit":0.0,"hold_guidance":"ride|scalp"}

Rules:
- Score > 60 = trade. Score < 45 = no trade. Direction = none if uncertain. Higher bar = safer.
- CONSERVATIVE COMBINE PASS: We trade exactly 1 contract MAX. Risk = $160 per trade.
- For NQ futures: 1 point = $20 per contract. 1 contract = $20/point.
- stop_loss = 8 points max ($160 total risk). ABSOLUTE price level below/above entry.
- take_profit = 12 points ($240 gain on 1 contract). Close ALL at target — no runners.
- Time exit: 30 minutes max. If not profitable in 30 min, exit.
- If down $1,800 total for the day, STOP completely. No more trades.
- If up $1,500 for the day, STOP. We passed. Don't get greedy.
- Only trade when there's a clear trend (price above/below SMA20 with expanding range and confirming volume).
- Chop/no-trend = no trade (direction = none).
- Be decisive but patient. Better to miss a trade than take a bad one.
- NO REVERSALS. If stop hits, we walk away. Reversals add risk.
- If direction = none, stop_loss and take_profit can be 0."""


OPTIONS_TRADING_PERSONA_PROMPT = """You are Dexter, a conservative morning-session options trader on SPY, QQQ, and TSLA. You ONLY trade the 9:28 AM pre-market gap — one shot at the open, then done. ATM/ITM only. NO OTM. Analyze the data and return ONLY a JSON object with no markdown, no code blocks, no extra text:
{"underlying":"SPY","direction":"long|short|none","option_type":"call|put","strike":0.0,"expiration":"YYYY-MM-DD","max_entry_price":0.0,"score":0-100,"thesis":"concise reasoning","risks":["risk1"],"stop_loss":0.0,"take_profit":0.0,"time_decay_risk":"...","momentum_assessment":"strong|moderate|weak","hold_guidance":"scalp|partial_then_ride|hold_runner"}

Rules:
- Score > 45 = trade. Score < 35 = no trade. Direction = none if uncertain.
- PRE-MARKET GAP ENTRY ONLY (9:28 AM ET): One entry, then done for the day.
- If gap < 0.30%: NO TRADE. Chop day, skip entirely.
- DELTA HARD RULE: 0.50-0.70 delta ONLY. ATM or slight ITM. NO OTM — theta will kill you.
  - If the best available delta is < 0.50, direction = none. Do NOT compromise on this.
  - If delta > 0.70, that's fine (deep ITM), but entry cost may be high — check max_entry_price.
- Use 0DTE (today's expiration). Time decay is manageable at 9:30, deadly after 10 AM.
- max_entry_price = mid-price (bid+ask)/2. NEVER above ask.
- A $0.40 option move = $40 P&L per contract. Target: $0.40-0.80 move, then exit.

CRITICAL: The "option_chain" field in the input data contains the actual strikes, bid/ask, delta, theta, and volume. You MUST use this data to pick the strike. Do NOT say the option chain is missing.

EXIT STRATEGY:
- stop_loss = entry minus $0.30 (hard stop, -$30 per contract).
- take_profit_1 = entry + $0.40 (sell 50%, move stop to breakeven + $0.02).
- take_profit_2 = entry + $0.80 (sell 25% more, close remaining).
- NO RUNNERS. Close everything by +$0.80 or 20 minutes max.
- If momentum fades after 15 min: exit everything, even if slightly green.
- NEVER let a winner turn red. Breakeven stop after first partial is mandatory.
- If RSI > 70 on calls or < 30 on puts at open, score drops 10 (gap may retrace).
- direction = none if: chop/no gap, price hovering at VWAP, wide spreads, no volume, or delta < 0.50.
- Be decisive at 9:28. The best moves happen in the first 15 minutes. Don't hesitate, but if gap is weak, skip."""


DEXTER_CHAT_PERSONA_PROMPT = """You are Dexter, the Alpha Trader AI assistant. You are direct, concise, and speak like a seasoned trader.

Your job is to help the user understand the trading system, interpret market data, and make decisions. You have access to the live Alpha Trader dashboard state: mode, active venues, open positions, recent trades, risk snapshot, scheduled agents, and system logs.

Guidelines:
- Keep answers short and actionable (1-4 paragraphs unless asked for detail).
- When the user asks about status, trades, positions, or risk, use the provided context rather than making up numbers.
- If you don't have enough context, say so and suggest what to check.
- Avoid financial advice disclaimers unless the user asks for personal investment advice.
- Use trader terminology: entries, stops, targets, risk/reward, sessions, liquidity sweeps, etc.
- If the system is in dry-run mode, remind the user that no real orders are being sent.
- If a command is available in the dashboard (start, pause, stop, approve, reject, run workflow), tell the user they can use the Control tab or type the command here."""


# ─── INFERENCE FUNCTIONS ───

async def fetch_recent_learnings(limit: int = 5) -> str:
    """
    Fetch the most recent learning lessons from the audit database.
    """
    import sqlite3
    from pathlib import Path
    db_path = Path(__file__).parent.parent / "data" / "audit" / "audit.db"
    
    if not db_path.exists():
        return "No past learnings found."
        
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT details FROM audit_log 
            WHERE action = 'memory_update' 
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return "No specific lessons learned yet."
            
        learnings = []
        for (details_json,) in rows:
            details = json.loads(details_json)
            lesson = details.get('learnings', {}).get('learning_lesson', "Continue following core strategy.")
            learnings.append(f"- {lesson}")
            
        return "\n".join(learnings)
    except Exception as e:
        logger.error(f"Error fetching learnings: {e}")
        return "Error retrieving memory."


async def reason_about_setup(
    symbol: str,
    market_data: Dict = None,
    ohlcv_data: List[Dict] = None,
    volume_profile: Dict = None,
    order_flow: Dict = None,
    technicals: Dict = None,
    pdt_status: bool = True,
    **kwargs
) -> Dict:
    """
    Primary inference node. Uses CLI LLM to synthesize tool data into a trade decision.
    Includes memory injection for learning and a daily-chart reversal read.
    """
    logger.info(f"🧠 Brain ({LLM_PROVIDER}) performing inference for {symbol}")

    past_learnings = await fetch_recent_learnings()

    # Limit OHLCV to last 5 candles to avoid massive prompts
    recent_ohlcv = ohlcv_data[-5:] if ohlcv_data else []

    # Daily-chart reversal pattern (e.g., 3 red days + support test)
    daily_signal = {"signal": "neutral", "confidence": 0}
    try:
        from tools.market_data import fetch_ohlcv
        from tools.analysis import detect_daily_reversal_pattern
        daily_ohlcv = await fetch_ohlcv(symbol, timeframe="1d", limit=20)
        daily_signal = detect_daily_reversal_pattern(daily_ohlcv)
    except Exception as e:
        logger.debug(f"Daily chart signal fetch failed for {symbol}: {e}")

    context = {
        "symbol": symbol,
        "current_time": datetime.utcnow().isoformat(),
        "recent_candles": recent_ohlcv,
        "latest_price": recent_ohlcv[-1] if recent_ohlcv else {},
        "technicals": technicals,
        "daily_chart_signal": daily_signal,
        "past_learnings": past_learnings,
    }

    try:
        response_text = await call_brain(
            prompt=f"Analyze this data for {symbol}:\n{json.dumps(context, indent=2, default=str)}",
            system_instruction=TRADING_PERSONA_PROMPT
        )

        if not response_text:
            raise ValueError("Empty response from CLI")

        # Clean markdown fences
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("\n", 1)[1] if "\n" in clean_text else clean_text
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3].strip()
            if clean_text.startswith("json"):
                clean_text = clean_text[4:].strip()

        decision = json.loads(clean_text)
        logger.info(f"🧠 Brain Decision: {decision.get('symbol')} - {decision.get('direction')} (Score: {decision.get('score')})")
        
        # Notify via Telegram
        from tools.delivery import send_telegram
        score = decision.get('score', 0)
        if score > 60:
            msg = f"🧠 *{LLM_PROVIDER.upper()} Thought: {symbol}*\n"
            msg += f"*Direction:* {decision.get('direction').upper()}\n"
            msg += f"*Score:* {score}/100\n"
            msg += f"*Thesis:* {decision.get('thesis')}"
            asyncio.create_task(send_telegram(message=msg))
        
        return decision

    except Exception as e:
        logger.error(f"🧠 Brain inference failed: {e}")
        return {
            "symbol": symbol,
            "direction": "none",
            "score": 0,
            "trade_type": "intraday",
            "thesis": f"Inference failed: {str(e)}",
            "grade": "NO_TRADE"
        }


async def reason_about_options_setup(
    symbol: str,
    ohlcv_data: List[Dict] = None,
    technicals: Dict = None,
    option_chain: Dict = None,
    **kwargs
) -> Dict:
    """
    Options-specific inference node. Uses CLI LLM to pick strike, expiration, entry price.
    """
    logger.info(f"🧠 Brain ({LLM_PROVIDER}) performing OPTIONS inference for {symbol}")

    past_learnings = await fetch_recent_learnings()

    recent_ohlcv = ohlcv_data[-5:] if ohlcv_data else []
    
    # Daily-chart reversal pattern
    daily_signal = {"signal": "neutral", "confidence": 0}
    try:
        from tools.market_data import fetch_ohlcv
        from tools.analysis import detect_daily_reversal_pattern
        daily_ohlcv = await fetch_ohlcv(symbol, timeframe="1d", limit=20)
        daily_signal = detect_daily_reversal_pattern(daily_ohlcv)
    except Exception as e:
        logger.debug(f"Daily chart signal fetch failed for {symbol}: {e}")

    context = {
        "underlying": symbol,
        "current_time": datetime.utcnow().isoformat(),
        "recent_candles": recent_ohlcv,
        "latest_price": recent_ohlcv[-1] if recent_ohlcv else {},
        "technicals": technicals,
        "option_chain": option_chain,
        "daily_chart_signal": daily_signal,
        "past_learnings": past_learnings,
    }

    try:
        response_text = await call_brain(
            prompt=f"Analyze this options data for {symbol}:\n{json.dumps(context, indent=2, default=str)}",
            system_instruction=OPTIONS_TRADING_PERSONA_PROMPT
        )

        if not response_text:
            raise ValueError("Empty response from CLI")

        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("\n", 1)[1] if "\n" in clean_text else clean_text
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3].strip()
            if clean_text.startswith("json"):
                clean_text = clean_text[4:].strip()

        decision = json.loads(clean_text)
        logger.info(f"🧠 Brain Options Decision: {decision.get('underlying')} {decision.get('option_type')} {decision.get('direction')} (Score: {decision.get('score')})")
        
        from tools.delivery import send_telegram
        score = decision.get('score', 0)
        if score > 60:
            msg = f"🧠 *Options Signal: {symbol}*\n"
            msg += f"*{decision.get('option_type', '').upper()} {decision.get('direction', '').upper()}*\n"
            msg += f"*Strike:* {decision.get('strike')} | *Score:* {score}/100\n"
            msg += f"*Thesis:* {decision.get('thesis', '')}"
            asyncio.create_task(send_telegram(message=msg))
        
        return decision

    except Exception as e:
        logger.error(f"🧠 Brain options inference failed: {e}")
        return {
            "underlying": symbol,
            "direction": "none",
            "score": 0,
            "option_type": "call",
            "strike": 0,
            "expiration": "",
            "max_entry_price": 0,
            "thesis": f"Inference failed: {str(e)}",
            "time_decay_risk": ""
        }


async def deep_research_critique(
    symbol: str,
    brain_decision: Dict,
    ohlcv_data: Optional[List[Dict]] = None,
    technicals: Optional[Dict] = None,
    **kwargs
) -> Dict:
    """
    Red Team / Deep Research Node using CLI LLM.
    """
    logger.info(f"🧠 Brain ({LLM_PROVIDER}) performing deep research critique for {symbol}")

    # Safety gate: if the orchestrator failed to pass market data, reject rather
    # than allow a live trade on an incomplete critique.
    if ohlcv_data is None or technicals is None:
        logger.warning(
            f"Deep research critique for {symbol} missing required market data; rejecting trade"
        )
        return {
            "rating": 3,
            "critique": "Missing OHLCV or technicals — cannot perform a robust critique.",
            "hidden_risks": ["Insufficient market data supplied to research node"],
            "verdict": "REJECT",
            "suggested_adjustment": "Re-run the workflow with complete OHLCV and technical context.",
        }

    critique_prompt = f"""
    You are the "Head of Research" at a top-tier hedge fund reviewing a trade proposal.
    Your job is to be the ultimate skeptic. Find reasons WHY this trade will fail.
    
    TRADE PROPOSAL:
    {json.dumps(brain_decision, indent=2)}
    
    MARKET CONTEXT (Technicals):
    {json.dumps(technicals, indent=2)}
    
    RESEARCH TASKS:
    1. Check for "Bull/Bear Traps" at the current levels.
    2. Analyze the risk of "Liquidity Grabs" near the POC/VA edges.
    3. Evaluate if the trend is overextended (look at RSI and distance from SMA20).
    4. Consider the macro context: Is this a high-volatility environment?
    
    CRITIQUE REQUIREMENTS:
    - Rate the proposal from 1-10 (1 = reckless, 10 = bulletproof).
    - Identify at least 3 hidden risks.
    - Provide a definitive verdict: APPROVE, REJECT, or CAUTION.
    - Suggest a refined entry/exit plan. 
    
    RESPONSE FORMAT (JSON ONLY):
    {{
      "rating": 8,
      "critique": "Detailed critical feedback",
      "hidden_risks": ["Risk 1", "Risk 2", "Risk 3"],
      "verdict": "APPROVE|REJECT|CAUTION",
      "suggested_adjustment": "Refined strategy details"
    }}
    """

    try:
        response_text = await call_brain(
            prompt=critique_prompt,
            system_instruction=""
        )
        clean_text = response_text.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("\n", 1)[1] if "\n" in clean_text else clean_text
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3].strip()
            if clean_text.startswith("json"):
                clean_text = clean_text[4:].strip()
        return json.loads(clean_text)
    except Exception as e:
        logger.error(f"Deep research critique failed: {e}")
        return {
            "rating": 5,
            "critique": f"Critique failed: {str(e)}",
            "hidden_risks": ["Unable to analyze"],
            "verdict": "CAUTION",
            "suggested_adjustment": "Manual review required"
        }


# ─── STANDALONE WRAPPERS FOR ORCHESTRATOR ───

async def risk_governor(
    scalp_decision: Dict = None,
    compliance_status: Dict = None,
    **kwargs
) -> Dict:
    """
    Risk Governor - validates trade decisions against prop firm rules.
    Standalone wrapper for orchestrator.
    """
    if not scalp_decision:
        return {"approved": False, "reason": "No decision provided"}
    
    direction = scalp_decision.get("direction", "none")
    score = scalp_decision.get("score", 0)
    
    # Basic validation — CONSERVATIVE: score must be > 60
    if direction == "none" or score < 60:
        return {"approved": False, "reason": f"Score {score} too low or direction is none"}
    
    # Prop firm constraints — read from env so they stay aligned with .env / YAML
    max_contracts = int(os.getenv("TOPSTEP_MAX_CONTRACTS", 1))
    max_daily_loss = float(os.getenv("TOPSTEP_MAX_DAILY_LOSS", 1800))
    
    # Check compliance
    if compliance_status and not compliance_status.get("can_trade", True):
        return {"approved": False, "reason": "Compliance check failed"}
    
    return {
        "approved": True,
        "reason": f"Direction: {direction}, Score: {score}",
        "max_contracts": max_contracts,
        "max_daily_loss": max_daily_loss,
        "stop_loss": scalp_decision.get("stop_loss") if scalp_decision else None,
        "take_profit": scalp_decision.get("take_profit") if scalp_decision else None,
    }


async def options_risk_governor(
    options_decision: Dict = None,
    compliance_status: Dict = None,
    current_positions: List[Dict] = None,
    **kwargs
) -> Dict:
    """
    Options Risk Governor - validates options trade decisions.
    """
    if not options_decision:
        return {"approved": False, "reason": "No decision provided"}
    
    direction = options_decision.get("direction", "none")
    score = options_decision.get("score", 0)
    max_entry = options_decision.get("max_entry_price", 0)
    
    if direction == "none" or score < 45:
        return {"approved": False, "reason": f"Score {score} too low or direction is none"}
    
    if max_entry <= 0:
        return {"approved": False, "reason": "Invalid max_entry_price"}
    
    # Options constraints — CONSERVATIVE
    max_contracts = 2
    max_position_cost = 500  # Max $500 per position (premium * 100 * contracts)
    
    # HARD DELTA CHECK: reject if brain picked OTM (delta < 0.50)
    # Note: delta is not always in the decision, but if it is, enforce it
    selected_delta = options_decision.get("delta", 0)
    if selected_delta and selected_delta < 0.50:
        return {"approved": False, "reason": f"Delta {selected_delta} < 0.50 — OTM rejected"}
    
    # Check compliance
    if compliance_status and not compliance_status.get("can_trade", True):
        return {"approved": False, "reason": "Compliance check failed"}
    
    # Check position limits
    option_count = 0
    if current_positions:
        option_count = sum(1 for p in current_positions if p.get("asset_type") == "OPTION")
    
    if option_count >= 2:
        return {"approved": False, "reason": "Max 2 concurrent option positions reached"}
    
    return {
        "approved": True,
        "reason": f"Options {direction} approved. Score: {score}",
        "max_contracts": max_contracts,
        "max_position_cost": max_position_cost,
        "stop_loss": options_decision.get("stop_loss") if options_decision else None,
        "take_profit": options_decision.get("take_profit") if options_decision else None,
        "max_entry_price": max_entry,
    }
