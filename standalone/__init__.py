"""
Alpha Trader Standalone Package

This package contains the standalone implementation that can run
independently while following A2rchitech patterns for future migration.
"""

from .config import Config
from .scheduler import Scheduler
from .orchestrator import WorkflowOrchestrator, WorkflowResult, ExecutionContext

__all__ = [
    'Config',
    'Scheduler',
    'WorkflowOrchestrator',
    'WorkflowResult',
    'ExecutionContext',
]
