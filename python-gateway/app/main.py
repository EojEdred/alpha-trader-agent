from __future__ import annotations

import contextlib
import importlib
import inspect
import io
import time
import traceback
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="A2rchitech Python Gateway", version="0.1.0")


class ToolDefinition(BaseModel):
    id: str
    name: str
    description: str = ""
    entrypoint: str = Field(
        ..., description="Python entrypoint in the form module:function"
    )
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    side_effects: list[str] = Field(default_factory=list)
    idempotency_behavior: str = "idempotent"
    safety_tier: str = "safe"


class ToolExecutionRequest(BaseModel):
    tool_id: str
    input: Dict[str, Any]
    identity_id: str
    session_id: str
    tenant_id: str
    trace_id: Optional[str] = None
    idempotency_key: Optional[str] = None


class ToolExecutionResult(BaseModel):
    execution_id: str
    tool_id: str
    input: Dict[str, Any]
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    timestamp: int


@dataclass
class RegisteredTool:
    definition: ToolDefinition


TOOLS: Dict[str, RegisteredTool] = {}


@app.get("/v1/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/tools")
def list_tools() -> Dict[str, ToolDefinition]:
    return {tool_id: tool.definition for tool_id, tool in TOOLS.items()}


@app.post("/v1/tools/register")
def register_tool(definition: ToolDefinition) -> Dict[str, str]:
    TOOLS[definition.id] = RegisteredTool(definition=definition)
    return {"status": "registered", "tool_id": definition.id}


@app.post("/v1/tools/execute", response_model=ToolExecutionResult)
async def execute_tool(request: ToolExecutionRequest) -> ToolExecutionResult:
    tool = TOOLS.get(request.tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="tool not found")

    try:
        module_name, func_name = tool.definition.entrypoint.split(":", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid entrypoint format") from exc

    try:
        module = importlib.import_module(module_name)
        handler = getattr(module, func_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"entrypoint load failed: {exc}") from exc

    if not callable(handler):
        raise HTTPException(status_code=500, detail="entrypoint is not callable")

    stdout = io.StringIO()
    stderr = io.StringIO()
    start = time.monotonic()
    error: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    exit_code = 0

    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            result = handler(request.input)
            if inspect.isawaitable(result):
                result = await result
            if result is not None and not isinstance(result, dict):
                raise TypeError("tool handlers must return a dict or None")
            output = result
        except Exception as exc:  # noqa: BLE001
            error = "".join(traceback.format_exception(exc))
            exit_code = 1

    duration_ms = int((time.monotonic() - start) * 1000)

    return ToolExecutionResult(
        execution_id=str(uuid.uuid4()),
        tool_id=request.tool_id,
        input=request.input,
        output=output,
        error=error,
        stdout=stdout.getvalue(),
        stderr=stderr.getvalue(),
        exit_code=exit_code,
        execution_time_ms=duration_ms,
        timestamp=int(time.time()),
    )
