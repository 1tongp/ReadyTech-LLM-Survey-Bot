# Full-Stack Survey Bot (React + Ant Design, FastAPI, SQLite)

A simple, professional survey system where:
- Admin creates surveys, guidelines, and shareable links.
- Participants answer via a tokenized link, navigate with previous/next, flag questions, edit/update/delete answers, and submit.
- Admin views responses and exports CSV.
- LLM based answer scorer.

## Prereqs
- Node 18+ and npm
- Python 3.10+
- macOS/Linux/Windows

## 1) Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.sample .env && # edit ADMIN_API_KEY if desired
uvicorn main:app --reload --port 8000
```
OpenAPI docs: http://localhost:8000/docs

## 2) Frontend
```bash
cd ../frontend
cp .env.sample .env # confirm VITE_API_BASE if needed
npm install
npm run dev
```

## 3) Use the App
- Visit http://localhost:5173
- Go to **Admin** → enter your `Admin Key` (matches `ADMIN_API_KEY` in backend .env)
- Create a survey + questions + guideline, then **Generate Shareable Link**.
- Open `/take/<token>` to fill the survey.

## Notes on LLM scoring
- `backend/llm_scorer.py` exposes a stable `score_answer(answer_text, guideline)` interface.
- Replace the stub with your preferred model (OpenAI/Azure/Bedrock, etc.).
- The API automatically re-scores edited answers.

## Security
- Admin endpoints require header `Admin Key`.
- Public endpoints are token-based per-link and can be revoked by admin.

## Edge Cases Considered
- Link revocation / invalid tokens
- Saving drafts vs final submission
- Edit/update/delete answers before submission
- Flagging questions for admin review
- CSV export sorted by respondent and question order
- CORS configurable via backend `.env`

## Folder Structure
```
survey-bot-react-python/
  backend/   # FastAPI + SQLite
  frontend/  # Vite + React + AntD
```
