# webxray-agent

Standalone FastAPI service for node-side script storage and execution primitives.

## Run

```powershell
cd agent
python -m uvicorn webxray_agent.main:app --reload
```

## Test

```powershell
cd agent
python -m unittest discover -s tests
```
