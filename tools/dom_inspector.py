"""
DOM Inspector — Automatic trading platform selector discovery

Logs into trading platforms, inspects the DOM, and extracts
selectors for key interactive elements (Buy, Sell, Quantity, etc.).

Usage:
    python -m tools.dom_inspector --platform topstep
    
Results are saved to data/platform_selectors.json for use by
the prop firm order placement agent.
"""

import asyncio
import json
import os
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger
from playwright.async_api import async_playwright


# Platform configurations
PLATFORM_CONFIGS = {
    "topstep": {
        "name": "TopstepX",
        "login_url": "https://topstepx.com/login",
        "trade_url_pattern": "**/trade",
        "credentials": ["TOPSTEP_USERNAME", "TOPSTEP_PASSWORD"],
    },
}


# Elements we want to discover
TARGET_ELEMENTS = {
    "buy_button": {
        "descriptions": ["Buy", "Long", "BUY", "LONG"],
        "attributes": ["data-testid", "data-action", "aria-label", "id", "class"],
    },
    "sell_button": {
        "descriptions": ["Sell", "Short", "SELL", "SHORT"],
        "attributes": ["data-testid", "data-action", "aria-label", "id", "class"],
    },
    "quantity_input": {
        "descriptions": ["# of Contracts", "Quantity", "Qty", "Size", "Contracts"],
        "attributes": ["data-testid", "aria-label", "name", "id", "class"],
        "input_type": "number",
    },
    "symbol_input": {
        "descriptions": ["Contract", "Symbol", "Instrument"],
        "attributes": ["data-testid", "aria-label", "name", "id", "class"],
        "input_type": "text",
    },
    "order_type_select": {
        "descriptions": ["Order Type", "Type"],
        "attributes": ["data-testid", "aria-label", "name", "id", "class"],
    },
}


def _load_env_credentials(platform: str) -> Dict[str, str]:
    """Load credentials from environment."""
    from dotenv import load_dotenv
    load_dotenv()
    
    config = PLATFORM_CONFIGS.get(platform)
    if not config:
        raise ValueError(f"Unknown platform: {platform}")
    
    creds = {}
    for key in config["credentials"]:
        val = os.getenv(key)
        if not val:
            raise ValueError(f"Missing credential: {key}")
        creds[key] = val
    return creds


async def inspect_platform(platform: str = "topstep", headless: bool = True) -> Dict:
    """
    Log into a trading platform and inspect the DOM for interactive elements.
    
    Returns a dict with discovered selectors and metadata.
    """
    config = PLATFORM_CONFIGS.get(platform)
    if not config:
        raise ValueError(f"Unknown platform: {platform}")
    
    creds = _load_env_credentials(platform)
    username = creds.get("TOPSTEP_USERNAME", "")
    password = creds.get("TOPSTEP_PASSWORD", "")
    
    results = {
        "platform": platform,
        "inspected_at": datetime.utcnow().isoformat(),
        "selectors": {},
        "screenshots": {},
        "raw_elements": {},
    }
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless, slow_mo=100)
        page = await browser.new_page(viewport={"width": 1920, "height": 1080})
        
        try:
            # Login
            logger.info(f"Navigating to {config['login_url']}")
            await page.goto(config["login_url"], wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)
            
            # Fill login form
            inputs = await page.query_selector_all("input")
            for inp in inputs:
                name = await inp.get_attribute("name") or ""
                typ = await inp.get_attribute("type") or ""
                if "user" in name.lower() or typ == "email":
                    await inp.fill(username)
                elif typ == "password":
                    await inp.fill(password)
            
            # Click login
            btn = await page.query_selector('button:has-text("PLATFORM LOGIN")')
            if btn:
                await btn.click()
            
            # Wait for trade page
            await page.wait_for_url(config["trade_url_pattern"], timeout=60000)
            logger.info("Reached trade page, waiting for UI to load...")
            await asyncio.sleep(10)
            
            # Save screenshots
            screenshots_dir = Path(__file__).parent.parent / "data" / "audit"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            
            trade_ss = screenshots_dir / f"{platform}_trade_full.png"
            await page.screenshot(path=str(trade_ss), full_page=True)
            results["screenshots"]["trade_full"] = str(trade_ss)
            
            # Save HTML
            html_path = screenshots_dir / f"{platform}_trade.html"
            html = await page.content()
            html_path.write_text(html, encoding="utf-8")
            results["screenshots"]["trade_html"] = str(html_path)
            
            # Inspect elements
            for element_name, element_config in TARGET_ELEMENTS.items():
                discovered = await _discover_element(page, element_name, element_config)
                results["selectors"][element_name] = discovered
                results["raw_elements"][element_name] = discovered.get("candidates", [])
            
            logger.info(f"DOM inspection complete. Found {len(results['selectors'])} element types.")
            
        except Exception as e:
            logger.error(f"DOM inspection failed: {e}")
            results["error"] = str(e)
            # Save error screenshot
            error_ss = screenshots_dir / f"{platform}_error_{datetime.utcnow().strftime('%H%M%S')}.png"
            try:
                await page.screenshot(path=str(error_ss), full_page=True)
                results["screenshots"]["error"] = str(error_ss)
            except Exception:
                pass
        finally:
            await browser.close()
    
    return results


