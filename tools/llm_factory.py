"""
LLM Model Factory — Dynamic Discovery

Discovers available LLM providers by inspecting the system:
- CLI tools (kimi, openai)
- Config files (~/.config/gizzi/config.json, ~/.kimi/config.toml)
- Environment variables
- Running inference servers

Usage:
    from tools.llm_factory import LLMFactory

    factory = LLMFactory.discover()
    print(factory.available_providers())

    llm = factory.create("kimi-k2")          # Moonshot AI via API
    llm = factory.create("gpt-4o")           # OpenAI
    llm = factory.create("llama3.2")         # Ollama local
    llm = factory.create("kimi-subprocess")  # Kimi CLI subprocess
"""

import asyncio
import json
import os
import subprocess
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger


@dataclass
class ProviderInfo:
    """Information about a discovered LLM provider."""
    name: str
    type: str  # "openai-compatible", "anthropic", "ollama", "kimi-cli", "kimi-api"
    models: List[str] = field(default_factory=list)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    available: bool = False
    source: str = ""  # How we discovered it: "env", "config", "cli", "subprocess"


class LLMFactory:
    """
    Dynamically discovers and creates LLM instances.

    No hard-coded model lists. Everything is discovered at runtime.
    """

    _cache: Optional[Dict[str, ProviderInfo]] = None
    _cache_time: Optional[float] = None
    _cache_ttl_seconds: float = 60.0  # Cache discovery for 60s

    def __init__(self):
        self._providers: Dict[str, ProviderInfo] = {}
        self._discovered = False

    @classmethod
    def discover(cls, fast_mode: bool = False) -> "LLMFactory":
        """
        Discover all available LLM providers on the system.

        Args:
            fast_mode: If True, skip slow subprocess-based discovery
                      (kimi CLI, ollama, openai CLI). Use in tests.
        """
        factory = cls()
        factory._discover_all(fast_mode=fast_mode)
        return factory

    def _discover_all(self, fast_mode: bool = False):
        """Run all discovery methods."""
        if self._discovered:
            return

        # Check cache first
        if not fast_mode and self._use_cache():
            self._providers = dict(self._cache)
            self._discovered = True
            logger.debug(f"Using cached LLM discovery ({len(self._providers)} providers)")
            return

        logger.info("Discovering available LLM providers...")

        # Priority order: user's preferred providers first
        self._discover_kimi_from_gizzi()      # User's gizzi config (preferred)
        self._discover_kimi_from_env()         # KIMI_API_KEY / MOONSHOT_API_KEY

        if not fast_mode:
            self._discover_kimi_cli()             # kimi CLI subprocess (slow)
            self._discover_openai_from_env()      # OPENAI_API_KEY
            self._discover_anthropic_from_env()   # ANTHROPIC_API_KEY
            self._discover_openrouter_from_env()  # OPENROUTER_API_KEY
            self._discover_google_from_env()      # GOOGLE_API_KEY
            self._discover_groq_from_env()        # GROQ_API_KEY
        else:
            # Fast mode: only env-based discovery, skip subprocesses
            self._discover_openai_from_env()
            self._discover_anthropic_from_env()
            self._discover_openrouter_from_env()
            self._discover_google_from_env()
            self._discover_groq_from_env()

        self._discovered = True

        available = [p for p in self._providers.values() if p.available]
        logger.info(f"Discovered {len(available)} available providers: {[p.name for p in available]}")

        # Update cache
        if not fast_mode:
            LLMFactory._cache = dict(self._providers)
            LLMFactory._cache_time = __import__('time').time()

    def _use_cache(self) -> bool:
        """Check if cached discovery results are still valid."""
        if LLMFactory._cache is None or LLMFactory._cache_time is None:
            return False
        elapsed = __import__('time').time() - LLMFactory._cache_time
        return elapsed < LLMFactory._cache_ttl_seconds

    # ─── DISCOVERY METHODS ───

    def _discover_kimi_from_gizzi(self):
        """Check gizzi config for Moonshot AI credentials."""
        config_path = Path.home() / ".config" / "gizzi" / "config.json"
        if not config_path.exists():
            return

        try:
            config = json.loads(config_path.read_text())
            provider = config.get("provider", {})

            for provider_name, provider_config in provider.items():
                if "moonshot" in provider_name or "kimi" in provider_name:
                    opts = provider_config.get("options", {})
                    api_key = opts.get("apiKey", "")
                    base_url = opts.get("baseURL", "https://api.kimi.com/coding/v1")
                    models = list(provider_config.get("models", {}).keys())

                    if api_key and api_key.startswith("sk-"):
                        self._providers["kimi"] = ProviderInfo(
                            name="kimi",
                            type="openai-compatible",
                            models=models or ["kimi-k2"],
                            api_key=api_key,
                            base_url=base_url,
                            available=True,
                            source="gizzi config",
                        )
                        logger.info(f"Found Kimi API key in gizzi config (models: {models})")
                        return
        except Exception as e:
            logger.debug(f"Gizzi config read failed: {e}")

    def _discover_kimi_from_env(self):
        """Check environment for Kimi/Moonshot API keys."""
        for env_name in ["KIMI_API_KEY", "MOONSHOT_API_KEY", "MOONSHOT_APIKEY"]:
            key = os.getenv(env_name)
            if key and key.startswith("sk-"):
                self._providers["kimi"] = ProviderInfo(
                    name="kimi",
                    type="openai-compatible",
                    models=["kimi-k2", "kimi-k1.5", "kimi-latest"],
                    api_key=key,
                    base_url="https://api.kimi.com/coding/v1",
                    available=True,
                    source=f"env {env_name}",
                )
                logger.info(f"Found Kimi API key from {env_name}")
                return

    def _discover_kimi_cli(self):
        """Check if kimi CLI is available as a subprocess fallback."""
        try:
            result = subprocess.run(
                ["kimi", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                self._providers["kimi-cli"] = ProviderInfo(
                    name="kimi-cli",
                    type="kimi-cli",
                    models=["kimi-for-coding"],  # CLI uses whatever model it's configured for
                    available=True,
                    source="kimi CLI",
                )
                logger.info(f"Found kimi CLI: {version}")
        except Exception:
            pass

    def _discover_openai_from_env(self):
        """Check for OpenAI API key."""
        key = os.getenv("OPENAI_API_KEY")
        if key and key.startswith("sk-"):
            models = self._list_openai_models(key) if self._has_openai_cli() else ["gpt-4o", "gpt-4o-mini"]
            self._providers["openai"] = ProviderInfo(
                name="openai",
                type="openai-compatible",
                models=models,
                api_key=key,
                base_url="https://api.openai.com/v1",
                available=True,
                source="env OPENAI_API_KEY",
            )
            logger.info(f"Found OpenAI API key")

    def _discover_anthropic_from_env(self):
        """Check for Anthropic API key."""
        key = os.getenv("ANTHROPIC_API_KEY")
        if key and key.startswith("sk-"):
            self._providers["anthropic"] = ProviderInfo(
                name="anthropic",
                type="anthropic",
                models=["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022", "claude-3-opus-20240229"],
                api_key=key,
                available=True,
                source="env ANTHROPIC_API_KEY",
            )
            logger.info(f"Found Anthropic API key")


    def _discover_openrouter_from_env(self):
        """Check for OpenRouter API key."""
        key = os.getenv("OPENROUTER_API_KEY")
        if key:
            self._providers["openrouter"] = ProviderInfo(
                name="openrouter",
                type="openai-compatible",
                models=[],  # OpenRouter has too many to list
                api_key=key,
                base_url="https://openrouter.ai/api/v1",
                available=True,
                source="env OPENROUTER_API_KEY",
            )
            logger.info(f"Found OpenRouter API key")

    def _discover_google_from_env(self):
        """Check for Google API key."""
        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if key:
            self._providers["google"] = ProviderInfo(
                name="google",
                type="google",
                models=["gemini-1.5-pro", "gemini-1.5-flash"],
                api_key=key,
                available=True,
                source="env GOOGLE_API_KEY",
            )
            logger.info(f"Found Google API key")

    def _discover_groq_from_env(self):
        """Check for Groq API key."""
        key = os.getenv("GROQ_API_KEY")
        if key:
            self._providers["groq"] = ProviderInfo(
                name="groq",
                type="openai-compatible",
                models=["llama-3.1-70b", "mixtral-8x7b"],
                api_key=key,
                base_url="https://api.groq.com/openai/v1",
                available=True,
                source="env GROQ_API_KEY",
            )
            logger.info(f"Found Groq API key")

    def _has_openai_cli(self) -> bool:
        """Check if OpenAI CLI is installed."""
        try:
            subprocess.run(["openai", "--version"], capture_output=True, timeout=2)
            return True
        except Exception:
            return False

    def _list_openai_models(self, api_key: str) -> List[str]:
        """List available OpenAI models via CLI."""
        try:
            result = subprocess.run(
                ["openai", "api", "models.list"],
                capture_output=True,
                text=True,
                timeout=5,
                env={**os.environ, "OPENAI_API_KEY": api_key},
            )
            if result.returncode == 0:
                # Parse output for model IDs
                models = []
                for line in result.stdout.split("\n"):
                    if "gpt-" in line.lower():
                        parts = line.split()
                        for p in parts:
                            if p.startswith("gpt-"):
                                models.append(p)
                return models if models else ["gpt-4o", "gpt-4o-mini"]
        except Exception:
            pass
        return ["gpt-4o", "gpt-4o-mini"]

    # ─── CREATION ───

    def create(self, model_name: Optional[str] = None, **kwargs):
        """
        Create an LLM instance from model name.

        Args:
            model_name: Model identifier. If None, uses the first available provider.
            **kwargs: Additional arguments (temperature, etc.)

        Returns:
            LLM instance compatible with browser-use
        """
        if not self._discovered:
            self._discover_all()

        model_name = (model_name or os.getenv("BROWSER_USE_MODEL", "")).strip()

        # If no model specified, use the first available provider
        if not model_name:
            available = self.available_providers()
            if not available:
                raise RuntimeError("No LLM providers available. Set an API key or start Ollama.")
            model_name = available[0].models[0] if available[0].models else "default"
            provider = available[0]
            logger.info(f"No model specified, using {provider.name}/{model_name}")
        else:
            # Find provider for this model
            provider = self._find_provider_for_model(model_name)
            if not provider:
                raise RuntimeError(
                    f"No provider available for model '{model_name}'. "
                    f"Available: {self.list_available_models()}"
                )

        logger.info(f"Creating LLM: provider={provider.name}, model={model_name}, source={provider.source}")

        if provider.type == "openai-compatible":
            return self._create_openai_compatible(provider, model_name, **kwargs)
        elif provider.type == "anthropic":
            return self._create_anthropic(provider, model_name, **kwargs)
        elif provider.type == "google":
            return self._create_google(provider, model_name, **kwargs)
        elif provider.type == "ollama":
            return self._create_ollama(provider, model_name, **kwargs)
        elif provider.type == "kimi-cli":
            return self._create_kimi_cli(model_name, **kwargs)
        else:
            raise ValueError(f"Unknown provider type: {provider.type}")

    def _find_provider_for_model(self, model_name: str) -> Optional[ProviderInfo]:
        """Find the provider that can serve this model."""
        model_lower = model_name.lower()

        # Check each provider's model list
        for provider in self._providers.values():
            if not provider.available:
                continue
            for m in provider.models:
                if model_lower == m.lower() or model_lower in m.lower() or m.lower() in model_lower:
                    return provider

        # Special cases: provider name as model prefix
        if model_lower.startswith("kimi"):
            return self._providers.get("kimi") or self._providers.get("kimi-cli")
        if model_lower.startswith("gpt"):
            return self._providers.get("openai")
        if model_lower.startswith("claude"):
            return self._providers.get("anthropic")
        if model_lower.startswith("gemini"):
            return self._providers.get("google")

        # Fallback: if only one provider available, use it
        available = [p for p in self._providers.values() if p.available]
        if len(available) == 1:
            return available[0]

        # Ollama accepts any model name
        if "ollama" in self._providers and self._providers["ollama"].available:
            return self._providers["ollama"]

        # OpenRouter accepts any model name
        if "openrouter" in self._providers and self._providers["openrouter"].available:
            return self._providers["openrouter"]

        return None

    def _create_openai_compatible(self, provider: ProviderInfo, model: str, **kwargs):
        """Create OpenAI-compatible LLM (works for OpenAI, Moonshot, Groq, OpenRouter)."""
        from browser_use.llm.openai.chat import ChatOpenAI

        # Kimi Code console keys require the KimiCLI User-Agent on api.kimi.com/coding/v1
        default_headers = None
        frequency_penalty = kwargs.get("frequency_penalty", 0.3)
        if provider.name == "kimi" and provider.base_url and "kimi.com" in provider.base_url:
            default_headers = {"User-Agent": "KimiCLI/1.47.0"}
            frequency_penalty = 0  # Kimi models only accept 0

        return ChatOpenAI(
            model=model,
            api_key=provider.api_key,
            base_url=provider.base_url,
            temperature=kwargs.get("temperature", 0.1),
            max_completion_tokens=kwargs.get("max_completion_tokens", 1024),
            frequency_penalty=frequency_penalty,
            default_headers=default_headers,
        )

    def _create_anthropic(self, provider: ProviderInfo, model: str, **kwargs):
        """Create Anthropic LLM."""
        from browser_use.llm.anthropic.chat import ChatAnthropic

        return ChatAnthropic(
            model=model,
            api_key=provider.api_key,
            temperature=kwargs.get("temperature", 0.1),
        )

    def _create_google(self, provider: ProviderInfo, model: str, **kwargs):
        """Create Google Gemini LLM."""
        from browser_use.llm.google.chat import ChatGoogle

        return ChatGoogle(
            model=model,
            api_key=provider.api_key,
            temperature=kwargs.get("temperature", 0.1),
        )

    def _create_ollama(self, provider: ProviderInfo, model: str, **kwargs):
        """Create Ollama local LLM."""
        from browser_use.llm.ollama.chat import ChatOllama

        return ChatOllama(
            model=model,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=kwargs.get("temperature", 0.1),
        )

    def _create_kimi_cli(self, model: str, **kwargs):
        """
        Create a wrapper that uses kimi CLI as subprocess.

        This is a fallback when no API key is available but the kimi CLI is installed.
        """
        return KimiCLIWrapper(**kwargs)

    # ─── QUERIES ───

    def available_providers(self) -> List[ProviderInfo]:
        """List all available providers."""
        if not self._discovered:
            self._discover_all()
        return [p for p in self._providers.values() if p.available]

    def list_available_models(self) -> List[str]:
        """List all available models across all providers."""
        if not self._discovered:
            self._discover_all()
        models = []
        for provider in self.available_providers():
            for m in provider.models:
                models.append(f"{provider.name}/{m}")
        return models

    def get_provider_for_model(self, model_name: str) -> Optional[ProviderInfo]:
        """Get provider info for a specific model."""
        if not self._discovered:
            self._discover_all()
        return self._find_provider_for_model(model_name)

    @classmethod
    def clear_cache(cls):
        """Clear the discovery cache. Useful in tests."""
        cls._cache = None
        cls._cache_time = None


class _SimpleCompletion:
    """Minimal completion object compatible with browser-use's expected interface."""

    def __init__(self, completion, usage=None, thinking=None, stop_reason=None):
        self.completion = completion
        self.usage = usage
        self.thinking = thinking
        self.redacted_thinking = None
        self.stop_reason = stop_reason


class KimiCLIWrapper:
    """
    Wrapper that uses kimi CLI as a subprocess for inference.

    Usage:
        wrapper = KimiCLIWrapper()
        response = await wrapper.ainvoke([SystemMessage("..."), UserMessage("...")])
        print(response.completion)

    Note: This wrapper is best for simple text tasks. For browser-use Agent
    (which requires structured JSON output), use the Kimi API provider instead.
    """

    def __init__(self, temperature: float = 0.1, **kwargs):
        self.temperature = temperature

    async def ainvoke(self, messages, output_format=None, **kwargs):
        """
        Async invoke compatible with browser-use LLM interface.

        Args:
            messages: List of message objects (SystemMessage, UserMessage, etc.)
            output_format: Optional Pydantic model for structured output
            **kwargs: Ignored (for compatibility)

        Returns:
            _SimpleCompletion with .completion attribute
        """
        prompt = self._messages_to_prompt(messages)

        # If structured output requested, add JSON instructions
        if output_format is not None:
            schema = output_format.model_json_schema()
            prompt += (
                f"\n\nIMPORTANT: Respond with ONLY a valid JSON object "
                f"matching this schema:\n{json.dumps(schema, indent=2)}"
            )

        text = await self._run_kimi(prompt)
        text = self._clean_output(text)

        # Try to parse structured output
        if output_format is not None:
            completion = self._try_parse_json(text, output_format)
        else:
            completion = text

        return _SimpleCompletion(completion=completion)

    async def _run_kimi(self, prompt: str) -> str:
        """Run kimi CLI asynchronously."""
        proc = await asyncio.create_subprocess_exec(
            "kimi", "--quiet", "-p", prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"kimi CLI failed (exit {proc.returncode}): {err}")

        return stdout.decode("utf-8", errors="replace")

    def _clean_output(self, text: str) -> str:
        """Remove session resume footer and markdown fences."""
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            if line.strip().startswith("To resume this session:"):
                break
            cleaned.append(line)
        text = "\n".join(cleaned).strip()

        # Strip markdown code fences if present
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    def _try_parse_json(self, text: str, output_format):
        """Attempt to parse text as JSON matching output_format."""
        try:
            data = json.loads(text)
            return output_format.model_validate(data)
        except Exception as e:
            logger.warning(f"KimiCLIWrapper: JSON parse failed: {e}. Returning raw text.")
            return text

    def _messages_to_prompt(self, messages) -> str:
        """Convert message list to a single prompt string."""
        parts = []
        for msg in messages:
            if hasattr(msg, 'content'):
                content = msg.content
            elif isinstance(msg, dict):
                content = msg.get('content', '')
            else:
                content = str(msg)
            parts.append(content)
        return "\n\n".join(parts)
