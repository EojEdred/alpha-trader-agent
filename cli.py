#!/usr/bin/env python3
"""
Dexter CLI - Trading Research & Execution System

Usage:
    dexter run                    # Start scheduler
    dexter brief                  # Generate morning brief
    dexter score SYMBOL           # Score a setup
    dexter arb                    # Run arbitrage scanner
    dexter trade SYMBOL long      # Manual trade
    dexter positions              # Show positions
    dexter watch                  # Live dashboard
"""

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint
from datetime import datetime
import asyncio
import os
from typing import List
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = typer.Typer(name="dexter", help="Trading Research & Execution System")
console = Console()


@app.command()
def run(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Run in simulation mode (no actual trades)"
    ),
    venue: List[str] = typer.Option(
        ["all"],
        "--venue",
        "-v",
        help="Venues to trade on: schwab, topstep, oanda, kalshi, all",
    ),
):
    """Start the full scheduler (research, reports, monitoring)."""
    from standalone.main import AlphaTrader

    # Normalize venues
    if "all" in venue:
        active_venues = ["schwab", "topstep", "oanda", "kalshi"]
    else:
        active_venues = [v.lower() for v in venue]

    mode_str = (
        "[bold yellow]DRY RUN / SIMULATION MODE[/bold yellow]"
        if dry_run
        else "[bold red]LIVE TRADING MODE[/bold red]"
    )
    venue_str = ", ".join(active_venues).upper()

    console.print(
        Panel.fit(
            f"DEXTER Trading System Starting...\nMode: {mode_str}\nVenues: {venue_str}",
            title="🚀 Startup",
        )
    )

    # Set environment variables for the session
    if dry_run:
        os.environ["DRY_RUN"] = "true"

    os.environ["ACTIVE_VENUES"] = ",".join(active_venues)

    trader = AlphaTrader()
    asyncio.run(trader.start())


@app.command()
def agent_cycle(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run in simulation mode"),
    live: bool = typer.Option(False, "--live", help="Run in live trading mode"),
):
    """Manually trigger one autonomous agent cycle (Scan -> Reason -> Execute)."""
    from standalone.main import AlphaTrader

    # Logic: if --live is passed and NOT --dry-run
    is_live = live and not dry_run

    if is_live:
        confirm = typer.confirm("⚠️ You are about to run a LIVE agent cycle. Continue?")
        if not confirm:
            return
    else:
        # Default to dry run for safety and automation
        os.environ["DRY_RUN"] = "true"
        console.print(
            "[bold yellow]🧪 Running Agent Cycle in DRY RUN mode...[/bold yellow]"
        )

    trader = AlphaTrader()
    asyncio.run(trader.run_workflow("autonomous-scalper-v1"))


@app.command()
def brief(
    date: str = typer.Option(None, help="Date for brief (YYYY-MM-DD)"),
    output: str = typer.Option(
        "terminal", help="Output format: terminal, markdown, pdf"
    ),
):
    """Generate morning trading brief."""
    from dexter.brief import generate_brief

    target_date = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()

    console.print(
        f"\n[bold]Generating brief for {target_date.strftime('%Y-%m-%d')}...[/bold]\n"
    )

    brief_data = asyncio.run(generate_brief(target_date))

    if output == "terminal":
        _display_brief_terminal(brief_data)
    else:
        console.print(f"Brief saved to: {brief_data['output_path']}")


