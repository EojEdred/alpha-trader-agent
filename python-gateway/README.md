# Python Tools Gateway

This service provides a lightweight HTTP gateway for running Python tools and
returning structured results. It is intended for integrating legacy or
Python-native tools into the A2rchitech ecosystem.

## Quick Start

```
python -m venv .venv
. .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

## Register and Execute a Tool

Register a tool (entrypoint uses `module:function`):

```
curl -X POST http://localhost:8000/v1/tools/register \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "echo",
    "name": "Echo",
    "description": "Return the payload",
    "entrypoint": "tools.echo:run",
    "input_schema": {"type": "object"},
    "output_schema": {"type": "object"}
  }'
```

Execute the tool:

```
curl -X POST http://localhost:8000/v1/tools/execute \
  -H 'Content-Type: application/json' \
  -d '{
    "tool_id": "echo",
    "input": {"ping": "pong"},
    "identity_id": "user-1",
    "session_id": "session-1",
    "tenant_id": "tenant-1"
  }'
```

## Notes

- This gateway currently trusts registered tools and does not enforce policy.
  Wire it to `a2rchitech-policy` before production use.
- Tool handlers must return a JSON-serializable dict (or `None`).
- The service captures stdout/stderr for observability.
