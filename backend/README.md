# Survey Bot Backend (FastAPI + SQLite)

## Quickstart
```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.sample .env  # and set ADMIN_API_KEY
uvicorn main:app --reload --port 8000
```

The OpenAPI docs will be at http://localhost:8000/docs
