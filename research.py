"""
Research Ingestion Module

Web content extraction and thesis generation.
Uses trafilatura for URL extraction (feature-gated).
Hybrid ingestion: supports both user-provided URLs and automatic API data fetching.
"""

import asyncio
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from loguru import logger

from models import (
    EvidenceItem,
    ThesisObject,
    RegimeBias,
    generate_evidence_id,
    generate_thesis_id,
)


class ResearchIngestion:
    """Web content extraction and thesis generation with hybrid ingestion."""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        research_config = self.config.get("research", {})
        self.enable_extraction = research_config.get("enable_ingestion", False)

        self.auto_sources = research_config.get(
            "auto_sources",
            ["tradingview.com", "forexfactory.com", "fxstreet.com", "dailyfx.com"],
        )

    async def ingest_intelligent(
        self, urls: List[str] = None, symbols: List[str] = None, **kwargs
    ) -> Tuple[List[EvidenceItem], ThesisObject]:
        """
        Intelligent ingestion:
        - If URLs provided: fetch from user sources
        - If symbols provided: auto-fetch from trusted sources
        - If both: combine both
        - If neither: use default watchlist

        Returns:
            (EvidenceItems[], ThesisObject)
        """
        evidence_items = []

        if urls:
            logger.info(f"User provided {len(urls)} explicit URLs")
            user_evidence, _ = await self.ingest_urls(urls, **kwargs)
            evidence_items.extend(user_evidence)

        elif symbols:
            logger.info(f"Auto-fetching research for {len(symbols)} symbols")
            auto_evidence = await self.auto_ingest_for_symbols(symbols, **kwargs)
            evidence_items.extend(auto_evidence)

        elif urls and symbols:
            logger.info("Combining user URLs with auto-fetch")
            user_evidence, _ = await self.ingest_urls(urls, **kwargs)
            auto_evidence = await self.auto_ingest_for_symbols(symbols, **kwargs)
            evidence_items = user_evidence + auto_evidence

        else:
            logger.info("No URLs or symbols - using default watchlist")
            watchlist = self.config.get("watchlists", {}).get("options", ["SPY", "QQQ"])
            evidence_items = await self.auto_ingest_for_symbols(watchlist, **kwargs)

        thesis = await self.generate_thesis(evidence_items)

        logger.info(
            f"Created thesis {thesis.id} with {len(evidence_items)} evidence items"
        )
        return evidence_items, thesis

    async def auto_ingest_for_symbols(
        self, symbols: List[str], **kwargs
    ) -> List[EvidenceItem]:
        """
        Automatically ingest research for specific symbols.

        Fetches from trusted sources configured in auto_sources.
        """
        logger.info(f"Auto-ingesting research for {len(symbols)} symbols")

        evidence_items = []

        for symbol in symbols:
            symbol_urls = self._build_symbol_urls(symbol)

            for url in symbol_urls:
                try:
                    evidence = await self._create_evidence_from_market_data(symbol, url)
                    if evidence:
                        evidence_items.append(evidence)
                        logger.info(f"Auto-fetched: {evidence.title}")
                except Exception as e:
                    logger.error(f"Failed auto-fetch from {url}: {e}")
                    evidence = EvidenceItem(
                        id=generate_evidence_id(),
                        url=url,
                        title=f"Failed: {symbol} research",
                        snippet="Auto-fetch failed",
                        timestamp=datetime.utcnow(),
                        confidence=0.1,
                        tags=["failed"],
                    )
                    evidence_items.append(evidence)

        return evidence_items

    def _build_symbol_urls(self, symbol: str) -> List[str]:
        """
        Build URLs for a symbol from trusted research sources.

        Example: For SPY, generates:
        - https://tradingview.com/symbols/SPY
        - https://forexfactory.com/news/SPY
        """
        url_patterns = [
            f"https://tradingview.com/symbols/{symbol.lower()}",
            f"https://forexfactory.com/news/{symbol.lower()}",
            f"https://fxstreet.com/market/{symbol.lower()}",
            f"https://dailyfx.com/{symbol.lower()}",
        ]

        return url_patterns

    async def _create_evidence_from_market_data(
        self, symbol: str, url: str
    ) -> Optional[EvidenceItem]:
        """
        Create evidence item from fetched market data.

        This is a placeholder - full implementation would call market_data/fetcher.
        """
        try:
            from market_data.fetcher import MarketDataFetcher

            fetcher = MarketDataFetcher(self.config)
            data = await fetcher.fetch_symbol_data(symbol)

            if not data.get("news"):
                return None

            articles = data["news"][:3]
            if not articles:
                return None

            latest_article = articles[0]

            return EvidenceItem(
                id=generate_evidence_id(),
                url=url,
                title=latest_article.get("title", f"{symbol} Research"),
                snippet=latest_article.get("description", f"{symbol} market data")[
                    :200
                ],
                timestamp=datetime.utcnow(),
                confidence=0.85,
                tags=["market_data", "api"],
            )

        except ImportError:
            logger.warning("Market data fetcher not available")
            return None
        except Exception as e:
            logger.error(f"Failed to create evidence for {symbol}: {e}")
            return None

    async def ingest_urls(
        self, urls: List[str], **kwargs
    ) -> Tuple[List[EvidenceItem], ThesisObject]:
        """
        Extract content from URLs and synthesize thesis.

        Args:
            urls: List of URLs to process

        Returns:
            (EvidenceItems[], ThesisObject)

        Notes:
            - Extracts clean text from each URL
            - Stores EvidenceItems in DB
            - Synthesizes into ThesisObject (LLM)
            - Degrades gracefully on extraction failure
        """
        logger.info(f"Ingesting {len(urls)} research URLs")

        evidence_items = []

        for url in urls:
            try:
                if self.enable_extraction:
                    evidence = await self.extract_content(url)
                    if evidence:
                        evidence_items.append(evidence)
                        logger.info(f"Extracted: {evidence.title}")
                else:
                    evidence = EvidenceItem(
                        id=generate_evidence_id(),
                        url=url,
                        title=f"Research: {url[:50]}...",
                        snippet="Web extraction disabled (feature flag)",
                        timestamp=datetime.utcnow(),
                        confidence=0.5,
                        tags=["external"],
                    )
                    evidence_items.append(evidence)
            except Exception as e:
                logger.error(f"Failed to extract from {url}: {e}")
                evidence = EvidenceItem(
                    id=generate_evidence_id(),
                    url=url,
                    title=f"Failed: {url[:50]}...",
                    snippet="Extraction failed",
                    timestamp=datetime.utcnow(),
                    confidence=0.1,
                    tags=["failed"],
                )
                evidence_items.append(evidence)

        thesis = await self.generate_thesis(evidence_items)

        logger.info(
            f"Created thesis {thesis.id} with {len(evidence_items)} evidence items"
        )
        return evidence_items, thesis

    async def extract_content(self, url: str) -> Optional[EvidenceItem]:
        """
        Extract clean text from URL.

        Uses trafilatura library (optional via feature flag).
        """
        try:
            import trafilatura

            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None

            text = trafilatura.extract(downloaded)
            if not text:
                return None

            title = trafilatura.extract_title(downloaded) or "Untitled"
            date = trafilatura.extract_date(downloaded) or datetime.utcnow()

            snippet = text[:200] + "..." if len(text) > 200 else text

            return EvidenceItem(
                id=generate_evidence_id(),
                url=url,
                title=title,
                snippet=snippet,
                timestamp=date if isinstance(date, datetime) else datetime.utcnow(),
                confidence=0.8,
                tags=["web", "extracted"],
            )

        except ImportError:
            logger.warning("trafilatura not installed, web extraction disabled")
            return None
        except Exception as e:
            logger.error(f"Extraction error for {url}: {e}")
            return None

    async def generate_thesis(self, evidence_items: List[EvidenceItem]) -> ThesisObject:
        """
        Synthesize evidence into a thesis object.

        Uses LLM (Gemini/OpenAI) to:
        - Summarize key points
        - Determine regime bias (risk-on/off)
        - Assign overall conviction

        Degrades gracefully if LLM unavailable.
        """
        if not evidence_items:
            return ThesisObject(
                id=generate_thesis_id(),
                summary="No evidence available",
                evidence_ids=[],
                conviction=0.0,
                regime_bias=RegimeBias.NEUTRAL,
                created_at=datetime.utcnow(),
                tags=[],
            )

        try:
            from tools.brain import reason_about_setup

            context = "\n\n".join(
                [
                    f"Evidence {i + 1}:\n{e.title}\n{e.snippet}\n"
                    for i, e in enumerate(evidence_items)
                ]
            )

            llm_result = await reason_about_setup(context)

            summary = llm_result.get("summary", "LLM synthesis failed")
            bias_str = llm_result.get("regime_bias", "neutral").lower()

            if bias_str == "risk_on":
                regime_bias = RegimeBias.RISK_ON
            elif bias_str == "risk_off":
                regime_bias = RegimeBias.RISK_OFF
            else:
                regime_bias = RegimeBias.NEUTRAL

            avg_confidence = sum(e.confidence for e in evidence_items) / len(
                evidence_items
            )

            return ThesisObject(
                id=generate_thesis_id(),
                summary=summary,
                evidence_ids=[e.id for e in evidence_items],
                conviction=avg_confidence,
                regime_bias=regime_bias,
                created_at=datetime.utcnow(),
                tags=[tag for e in evidence_items for tag in e.tags],
            )

        except Exception as e:
            logger.warning(f"LLM synthesis failed: {e}, using fallback")
            summaries = [e.snippet for e in evidence_items[:3]]
            summary = " | ".join(summaries)

            return ThesisObject(
                id=generate_thesis_id(),
                summary=summary,
                evidence_ids=[e.id for e in evidence_items],
                conviction=0.5,
                regime_bias=RegimeBias.NEUTRAL,
                created_at=datetime.utcnow(),
                tags=["fallback"],
            )


async def run_research_workflow(urls: List[str]):
    """
    Standalone research workflow entry point using intelligent ingestion.

    Supports:
    - Explicit URLs: dexter run workflow research --urls "url1,url2"
    - Symbols: dexter run workflow research --symbols SPY,QQQ
    - Auto mode: dexter run workflow research (uses default watchlist)
    """
    from standalone.config import Config

    config = Config.load()
    ingestion = ResearchIngestion(config.__dict__)

    evidence_items, thesis = await ingestion.ingest_intelligent(urls=urls)

    print(f"\nThesis Created: {thesis.id}")
    print(f"Regime Bias: {thesis.regime_bias.value}")
    print(f"Conviction: {thesis.conviction:.2%}")
    print(f"Summary: {thesis.summary}\n")
    print(f"Evidence Items: {len(evidence_items)}")

    for i, evidence in enumerate(evidence_items, 1):
        print(f"  {i}. {evidence.title} ({evidence.confidence:.2%})")