async def _discover_element(page, name: str, config: Dict) -> Dict:
    """Discover a specific element on the page."""
    result = {
        "best_selector": None,
        "selector_type": None,
        "text": None,
        "candidates": [],
    }
    
    descriptions = config.get("descriptions", [])
    attributes = config.get("attributes", [])
    input_type = config.get("input_type")
    
    # Strategy 1: Search by data-testid (most reliable)
    for attr in attributes:
        if attr == "data-testid":
            # Try common patterns
            patterns = [name.replace("_", "-")]
            if "button" in name:
                patterns.extend([f"{name.replace('_', '-')}-button", f"click-button-{name.replace('_', '-').replace('-button', '')}"])
            
            for pattern in patterns:
                try:
                    el = await page.query_selector(f'[{attr}*="{pattern}"]')
                    if el:
                        val = await el.get_attribute(attr)
                        tag = await el.evaluate("el => el.tagName")
                        result["best_selector"] = f'[{attr}="{val}"]'
                        result["selector_type"] = attr
                        result["text"] = await el.inner_text() if hasattr(el, "inner_text") else None
                        result["candidates"].append({"selector": result["best_selector"], "tag": tag, "text": result["text"]})
                        return result
                except Exception:
                    pass
    
    # Strategy 2: Search by button text
    if "button" in name:
        for text in descriptions:
            try:
                els = await page.query_selector_all(f'button:has-text("{text}")')
                for el in els:
                    cls = await el.get_attribute("class") or ""
                    data_testid = await el.get_attribute("data-testid") or ""
                    sel = f'[data-testid="{data_testid}"]' if data_testid else f'button:has-text("{text}")'
                    result["candidates"].append({
                        "selector": sel,
                        "tag": "BUTTON",
                        "text": text,
                        "class": cls,
                    })
                if els:
                    best = result["candidates"][0]
                    result["best_selector"] = best["selector"]
                    result["selector_type"] = "text"
                    result["text"] = best["text"]
                    return result
            except Exception:
                pass
    
    # Strategy 3: Search inputs by label or placeholder
    if input_type:
        # Find by label text
        for text in descriptions:
            try:
                # Look for label with this text, then find associated input
                labels = await page.query_selector_all(f'label:has-text("{text}")')
                for lbl in labels:
                    inp_id = await lbl.get_attribute("for")
                    if inp_id:
                        inp = await page.query_selector(f'#{inp_id}')
                        if inp:
                            result["candidates"].append({
                                "selector": f'#{inp_id}',
                                "tag": "INPUT",
                                "label": text,
                            })
                if result["candidates"]:
                    best = result["candidates"][0]
                    result["best_selector"] = best["selector"]
                    result["selector_type"] = "label"
                    return result
            except Exception:
                pass
        
        # Find by input type
        try:
            els = await page.query_selector_all(f'input[type="{input_type}"]')
            for el in els:
                aria = await el.get_attribute("aria-label") or ""
                placeholder = await el.get_attribute("placeholder") or ""
                name_attr = await el.get_attribute("name") or ""
                for text in descriptions:
                    if text.lower() in (aria + placeholder + name_attr).lower():
                        sel = f'input[type="{input_type}"][aria-label*="{text}"]' if aria else f'input[type="{input_type}"]'
                        result["candidates"].append({"selector": sel, "tag": "INPUT", "label": text})
            if result["candidates"]:
                best = result["candidates"][0]
                result["best_selector"] = best["selector"]
                result["selector_type"] = "input_type"
                return result
        except Exception:
            pass
    
    return result


def save_selectors(results: Dict, platform: str = "topstep"):
    """Save discovered selectors to JSON config."""
    selectors_dir = Path(__file__).parent.parent / "data"
    selectors_dir.mkdir(parents=True, exist_ok=True)
    
    config_path = selectors_dir / "platform_selectors.json"
    
    # Load existing
    existing = {}
    if config_path.exists():
        existing = json.loads(config_path.read_text())
    
    # Update
    existing[platform] = {
        "updated_at": results.get("inspected_at"),
        "selectors": {
            k: v.get("best_selector")
            for k, v in results.get("selectors", {}).items()
            if v.get("best_selector")
        },
        "raw": results.get("raw_elements", {}),
    }
    
    config_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    logger.info(f"Saved selectors to {config_path}")


def load_selectors(platform: str = "topstep") -> Dict[str, str]:
    """Load cached selectors for a platform."""
    config_path = Path(__file__).parent.parent / "data" / "platform_selectors.json"
    if not config_path.exists():
        return {}
    
    data = json.loads(config_path.read_text())
    platform_data = data.get(platform, {})
    return platform_data.get("selectors", {})


async def main():
    parser = argparse.ArgumentParser(description="DOM Inspector for trading platforms")
    parser.add_argument("--platform", default="topstep", help="Platform to inspect")
    parser.add_argument("--headless", action="store_true", default=True, help="Run headless")
    parser.add_argument("--headed", action="store_true", help="Run with visible browser")
    args = parser.parse_args()
    
    headless = not args.headed
    results = await inspect_platform(args.platform, headless=headless)
    
    if "error" not in results:
        save_selectors(results, args.platform)
    
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