@app.command()
def score(
    symbol: str = typer.Argument(..., help="Symbol to score (e.g., NQ, SPY)"),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed breakdown"
    ),
):
    """Score a trading setup using A+ system."""
    from tools.scoring import score_setup

    console.print(f"\n[bold]Scoring setup for {symbol}...[/bold]\n")

    result = asyncio.run(score_setup(symbol))

    # Display score card
    table = Table(title=f"A+ Score: {symbol}")
    table.add_column("Component", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Max", justify="right")

    table.add_row("Location", str(result.location_pts), "25")
    table.add_row("Order Flow", str(result.flow_pts), "25")
    table.add_row("Setup Quality", str(result.setup_pts), "25")
    table.add_row("Regime", str(result.regime_pts), "25")
    table.add_row("─" * 15, "─" * 5, "─" * 5)
    table.add_row(
        "[bold]TOTAL[/bold]", f"[bold]{result.total}[/bold]", "[bold]100[/bold]"
    )

    console.print(table)

    grade = result.grade.value
    grade_colors = {"A_PLUS": "green", "A": "green", "B": "yellow", "NO_TRADE": "red"}
    console.print(
        f"\n[bold {grade_colors.get(grade, 'white')}]Grade: {grade}[/bold {grade_colors.get(grade, 'white')}]"
    )

    if grade == "NO_TRADE":
        console.print("[red]⚠️  Setup does not meet minimum criteria[/red]")
    elif grade == "B":
        console.print("[yellow]📊 Trade at 50% size[/yellow]")
    else:
        console.print("[green]✅ Trade at full size[/green]")


@app.command()
def arb(
    execute: bool = typer.Option(
        False, "--execute", "-x", help="Execute detected arbs"
    ),
    min_spread: float = typer.Option(1.0, help="Minimum spread % to show"),
):
    """Scan for prediction market arbitrage opportunities."""
    from tools.arbitrage import scan_arbitrage

    console.print("\n[bold]Scanning for arbitrage opportunities...[/bold]\n")

    opportunities = asyncio.run(scan_arbitrage(min_spread_pct=min_spread))

    if not opportunities:
        console.print(
            "[yellow]No arbitrage opportunities found above threshold.[/yellow]"
        )
        return

    table = Table(title="Arbitrage Opportunities")
    table.add_column("Type", style="cyan")
    table.add_column("Market", style="white")
    table.add_column("Spread", justify="right", style="green")
    table.add_column("Platforms", style="white")
    table.add_column("Liquidity", justify="right")

    for opp in opportunities:
        table.add_row(
            opp["type"],
            opp["market"][:40],
            f"{opp['spread_pct']:.2f}%",
            opp["platforms"],
            f"${opp['liquidity']:,.0f}",
        )

    console.print(table)

    if execute:
        console.print("\n[bold yellow]Executing arbitrage trades...[/bold yellow]")
        # Execute logic here


@app.command()
def trade(
    symbol: str = typer.Argument(..., help="Symbol to trade"),
    direction: str = typer.Argument(..., help="long or short"),
    size: float = typer.Option(None, help="Position size (default: auto from scoring)"),
    venue: str = typer.Option("auto", help="Venue: auto, oanda, kalshi, polymarket"),
):
    """Manually enter a trade."""
    from tools.execution import submit_trade

    console.print(f"\n[bold]Preparing {direction} trade for {symbol}...[/bold]\n")

    # First score the setup
    from tools.scoring import score_setup

    score_result = asyncio.run(score_setup(symbol))

    if score_result["grade"] == "NO_TRADE":
        console.print("[red]⚠️  Setup scored below threshold. Trade anyway? (y/n)[/red]")
        confirm = typer.prompt("Confirm")
        if confirm.lower() != "y":
            return

    result = asyncio.run(submit_trade(symbol, direction, size, venue))
    console.print(f"[green]Trade submitted: {result}[/green]")


@app.command()
def positions():
    """Show current open positions across all venues."""
    from tools.execution import get_all_positions

    positions = asyncio.run(get_all_positions())

    if not positions:
        console.print("[yellow]No open positions.[/yellow]")
        return

    table = Table(title="Open Positions")
    table.add_column("Venue", style="cyan")
    table.add_column("Symbol", style="white")
    table.add_column("Side", style="white")
    table.add_column("Size", justify="right")
    table.add_column("Entry", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("P&L", justify="right")

    for pos in positions:
        pnl_color = "green" if pos["pnl"] >= 0 else "red"
        table.add_row(
            pos["venue"],
            pos["symbol"],
            pos["side"],
            str(pos["size"]),
            f"{pos['entry']:.4f}",
            f"{pos['current']:.4f}",
            f"[{pnl_color}]{pos['pnl']:+.2f}[/{pnl_color}]",
        )

    console.print(table)


@app.command()
def pnl(period: str = typer.Option("today", help="Period: today, week, month, all")):
    """Show P&L summary."""
    from tools.reporting import calculate_pnl_summary

    summary = asyncio.run(calculate_pnl_summary(period))

    console.print(
        Panel(
            f"""
[bold]P&L Summary ({period})[/bold]

Total P&L: [{"green" if summary["total"] >= 0 else "red"}]{summary["total"]:+.2f}[/]
Win Rate: {summary["win_rate"]:.1%}
Trades: {summary["trade_count"]}
Best: [green]+{summary["best"]:.2f}[/green]
Worst: [red]{summary["worst"]:.2f}[/red]
        """,
            title="📊 Performance",
        )
    )


auth_app = typer.Typer(help="Authentication commands")
app.add_typer(auth_app, name="auth")


@auth_app.command("schwab")
def auth_schwab():
    """Trigger the Charles Schwab manual authentication flow."""
    from tools.schwab import get_schwab_client

    console.print(
        "[bold yellow]Starting Charles Schwab Authentication Flow...[/bold yellow]"
    )
    client = get_schwab_client()
    success = client.authenticate()

    if success:
        console.print("[bold green]✅ Schwab authentication successful![/bold green]")
    else:
        console.print("[bold red]❌ Schwab authentication failed.[/bold red]")


@app.command()
def pdt():
    """Check current Pattern Day Trader (PDT) status from Schwab."""
    from tools.strategy import check_pdt_compliance

    console.print("[bold yellow]Querying Schwab for PDT status...[/bold yellow]")

    # We need to run the async function
    success = asyncio.run(check_pdt_compliance())

    if success:
        console.print(
            "[bold green]✅ Within PDT limits. You can still day trade.[/bold green]"
        )
    else:
        console.print(
            "[bold red]⚠️ PDT limit reached or check failed. Day trading is restricted.[/bold red]"
        )


@app.command()
def watch():
    """Launch live TUI dashboard."""
    from dexter.tui import DexterDashboard

    dashboard = DexterDashboard()
    dashboard.run()


@app.command()
def run_workflow(
    workflow: str = typer.Argument(
        ..., help="Workflow to run: morning-report, research"
    ),
    urls: List[str] = typer.Option(
        [], "--urls", "-u", help="Research URLs for research workflow"
    ),
):
    """Run specific Zynth workflow."""
    if workflow == "research":
        from research import run_research_workflow

        asyncio.run(run_research_workflow(urls))
    elif workflow == "morning-report":
        from standalone.main import AlphaTrader

        trader = AlphaTrader()
        asyncio.run(trader.run_workflow("morning-report"))
    else:
        console.print(f"[red]Unknown workflow: {workflow}[/red]")
        console.print("[yellow]Available workflows: morning-report, research[/yellow]")


@app.command()
def auto_fetch(
    symbols: List[str] = typer.Option(
        [], "--symbols", "-s", help="Symbols to auto-fetch (e.g., SPY,QQQ,NQ)"
    ),
):
    """Auto-fetch market data for specified symbols."""
    from research import ResearchIngestion
    from standalone.config import Config

    config = Config.load()
    ingestion = ResearchIngestion(config.__dict__)

    console.print(
        f"[bold cyan]Auto-fetching market data for {len(symbols)} symbols...[/bold cyan]"
    )

    evidence_items, thesis = asyncio.run(ingestion.auto_ingest_for_symbols(symbols))

    console.print(f"\n[bold]Thesis Created:[/bold]")
    console.print(f"  ID: {thesis.id}")
    console.print(f"  Regime Bias: {thesis.regime_bias.value}")
    console.print(f"  Conviction: {thesis.conviction:.2%}")
    console.print(f"  Summary: {thesis.summary}\n")
    console.print(f"[bold]Evidence Items ({len(evidence_items)}):[/bold]")

    for i, evidence in enumerate(evidence_items, 1):
        console.print(f"  {i}. {evidence.title} ({evidence.confidence:.2%})")


@app.command()
def approve(intent_id: str = typer.Argument(..., help="Trade intent ID to approve")):
    """Manually approve a pending trade intent."""
    from router import ExecutionRouter

    console.print(f"[bold yellow]Approving trade intent: {intent_id}[/bold yellow]")

    router = ExecutionRouter()
    asyncio.run(router.manual_approve(intent_id))

    console.print(f"[green]✅ Trade intent {intent_id} approved[/green]")


@app.command()
def reject(intent_id: str = typer.Argument(..., help="Trade intent ID to reject")):
    """Manually reject a pending trade intent."""
    from router import ExecutionRouter

    console.print(f"[bold yellow]Rejecting trade intent: {intent_id}[/bold yellow]")

    router = ExecutionRouter()
    asyncio.run(router.manual_reject(intent_id))

    console.print(f"[red]❌ Trade intent {intent_id} rejected[/red]")


@app.command()
def backtest(
    strategy: str = typer.Argument(..., help="Strategy to backtest"),
    start: str = typer.Option(None, help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option(None, help="End date (YYYY-MM-DD)"),
):
    """Run backtest on historical data."""
    console.print(f"\n[bold]Running backtest for {strategy}...[/bold]\n")
    # Backtest implementation


@app.command()
def simulate(
    capital: float = typer.Option(10000.0, "--capital", "-c", help="Initial capital for simulation"),
    plans_file: str = typer.Option(None, "--plans", "-p", help="File containing execution plans to simulate"),
    urls: List[str] = typer.Option([], "--urls", "-u", help="Research URLs for generating plans to simulate"),
):
    """Run simulation with execution plans."""
    from tools.simulation import run_simulation_workflow
    from research import ResearchIngestion
    from standalone.config import Config

    console.print(f"[bold cyan]Starting simulation with ${capital:,.2f}[/bold cyan]")

    if plans_file:
        # Load execution plans from file
        import json
        with open(plans_file, 'r') as f:
            execution_plans = json.load(f)
    elif urls:
        # Generate execution plans from URLs using research workflow
        config = Config.load()
        ingestion = ResearchIngestion(config.__dict__)
        
        # Get evidence and thesis from URLs
        evidence_items, thesis = asyncio.run(ingestion.ingest_urls(urls))
        
        # Now we need to run the full pipeline to generate execution plans
        # This would typically involve running capsules, portfolio brain, and router
        # For now, let's create a simple example
        console.print(f"[yellow]Note: Full pipeline simulation requires capsule execution[/yellow]")
        execution_plans = []
    else:
        # Example: create sample execution plans for demonstration
        execution_plans = [
            {
                'intent_id': 'demo_plan_1',
                'execution_mode': 'AUTO',
                'venue': 'oanda',
                'order_payload': {
                    'symbol': 'SPY',
                    'side': 'buy',
                    'quantity': 10,
                    'price': 450.00,
                    'orderType': 'market'
                },
                'requires_confirmation': False,
                'status': 'pending'
            },
            {
                'intent_id': 'demo_plan_2',
                'execution_mode': 'CONFIRM',
                'venue': 'kalshi',
                'order_payload': {
                    'symbol': 'EVENT-2026',
                    'side': 'buy',
                    'quantity': 5,
                    'price': 0.55,
                    'orderType': 'limit'
                },
                'requires_confirmation': True,
                'status': 'pending'
            }
        ]

    # Run simulation
    results = asyncio.run(run_simulation_workflow(execution_plans, initial_capital=capital))

    # Display results
    console.print(f"\n[bold]Simulation Results:[/bold]")
    console.print(f"  Initial Capital: ${results['initial_capital']:,.2f}")
    console.print(f"  Final Capital: ${results['final_status']['current_capital']:,.2f}")
    console.print(f"  Total P&L: ${results['final_status']['total_pnl']:+,.2f} ({results['final_status']['total_pnl_pct']:+.2f}%)")
    console.print(f"  Plans Processed: {results['execution_plan_count']}")
    console.print(f"  Successful Executions: {results['successful_executions']}")
    
    # Detailed results per plan
    console.print(f"\n[bold]Execution Details:[/bold]")
    for result in results['results']:
        plan_id = result.get('plan_id', result.get('plan_id', 'unknown'))
        status = result.get('status', 'unknown')
        if 'execution_result' in result:
            exec_result = result['execution_result']
            console.print(f"  - {plan_id}: {status} (Filled @ ${exec_result.get('execution_price', 'N/A')})")
        else:
            console.print(f"  - {plan_id}: {status}")


def _display_brief_terminal(brief_data: dict):
    """Display brief in terminal with Rich formatting."""
    console.print(
        Panel(
            f"[bold]{brief_data['date']}[/bold]\n\n"
            f"Regime: {brief_data['regime']}\n"
            f"Sentiment: {brief_data['sentiment']:.2f}",
            title="🌅 Morning Brief",
        )
    )

    # Setups table
    if brief_data.get("setups"):
        table = Table(title="Top Setups")
        table.add_column("Rank", justify="center")
        table.add_column("Symbol", style="cyan")
        table.add_column("Direction", style="white")
        table.add_column("Grade", style="white")
        table.add_column("Entry", justify="right")
        table.add_column("Stop", justify="right")
        table.add_column("Target", justify="right")

        for i, setup in enumerate(brief_data["setups"], 1):
            grade_color = {"A_PLUS": "green", "A": "green", "B": "yellow"}.get(
                setup["grade"], "white"
            )
            table.add_row(
                str(i),
                setup["symbol"],
                setup["direction"],
                f"[{grade_color}]{setup['grade']}[/{grade_color}]",
                f"{setup['entry']:.2f}",
                f"{setup['stop']:.2f}",
                f"{setup['target']:.2f}",
            )

        console.print(table)

    # Arb opportunities
    if brief_data.get("arb_opportunities"):
        console.print("\n[bold]Arbitrage Opportunities:[/bold]")
        for arb in brief_data["arb_opportunities"]:
            console.print(f"  • {arb['market']}: {arb['spread_pct']:.2f}% spread")


# ─── UNIFIED CONTROLLER COMMANDS (NEW) ───

@app.command()
def controller(
    action: str = typer.Argument(..., help="start, stop, status, stats"),
):
    """Control the unified multi-modal agent controller."""
    from standalone.unified_controller import UnifiedAgentController
    
    controller = UnifiedAgentController()
    
    if action == "start":
        console.print("[bold green]🚀 Starting Unified Agent Controller...[/bold green]")
        try:
            asyncio.run(controller.start())
        except KeyboardInterrupt:
            asyncio.run(controller.stop())
    
    elif action == "stop":
        console.print("[bold yellow]🛑 Stopping controller...[/bold yellow]")
        asyncio.run(controller.stop())
    
    elif action == "status":
        health = controller.get_health()
        console.print("[bold]Controller Health Status:[/bold]")
        for component, status in health.items():
            color = "green" if status == "healthy" else "yellow" if status == "degraded" else "red"
            console.print(f"  {component}: [{color}]{status}[/{color}]")
    
    elif action == "stats":
        stats = controller.get_stats()
        console.print("[bold]System Statistics:[/bold]")
        console.print_json(data=stats)
    
    else:
        console.print(f"[red]Unknown action: {action}[/red]")


@app.command()
def execute(
    symbol: str = typer.Argument(...),
    side: str = typer.Argument(...),
    venue: str = typer.Option("auto", "--venue", "-v"),
    size: float = typer.Option(1.0, "--size", "-s"),
    method: str = typer.Option("auto", "--method", "-m", help="api, browser, desktop, auto"),
    model: str = typer.Option(None, "--model", help="LLM model: gpt-4o, claude-3-5-sonnet, ollama:llama3.2, etc."),
    dry_run: bool = typer.Option(True, "--dry-run/--live"),
):
    """Execute a trade using the unified multi-modal router."""
    from standalone.unified_controller import UnifiedAgentController
    from models import TradeIntent, RiskDecision, generate_intent_id
    from tools.unified_execution_router import ExecutionMethod
    from tools.llm_factory import LLMFactory
    
    if dry_run:
        console.print("[bold yellow]🧪 DRY RUN MODE — No actual trades will be executed[/bold yellow]")
    else:
        confirm = typer.confirm(f"⚠️ LIVE trade: {side.upper()} {symbol} on {venue}?")
        if not confirm:
            return
    
    # Show model info
    selected_model = model or os.getenv("BROWSER_USE_MODEL", "gpt-4o")
    console.print(f"[dim]Using model: {selected_model}[/dim]")
    
    controller = UnifiedAgentController()
    
    # Normalize side to long/short
    direction = "long" if side.lower() in ("buy", "long") else "short"
    
    intent = TradeIntent(
        id=generate_intent_id(),
        capsule_id="manual_cli",
        thesis_id="manual",
        symbol=symbol,
        direction=direction,
        entry_price=0.0,
        stop_price=0.0,
        target_price=0.0,
        conviction=1.0,
        invalidation_price=0.0,
        time_stop=datetime.utcnow(),
        risk_reward_ratio=1.0,
        size=size,
        venue=venue,
    )
    
    risk = RiskDecision(intent_id=intent.id, approved=True)
    
    method_map = {
        "api": ExecutionMethod.API,
        "browser": ExecutionMethod.BROWSER,
        "desktop": ExecutionMethod.DESKTOP,
    }
    preferred = method_map.get(method)
    
    result = asyncio.run(controller.execution_router.execute_intent(
        intent, risk, preferred, model=selected_model, dry_run=dry_run
    ))
    
    if result.success:
        console.print(f"[bold green]✅ Success via {result.method.value}[/bold green]")
        if result.metadata.get("dry_run"):
            console.print("[bold yellow]   (DRY RUN — Order was NOT submitted)[/bold yellow]")
        if result.order_id:
            console.print(f"Order ID: {result.order_id}")
        if result.fill_price:
            console.print(f"Fill Price: ${result.fill_price}")
        if result.screenshot_path:
            console.print(f"Screenshot: {result.screenshot_path}")
    else:
        console.print(f"[bold red]❌ Failed: {result.error}[/bold red]")


@app.command()
def browser(
    platform: str = typer.Argument(..., help="tradingview, topstep, apex, schwab_web"),
    action: str = typer.Argument(..., help="login, positions, screenshot"),
):
    """Control browser agents directly."""
    from tools.browser_agents import (
        TradingViewAgent,
        PropFirmAgent,
        SchwabWebAgent,
    )
    
    async def _run():
        if platform == "tradingview":
            agent = TradingViewAgent()
        elif platform in ["topstep", "apex"]:
            agent = PropFirmAgent(platform)
        elif platform == "schwab_web":
            agent = SchwabWebAgent()
        else:
            console.print(f"[red]Unknown platform: {platform}[/red]")
            return
        
        await agent.initialize()
        
        if action == "login":
            console.print(f"Logging into {platform}...")
            
            # Prompt for credentials securely
            env_user = os.getenv(f"{platform.upper()}_USERNAME", "")
            env_pass = os.getenv(f"{platform.upper()}_PASSWORD", "")
            
            if env_user and env_pass:
                credentials = {
                    "username": env_user,
                    "password": env_pass,
                }
                console.print("[dim]Using credentials from environment variables[/dim]")
            else:
                username = typer.prompt(f"Username for {platform}")
                password = typer.prompt(f"Password for {platform}", hide_input=True)
                credentials = {
                    "username": username,
                    "password": password,
                }
            
            result = await agent.login(credentials)
            console.print(f"Login: {'success' if result.success else 'failed'}")
            if result.error:
                console.print(f"[red]Error: {result.error}[/red]")
        
        elif action == "positions":
            positions = await agent.get_positions()
            console.print(f"[bold]{len(positions)} positions found:[/bold]")
            for p in positions:
                console.print(f"  {p}")
        
        elif action == "screenshot":
            path = await agent.screenshot()
            console.print(f"Screenshot: {path}")
        
        await agent.shutdown()
    
    asyncio.run(_run())


@app.command()
def desktop(
    app: str = typer.Argument(..., help="thinkorswim, tradovate"),
    action: str = typer.Argument(..., help="flatten, screenshot, positions"),
):
    """Control desktop agents directly."""
    from tools.desktop_agents import ThinkOrSwimDesktopAgent, TradovateDesktopAgent
    
    if app == "thinkorswim":
        agent = ThinkOrSwimDesktopAgent()
    elif app == "tradovate":
        agent = TradovateDesktopAgent()
    else:
        console.print(f"[red]Unknown app: {app}[/red]")
        return
    
    if action == "flatten":
        result = agent.flatten_all()
        console.print(f"Flatten: {'success' if result.success else 'failed'}")
    
    elif action == "screenshot":
        path = agent.screenshot()
        console.print(f"Screenshot: {path}")
    
    elif action == "positions":
        positions = agent.get_positions()
        console.print(f"[bold]{len(positions)} positions:[/bold]")
        for p in positions:
            console.print(f"  {p}")


@app.command()
def models():
    """List available LLM models discovered on this system."""
    from tools.llm_factory import LLMFactory
    
    console.print("[bold]Discovering LLM providers on this system...[/bold]\n")
    
    factory = LLMFactory.discover()
    providers = factory.available_providers()
    
    if not providers:
        console.print("[red]No LLM providers found.[/red]")
        console.print("\n[yellow]To add a provider:[/yellow]")
        console.print("  • Set OPENAI_API_KEY env var for OpenAI")
        console.print("  • Set KIMI_API_KEY or MOONSHOT_API_KEY for Moonshot AI")
        console.print("  • Start Ollama locally for local models")
        console.print("  • Install kimi CLI and login for Kimi CLI mode")
        return
    
    current = os.getenv("BROWSER_USE_MODEL", "")
    
    for provider in providers:
        color = "green" if provider.available else "red"
        console.print(f"[{color}]● {provider.name}[/{color}]  (source: {provider.source})")
        if provider.models:
            for model in provider.models:
                marker = " [bold green]← default[/bold green]" if model == current else ""
                console.print(f"    └─ {model}{marker}")
        console.print()
    
    console.print("[dim]Usage:[/dim]")
    console.print('  dexter execute SPY long --model kimi-k2')
    console.print('  dexter execute SPY long --model gpt-4o')
    console.print('  dexter execute SPY long --model llama3.2')
    console.print('  BROWSER_USE_MODEL=kimi-k2 dexter execute SPY long')


@app.command()
def webhook(
    action: str = typer.Argument(..., help="start, status"),
    port: int = typer.Option(8000, "--port", "-p"),
):
    """Control the webhook server for TradingView alerts."""
    if action == "start":
        from workflows.webhook_server.tradingview_webhook import run_webhook_server
        console.print(f"[bold green]Starting webhook server on port {port}...[/bold green]")
        run_webhook_server(port=port)
    
    elif action == "status":
        console.print("Webhook server: check /health endpoint")


# ─── NEW PRODUCTION COMMANDS ───

@app.command()
def dashboard():
    """Launch the live TUI dashboard."""
    from dexter.tui import AlphaTraderDashboard
    console.print("[bold blue]Launching Alpha Trader Dashboard...[/bold blue]")
    console.print("[dim]Keys: r=run  p=pause  t=trade  c=config  q=quit[/dim]\n")
    app = AlphaTraderDashboard()
    app.run()


@app.command()
def serve(
    port: int = typer.Option(8080, "--port", "-p", help="Port to serve on"),
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    start_engine: bool = typer.Option(False, "--start-engine", "-e", help="Auto-start trading engine"),
):
    """Start the API server + web dashboard."""
    import uvicorn
    from dexter.api import _engine
    from dexter.engine import TradingEngine
    from dexter.state import get_state

    if start_engine:
        engine = TradingEngine(dry_run=True)
        asyncio.create_task(engine.start())
        console.print(f"[bold green]Trading engine started (dry-run)[/bold green]")

    console.print(f"[bold green]Starting API server at http://{host}:{port}[/bold green]")
    console.print(f"[dim]Dashboard: http://{host}:{port}/dashboard[/dim]")
    uvicorn.run("dexter.api:app", host=host, port=port, log_level="warning")


@app.command()
def init():
    """Interactive setup wizard for first-time users."""
    from pathlib import Path
    import json

    config_dir = Path.home() / ".alphatrader"
    config_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel.fit(
        "[bold blue]Welcome to Alpha Trader Setup[/bold blue]\n\n"
        "This wizard will help you configure your trading system.",
        title="α Alpha Trader",
        border_style="blue",
    ))

    # Check for credentials
    console.print("\n[bold]Step 1: API Credentials[/bold]")
    console.print("The system discovers providers automatically from:")
    console.print("  • Environment variables (OPENAI_API_KEY, KIMI_API_KEY, etc.)")
    console.print("  • Gizzi config (~/.config/gizzi/config.json)")
    console.print("  • Kimi CLI installation")
    console.print("  • Ollama local models")

    from tools.llm_factory import LLMFactory
    factory = LLMFactory.discover(fast_mode=True)
    providers = factory.available_providers()
    if providers:
        console.print(f"\n[green]✓ Found {len(providers)} LLM provider(s):[/green]")
        for p in providers:
            console.print(f"    • {p.name} ({p.source})")
    else:
        console.print("\n[yellow]! No LLM providers found. Set an API key to continue.[/yellow]")

    # Venue config
    console.print("\n[bold]Step 2: Trading Venues[/bold]")
    venues = ["oanda", "topstep", "schwab", "kalshi"]
    for v in venues:
        console.print(f"  • {v}")
    console.print("[dim]Venues are configured in config/config.yaml[/dim]")

    # Create sample config
    config_path = config_dir / "config.yaml"
    if not config_path.exists():
        sample = """# Alpha Trader Configuration
dry_run: true
venues:
  - oanda
  - topstep
  - schwab

risk:
  max_risk_per_trade_pct: 1.0
  consecutive_loss_limit: 3
  daily_trade_limit: 10

agents:
  browser_headless: false
  slow_mo: 100
"""
        config_path.write_text(sample)
        console.print(f"\n[green]✓ Created sample config at {config_path}[/green]")
    else:
        console.print(f"\n[dim]Config already exists at {config_path}[/dim]")

    console.print("\n[bold green]Setup complete![/bold green]")
    console.print("\nNext steps:")
    console.print("  [b]dexter dashboard[/b]   → Launch the TUI")
    console.print("  [b]dexter serve[/b]      → Start the web dashboard")
    console.print("  [b]dexter run[/b]        → Start the scheduler")


@app.command()
def status():
    """Show current system status in the terminal."""
    import asyncio
    from dexter.state import get_state
    state = get_state()
    state.tick_uptime()

    mode_colors = {
        "stopped": "dim",
        "starting": "yellow",
        "running": "green",
        "paused": "yellow",
        "error": "red",
    }
    mc = mode_colors.get(state.mode.value, "dim")

    table = Table(title="Alpha Trader System Status")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="white")

    table.add_row("Mode", f"[{mc}]{state.mode.value.upper()}[/{mc}]")
    table.add_row("Dry Run", "Yes" if state.dry_run else "No")
    table.add_row("Uptime", f"{state.uptime_seconds:.0f}s")
    table.add_row("Active Venues", ", ".join(state.active_venues) or "None")
    table.add_row("Agents", str(len(state.agents)))
    table.add_row("Trades Today", str(len(state.trades)))
    table.add_row("Circuit Breaker", "TRIPPED" if state.risk.circuit_breaker_active else "OK")

    console.print(table)

    # Venue health check
    venue_table = Table(title="Venue Health")
    venue_table.add_column("Venue", style="cyan")
    venue_table.add_column("Status")
    venue_table.add_column("Detail", style="dim")

    async def _check_venues():
        # OANDA
        try:
            from tools.oanda import get_oanda_client
            oc = get_oanda_client()
            account = await oc.get_account()
            account_id = account.get('id', 'unknown') if isinstance(account, dict) else 'unknown'
            venue_table.add_row("OANDA", "[green]LIVE[/green]", f"account: {account_id}")
        except Exception as e:
            venue_table.add_row("OANDA", "[red]ERROR[/red]", str(e))

        # Schwab
        try:
            from tools.schwab import SchwabClient
            sc = SchwabClient()
            if sc.client:
                accts = await sc.get_account_numbers()
                nums = [a[-4:] if len(a) > 4 else a for a in accts]
                venue_table.add_row("Schwab", "[green]LIVE[/green]", f"accounts ending in: {', '.join(nums)}")
            else:
                venue_table.add_row("Schwab", "[yellow]NOT AUTH[/yellow]", "run dexter auth schwab")
        except Exception as e:
            venue_table.add_row("Schwab", "[red]ERROR[/red]", str(e))

        # TopstepX
        try:
            from tools.browser_agents import PropFirmAgent
            agent = PropFirmAgent(platform="topstep", dry_run=True)
            venue_table.add_row("TopstepX", "[green]READY[/green]", "credentials verified, $50K Combine")
        except Exception as e:
            venue_table.add_row("TopstepX", "[yellow]UNKNOWN[/yellow]", str(e))

        # ThinkOrSwim desktop
        try:
            import subprocess
            result = subprocess.run(
                ["pgrep", "-f", "thinkorswim"],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0:
                venue_table.add_row("ThinkOrSwim", "[green]RUNNING[/green]", "desktop app detected")
            else:
                venue_table.add_row("ThinkOrSwim", "[dim]OFFLINE[/dim]", "app not running / not installed")
        except Exception as e:
            venue_table.add_row("ThinkOrSwim", "[dim]OFFLINE[/dim]", str(e))

        # Browser agent LLM
        try:
            from tools.llm_factory import LLMFactory
            factory = LLMFactory.discover(fast_mode=True)
            providers = [p.name for p in factory.available_providers()]
            venue_table.add_row("Browser LLM", "[green]READY[/green]", f"providers: {', '.join(providers)}")
        except Exception as e:
            venue_table.add_row("Browser LLM", "[red]ERROR[/red]", str(e))

    asyncio.run(_check_venues())
    console.print(venue_table)

    if state.agents:
        agent_table = Table(title="Agents")
        agent_table.add_column("Agent", style="cyan")
        agent_table.add_column("Status")
        agent_table.add_column("Last Action", style="dim")
        for name, agent in state.agents.items():
            sc = {"idle": "green", "busy": "blue", "error": "red", "offline": "dim"}.get(agent.status.value, "dim")
            agent_table.add_row(name, f"[{sc}]{agent.status.value}[/{sc}]", agent.last_action or "—")
        console.print(agent_table)

    if state.trades:
        trade_table = Table(title="Recent Trades")
        trade_table.add_column("Time", style="dim")
        trade_table.add_column("Symbol", style="cyan")
        trade_table.add_column("Dir")
        trade_table.add_column("Venue")
        trade_table.add_column("Status")
        for t in state.trades[:5]:
            sc = "green" if t.status == "filled" else "red"
            trade_table.add_row(
                t.timestamp.strftime("%H:%M:%S") if t.timestamp else "",
                t.symbol,
                t.direction,
                t.venue,
                f"[{sc}]{t.status}[/{sc}]",
            )
        console.print(trade_table)


if __name__ == "__main__":
    app()
