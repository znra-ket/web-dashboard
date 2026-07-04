# web-xray-dashboard

Local mono-repo skeleton for the web-xray dashboard backend and node agent.

## Test

```powershell
python -m pip install -e ".[test]"
pytest backend/tests agent/tests
python scripts/check_phase_gate.py --phase phase_0
```

`phase_1` is expected to stay `NO-GO` until the foundation/schema/transaction prompts are implemented and tested.
