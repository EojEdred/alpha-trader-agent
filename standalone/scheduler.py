"""
Scheduler - APScheduler-based workflow scheduling

Schedules:
- 04:00 ET: daily-research-cycle
- 06:00 ET: morning-report
- Every 5 min: continuous-monitoring (market hours only)
"""

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from functools import wraps
from loguru import logger
import pytz

from dexter.state import get_state, AgentStatus

ET = pytz.timezone('America/New_York')


def _job_wrapper(agent_id: str):
    """Decorator that updates SystemState when a scheduled job runs."""
    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            state = get_state()
            state.update_agent(agent_id, AgentStatus.BUSY, "running")
            state.add_log(f"Job started: {agent_id}")
            try:
                return await func(self, *args, **kwargs)
            except Exception as e:
                state.update_agent(agent_id, AgentStatus.ERROR, error=str(e))
                state.add_log(f"Job error: {agent_id} — {e}")
                raise
            finally:
                state.update_agent(agent_id, AgentStatus.IDLE)
                state.add_log(f"Job finished: {agent_id}")
        return wrapper
    return decorator

# Feature flags — CONSERVATIVE REBUILD: futures DISABLED, options pre-market ONLY
ENABLE_PROP_FIRM = False   # DISABLED: TopstepX combine is blown ($47,936 < $48,000 floor)
ENABLE_OPTIONS = True      # ENABLED: Schwab pre-market gap-entry + options position monitor
ENABLE_MIDDAY_SCALPER = False  # DISABLED: no mid-day rotation, only 9:28 entry
ENABLE_QQQ_VWAP_BOUNCE = True  # ENABLED: intraday QQQ VWAP-reclaim option scalps
ENABLE_BB_VWAP_REVERSAL = True  # ENABLED: intraday SPY/QQQ/TSLA BB/VWAP/volume reversal scalps


