# web-xray-dashboard backend

Foundation backend for the local web-xray-dashboard.

## Run

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

## Test

```powershell
cd backend
python -m unittest discover -s tests
```
