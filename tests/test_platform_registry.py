from alpha_platform.paths import forks
from alpha_platform.registry import (
    chart_symbol_for,
    component_status,
    desk_payload,
    desk_watchlist,
    hummingbot_inventory,
    vibe_inventory,
)


def test_sibling_forks_exist():
    f = forks()
    assert f.agent.exists()
    assert f.hummingbot.exists()
    assert f.vibe.exists()
    assert f.autohedge.exists()
    assert f.fincept_src.exists()


def test_component_status_lists_all_five():
    payload = component_status()
    ids = [c["id"] for c in payload["components"]]
    assert ids == ["dexter", "fincept", "hummingbot", "vibe", "autohedge"]
    assert payload["ok"] is True


def test_hummingbot_catalog_is_populated():
    inv = hummingbot_inventory()
    assert inv["controller_count"] >= 10
    assert inv["script_count"] >= 5
    assert inv["live_ready"] is False


def test_vibe_skills_are_catalogued():
    inv = vibe_inventory()
    assert inv["skill_count"] >= 20
    assert inv["factor_count"] >= 10
    assert any(s["id"] == "alpha-zoo" for s in inv["skills"])


def test_desk_payload_has_blotter_and_venues():
    desk = desk_payload()
    assert "venues" in desk
    assert "venue_cards" in desk
    assert any(c["id"] == "oanda" for c in desk["venue_cards"])
    assert any(c["id"] == "hummingbot" for c in desk["venue_cards"])
    assert any(c["id"] == "paper" for c in desk["venue_cards"])
    assert any(c["id"] == "tradovate" for c in desk["venue_cards"])
    assert "paper_trades" in desk
    assert "signals" in desk
    assert "components" in desk
    assert desk["hummingbot_controller_count"] >= 10
    assert desk["vibe_skill_count"] >= 20
    assert desk["watchlist"] == desk_watchlist()
    assert "SPY" in desk["watchlist"]


def test_desk_watchlist_is_us_liquid():
    wl = desk_watchlist()
    assert wl[0] == "SPY"
    assert "NVDA" in wl
    assert "QQQ" in wl
    assert len(wl) >= 8


def test_chart_symbol_aliases_keep_equities():
    assert chart_symbol_for("AAPL") == "AAPL"
    assert chart_symbol_for("eurusd") == "SPY"
    assert chart_symbol_for("XAUUSD") == "GLD"
    assert chart_symbol_for("NQ") == "QQQ"
    assert chart_symbol_for("BTCUSD") == "IBIT"
    assert chart_symbol_for("BTC/USDT") == "IBIT"