class Scheduler:
    """Workflow scheduler using APScheduler."""

    def __init__(self, orchestrator, config):
        self.orchestrator = orchestrator
        self.config = config
        self.scheduler = AsyncIOScheduler(timezone=ET)
        self._setup_jobs()

    def _setup_jobs(self):
        """Configure scheduled jobs."""

        # Daily Research Cycle - 4:00 AM ET
        self.scheduler.add_job(
            self._run_daily_research,
            CronTrigger(hour=4, minute=0, timezone=ET),
            id='daily-research-cycle',
            name='Daily Research Cycle',
            misfire_grace_time=300,
            coalesce=True
        )

        # Morning Report - 6:00 AM ET
        self.scheduler.add_job(
            self._run_morning_report,
            CronTrigger(hour=6, minute=0, timezone=ET),
            id='morning-report',
            name='Morning Report',
            misfire_grace_time=300,
            coalesce=True
        )

        # Continuous Monitoring - Every 5 minutes during market hours (9:30 AM - 4:00 PM ET, Mon-Fri)
        self.scheduler.add_job(
            self._run_monitoring,
            CronTrigger(
                day_of_week='mon-fri',
                hour='9-15',
                minute='*/5',
                timezone=ET
            ),
            id='continuous-monitoring',
            name='Continuous Monitoring',
            misfire_grace_time=60,
            coalesce=True
        )

        # Autonomous Scalper - Every 5 minutes during market hours
        self.scheduler.add_job(
            self._run_scalper,
            CronTrigger(
                day_of_week='mon-fri',
                hour='9-15',
                minute='2-59/5',  # Offset by 2 mins from monitoring
                timezone=ET
            ),
            id='autonomous-scalper',
            name='Autonomous Scalper Agent',
            misfire_grace_time=60,
            coalesce=True
        )

        # Forex Builder — DISABLED (not set up)
        # self.scheduler.add_job(...)

        # DOM Inspector — refresh selectors before trading hours
        self.scheduler.add_job(
            self._run_dom_inspector,
            CronTrigger(
                day_of_week='sun',
                hour=17,
                minute=30,
                timezone=ET
            ),
            id='dom-inspector-sun',
            name='DOM Inspector (Sun Pre-Market)',
            misfire_grace_time=300,
            coalesce=True
        )
        self.scheduler.add_job(
            self._run_dom_inspector,
            CronTrigger(
                day_of_week='mon-thu',
                hour=8,
                minute=30,
                timezone=ET
            ),
            id='dom-inspector-weekday',
            name='DOM Inspector (Weekday Pre-Market)',
            misfire_grace_time=300,
            coalesce=True
        )

        # ─── PROP FIRM JOBS — OVERNIGHT SESSION ONLY (6 PM - 5 AM ET) ───
        if ENABLE_PROP_FIRM:
            # Evening session: 6:00 PM - 11:59 PM (Sun-Thu)
            self.scheduler.add_job(
                self._run_prop_firm_scalper,
                CronTrigger(
                    day_of_week='sun,mon,tue,wed,thu',
                    hour='18-23',
                    minute='*/3',
                    timezone=ET
                ),
                id='prop-firm-scalper-evening',
                name='Prop Firm Scalper (Evening 6PM-12AM)',
                misfire_grace_time=60,
                coalesce=True
            )
            # Early morning session: 12:00 AM - 4:59 AM (Mon-Fri)
            self.scheduler.add_job(
                self._run_prop_firm_scalper,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour='0-4',
                    minute='*/3',
                    timezone=ET
                ),
                id='prop-firm-scalper-early',
                name='Prop Firm Scalper (Early 12AM-5AM)',
                misfire_grace_time=60,
                coalesce=True
            )
            # Day session: 4:00 AM - 4:59 PM ET (Mon-Fri) — CME active hours
            self.scheduler.add_job(
                self._run_prop_firm_scalper,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour='4-16',
                    minute='*/3',
                    timezone=ET
                ),
                id='prop-firm-scalper-day',
                name='Prop Firm Scalper (Day 4AM-5PM)',
                misfire_grace_time=60,
                coalesce=True
            )
            # Late night gap fill: 11:00 PM - 11:59 PM ET (Sun-Thu)
            self.scheduler.add_job(
                self._run_prop_firm_scalper,
                CronTrigger(
                    day_of_week='sun,mon,tue,wed,thu',
                    hour='23',
                    minute='*/3',
                    timezone=ET
                ),
                id='prop-firm-scalper-late',
                name='Prop Firm Scalper (Late 11PM-12AM)',
                misfire_grace_time=60,
                coalesce=True
            )
            # Position Monitor — every minute during overnight hours
            self.scheduler.add_job(
                self._run_position_monitor,
                CronTrigger(
                    day_of_week='sun,mon,tue,wed,thu',
                    hour='18-23',
                    minute='*',
                    timezone=ET
                ),
                id='position-monitor-evening',
                name='Position Monitor (Evening 6PM-12AM)',
                misfire_grace_time=30,
                coalesce=True
            )
            self.scheduler.add_job(
                self._run_position_monitor,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour='0-4',
                    minute='*',
                    timezone=ET
                ),
                id='position-monitor-early',
                name='Position Monitor (Early 12AM-5AM)',
                misfire_grace_time=30,
                coalesce=True
            )
            # Position Monitor — day session (Mon-Fri 4AM-5PM)
            self.scheduler.add_job(
                self._run_position_monitor,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour='4-16',
                    minute='*',
                    timezone=ET
                ),
                id='position-monitor-day',
                name='Position Monitor (Day 4AM-5PM)',
                misfire_grace_time=30,
                coalesce=True
            )
            # Position Monitor — late night gap fill (Sun-Thu 11PM-12AM)
            self.scheduler.add_job(
                self._run_position_monitor,
                CronTrigger(
                    day_of_week='sun,mon,tue,wed,thu',
                    hour='23',
                    minute='*',
                    timezone=ET
                ),
                id='position-monitor-late',
                name='Position Monitor (Late 11PM-12AM)',
                misfire_grace_time=30,
                coalesce=True
            )

        # ─── OPTIONS SCALPER — Every 2 minutes, rotating SPY → QQQ → TSLA ───
        if ENABLE_OPTIONS:
            # Pre-market gap entry — fires once at 9:28 AM ET for 9:30 open
            self.scheduler.add_job(
                self._run_premarket_gap_entry,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour=9,
                    minute=28,
                    timezone=ET
                ),
                id='options-premarket-entry',
                name='Options Pre-Market Gap Entry (9:28 AM)',
                misfire_grace_time=120,
                coalesce=True
            )
            
            # ─── QQQ VWAP BOUNCE SCALPER ───
            if ENABLE_QQQ_VWAP_BOUNCE:
                self.scheduler.add_job(
                    self._run_qqq_vwap_bounce,
                    CronTrigger(
                        day_of_week='mon-fri',
                        hour='9-15',
                        minute='*/2',
                        timezone=ET
                    ),
                    id='qqq-vwap-bounce',
                    name='QQQ VWAP Bounce Scalper',
                    misfire_grace_time=60,
                    coalesce=True
                )

            # ─── BB/VWAP/VOLUME REVERSAL SCALPER ───
            if ENABLE_BB_VWAP_REVERSAL:
                self.scheduler.add_job(
                    self._run_bb_vwap_reversal_scalper,
                    CronTrigger(
                        day_of_week='mon-fri',
                        hour='9-15',
                        minute='1-59/2',  # offset 1 min from VWAP bounce
                        timezone=ET
                    ),
                    id='bb-vwap-reversal',
                    name='BB/VWAP Reversal Scalper (SPY/QQQ/TSLA)',
                    misfire_grace_time=60,
                    coalesce=True
                )

            # MID-DAY SCALPER DISABLED — only pre-market gap entry
            if ENABLE_MIDDAY_SCALPER:
                self.scheduler.add_job(
                    self._run_options_scalper_rotating,
                    CronTrigger(
                        day_of_week='mon-fri',
                        hour='9-15',
                        minute='*/2',
                        timezone=ET
                    ),
                    id='options-scalper',
                    name='Options Scalper (SPY/QQQ/TSLA)',
                    misfire_grace_time=60,
                    coalesce=True
                )

            # ─── SCHWAB TOKEN HEALTH CHECK ───
            self.scheduler.add_job(
                self._run_schwab_token_health_check,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour='4-16',
                    minute=0,
                    timezone=ET
                ),
                id='schwab-token-health',
                name='Schwab Token Health Check',
                misfire_grace_time=300,
                coalesce=True
            )

            # ─── OPTIONS POSITION MONITOR — Every 30 seconds during equity hours ───
            self.scheduler.add_job(
                self._run_options_position_monitor,
                CronTrigger(
                    day_of_week='mon-fri',
                    hour='9-15',
                    minute='*',
                    second='*/30',
                    timezone=ET
                ),
                id='options-position-monitor',
                name='Options Profit-Locking Monitor',
                misfire_grace_time=15,
                coalesce=True
            )

        # Also run at market open and close
        self.scheduler.add_job(
            self._run_monitoring,
            CronTrigger(
                day_of_week='mon-fri',
                hour=9,
                minute=30,
                timezone=ET
            ),
            id='market-open-check',
            name='Market Open Check',
            misfire_grace_time=60
        )

        self.scheduler.add_job(
            self._run_monitoring,
            CronTrigger(
                day_of_week='mon-fri',
                hour=16,
                minute=0,
                timezone=ET
            ),
            id='market-close-check',
            name='Market Close Check',
            misfire_grace_time=60
        )

        # Agent Learning Cycle - 4:30 PM ET
        self.scheduler.add_job(
            self._run_learning,
            CronTrigger(
                day_of_week='mon-fri',
                hour=16,
                minute=30,
                timezone=ET
            ),
            id='agent-learning',
            name='Agent Self-Reflection',
            misfire_grace_time=300
        )

        # Daily Trading Review - 4:35 PM ET
        self.scheduler.add_job(
            self._run_daily_review,
            CronTrigger(
                day_of_week='mon-fri',
                hour=16,
                minute=35,
                timezone=ET
            ),
            id='daily-review',
            name='Daily Trading Review',
            misfire_grace_time=300
        )

    @_job_wrapper('daily-research')
    async def _run_daily_research(self):
        """Execute daily research cycle."""
        logger.info("Starting scheduled daily research cycle")
        try:
            await self.orchestrator.execute_workflow('daily-research-cycle-v1')
            logger.info("Daily research cycle completed")
        except Exception as e:
            logger.error(f"Daily research cycle failed: {e}")

    @_job_wrapper('morning-report')
    async def _run_morning_report(self):
        """Execute morning report generation."""
        logger.info("Starting scheduled morning report")
        try:
            await self.orchestrator.execute_workflow('morning-report-v1')
            logger.info("Morning report completed")
        except Exception as e:
            logger.error(f"Morning report failed: {e}")

    @_job_wrapper('continuous-monitoring')
    async def _run_monitoring(self):
        """Execute continuous monitoring."""
        logger.debug("Starting monitoring cycle")
        try:
            await self.orchestrator.execute_workflow('continuous-monitoring-v1')
        except Exception as e:
            logger.error(f"Monitoring cycle failed: {e}")

    @_job_wrapper('autonomous-scalper')
    async def _run_scalper(self):
        """Execute autonomous scalper agent."""
        logger.info("🤖 Starting autonomous scalper agent cycle")
        try:
            await self.orchestrator.execute_workflow('autonomous-scalper-v1')
            logger.info("🤖 Scalper cycle completed")
        except Exception as e:
            logger.error(f"🤖 Scalper cycle failed: {e}")

    @_job_wrapper('prop-firm-scalper')
    async def _run_prop_firm_scalper(self):
        """Execute prop firm scalper agent (TopstepX)."""
        logger.info("🏢 Starting prop firm scalper cycle")
        try:
            from tools.circuit_breakers import check_circuit_breakers
            cb = check_circuit_breakers()
            if cb["halted"]:
                logger.warning(f"🛑 Circuit breaker active: {cb['reason']}")
                return
            await self.orchestrator.execute_workflow('prop-firm-scalper-v1')
            logger.info("🏢 Prop firm scalper cycle completed")
        except Exception as e:
            logger.error(f"🏢 Prop firm scalper cycle failed: {e}")

    async def _run_dom_inspector(self):
        """Refresh trading platform DOM selectors."""
        logger.info("🔍 Starting DOM inspection cycle")
        try:
            from tools.dom_inspector import inspect_platform, save_selectors
            results = await inspect_platform("topstep", headless=True)
            if "error" not in results:
                save_selectors(results, "topstep")
                logger.info("🔍 DOM inspection completed — selectors refreshed")
            else:
                logger.warning(f"🔍 DOM inspection had errors: {results['error']}")
        except Exception as e:
            logger.error(f"🔍 DOM inspection failed: {e}")

    @_job_wrapper('position-monitor')
    async def _run_position_monitor(self):
        """Monitor open positions and close if needed."""
        logger.info("📊 Starting position monitor cycle")
        try:
            from tools.circuit_breakers import check_circuit_breakers
            cb = check_circuit_breakers()
            if cb.get("close_positions"):
                logger.error(f"🛑 Circuit breaker forcing close: {cb['reason']}")
                # Force close positions via direct call
                from tools.browser_agents.propfirm_agent import close_position_direct
                await close_position_direct()
                return
            await self.orchestrator.execute_workflow('position-monitor-v1')
            logger.info("📊 Position monitor cycle completed")
        except Exception as e:
            logger.error(f"📊 Position monitor cycle failed: {e}")

    async def _run_forex_builder(self):
        """Execute forex builder agent."""
        logger.info("💹 Starting Forex account builder cycle")
        try:
            await self.orchestrator.execute_workflow('forex-builder-v1')
            logger.info("💹 Forex cycle completed")
        except Exception as e:
            logger.error(f"💹 Forex cycle failed: {e}")

    @_job_wrapper('agent-learning')
    async def _run_learning(self):
        """Execute agent self-reflection cycle."""
        logger.info("🧠 Starting agent self-reflection cycle")
        try:
            await self.orchestrator.execute_workflow('agent-learning-v1')
            logger.info("🧠 Learning cycle completed")
        except Exception as e:
            logger.error(f"🧠 Learning cycle failed: {e}")

    @_job_wrapper('options-premarket-entry')
    async def _run_premarket_gap_entry(self):
        """Execute pre-market gap entry for options at 9:28 / 9:32 AM ET."""
        logger.info("📈 Starting pre-market gap entry cycle")
        try:
            from tools.circuit_breakers import check_circuit_breakers
            cb = check_circuit_breakers()
            if cb["halted"]:
                logger.warning(f"🛑 Circuit breaker active: {cb['reason']}")
                return
            from tools.options_multi_scalper import run_premarket_gap_entry
            result = await run_premarket_gap_entry(orchestrator=self.orchestrator)
            logger.info(f"📈 Pre-market gap entry complete: {result.get('count', 0)} order(s)")
        except Exception as e:
            logger.error(f"📈 Pre-market gap entry failed: {e}")

    @_job_wrapper('qqq-vwap-bounce')
    async def _run_qqq_vwap_bounce(self):
        """Execute QQQ VWAP bounce scalp during equity hours."""
        logger.info("📈 Starting QQQ VWAP bounce scalper")
        try:
            from tools.circuit_breakers import check_circuit_breakers
            cb = check_circuit_breakers()
            if cb["halted"]:
                logger.warning(f"🛑 Circuit breaker active: {cb['reason']}")
                return
            from tools.vwap_bounce_scalper import run_qqq_vwap_bounce
            result = await run_qqq_vwap_bounce()
            if result.get("action") != "none":
                logger.info(f"📈 QQQ VWAP bounce result: {result}")
            else:
                logger.info(f"📈 QQQ VWAP bounce: no entry — {result.get('reason')}")
        except Exception as e:
            logger.error(f"📈 QQQ VWAP bounce failed: {e}")

    @_job_wrapper('bb-vwap-reversal')
    async def _run_bb_vwap_reversal_scalper(self):
        """Execute BB/VWAP/volume reversal scalper during equity hours."""
        logger.info("📈 Starting BB/VWAP reversal scalper")
        try:
            from tools.circuit_breakers import check_circuit_breakers
            cb = check_circuit_breakers()
            if cb["halted"]:
                logger.warning(f"🛑 Circuit breaker active: {cb['reason']}")
                return
            from tools.bb_vwap_reversal_scalper import run_bb_vwap_reversal_scalper
            result = await run_bb_vwap_reversal_scalper(orchestrator=self.orchestrator)
            logger.info(f"📈 BB/VWAP reversal scalper complete: {result.get('count', 0)} entry(s)")
        except Exception as e:
            logger.error(f"📈 BB/VWAP reversal scalper failed: {e}")

    @_job_wrapper('options-scalper')
    async def _run_options_scalper_rotating(self):
        """Execute options scalper agent (Schwab) rotating through SPY/QQQ/TSLA."""
        logger.info("📈 Starting options scalper cycle")
        try:
            from tools.circuit_breakers import check_circuit_breakers
            cb = check_circuit_breakers()
            if cb["halted"]:
                logger.warning(f"🛑 Circuit breaker active: {cb['reason']}")
                return
            from tools.options_multi_scalper import run_options_scalper_rotating
            await run_options_scalper_rotating(orchestrator=self.orchestrator)
            logger.info("📈 Options scalper cycle completed")
        except Exception as e:
            logger.error(f"📈 Options scalper cycle failed: {e}")

    @_job_wrapper('options-position-monitor')
    async def _run_options_position_monitor(self):
        """Execute options profit-locking monitor."""
        logger.info("🔒 Starting options position monitor cycle")
        try:
            from tools.circuit_breakers import check_circuit_breakers
            cb = check_circuit_breakers()
            if cb.get("close_positions"):
                logger.error(f"🛑 Circuit breaker forcing close: {cb['reason']}")
                # The options monitor workflow will handle exits via profit-locking engine
            await self.orchestrator.execute_workflow('options-position-monitor-v1')
            logger.info("🔒 Options position monitor cycle completed")
        except Exception as e:
            logger.error(f"🔒 Options position monitor cycle failed: {e}")

    @_job_wrapper('daily-review')
    async def _run_daily_review(self):
        """Generate daily trading review report."""
        logger.info("📊 Starting daily trading review")
        try:
            from tools.daily_review import run_daily_review
            result = await run_daily_review()
            logger.info(f"📊 Daily review completed: {result.get('report_path')}")
        except Exception as e:
            logger.error(f"📊 Daily review failed: {e}")

    @_job_wrapper('schwab-token-health')
    async def _run_schwab_token_health_check(self):
        """Check Schwab token expiry and alert if reauth is needed."""
        logger.info("🔑 Starting Schwab token health check")
        try:
            from tools.schwab import check_schwab_token_health
            result = check_schwab_token_health()
            if result.get("healthy"):
                logger.info(f"🔑 Schwab token healthy: {result.get('refresh_token_hours_left')}h left")
            else:
                logger.warning(f"🔑 Schwab token issue: {result.get('alert')}")
        except Exception as e:
            logger.error(f"🔑 Schwab token health check failed: {e}")

    def start(self):
        """Start the scheduler."""
        logger.info("Starting scheduler")
        self.scheduler.start()

        # Log next run times
        for job in self.scheduler.get_jobs():
            logger.info(f"Job '{job.name}' next run: {job.next_run_time}")

    def stop(self):
        """Stop the scheduler."""
        logger.info("Stopping scheduler")
        self.scheduler.shutdown(wait=False)

    def run_now(self, workflow_id: str):
        """Trigger a workflow to run immediately."""
        job_map = {
            'daily-research-cycle-v1': self._run_daily_research,
            'morning-report-v1': self._run_morning_report,
            'continuous-monitoring-v1': self._run_monitoring,
            'prop-firm-scalper-v1': self._run_prop_firm_scalper,
            'dom-inspector-v1': self._run_dom_inspector,
            'position-monitor-v1': self._run_position_monitor,
            'options-scalper-v1': self._run_options_scalper_rotating,
            'options-position-monitor-v1': self._run_options_position_monitor,
            'bb-vwap-reversal-v1': self._run_bb_vwap_reversal_scalper,
            'daily-review-v1': self._run_daily_review,
        }

        if workflow_id in job_map:
            self.scheduler.add_job(
                job_map[workflow_id],
                'date',  # Run immediately
                id=f'{workflow_id}-manual',
                replace_existing=True
            )
            logger.info(f"Triggered manual run of {workflow_id}")
