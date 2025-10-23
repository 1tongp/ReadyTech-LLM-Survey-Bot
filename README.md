# Full-Stack Survey Bot (React + Ant Design, FastAPI, SQLite)

A simple, professional survey system where:
A small, production-style survey system:

- **Admin**
  - Create surveys with **per-question guidelines** (1:1 question↔guideline).
  - Add/delete questions; deleting a question also removes its guideline and related answers.
  - Generate a **shareable link** (token). If one already exists, the existing active token is returned.
  - View responses and **export CSV** (sorted by respondent then question order).
- **Participant**
  - Open `/take/<token>` via the share link (or paste a token into the input to navigate there).
  - Navigate **Previous/Next**, **Save**, **Flag/Unflag**, **Delete** individual answers, and **Submit**.
  - **Edit/update** answers at any time before submitting.
  - **Chat mode** (`/take/<token>/chat`): a simple left/right chat UI where the “bot” announces actions (saved/flagged/navigation) and shows score + rationale after saves.
- **LLM Scoring (0–5)**
  - Scores answers against **question-specific guidelines**.
  - Detects “refer to previous/next/last/first question” and absolute refs (e.g. “Q2”), pulls that answer into the scoring context, and warns on non-existent refs.
  - Auto **re-scores dependent answers** if a referenced answer is updated.
  - **Low-quality** answers are marked (threshold configurable) and the UI nudges users to improve.
  - Pluggable design so we can swap to a cheaper LLM later.
- **Testing & CI**
  - **Backend unit tests** (pytest + httpx) and **GitHub Actions CI** (runs tests, publishes coverage/JUnit).
  - **Playwright E2E**: admin creates a survey, generates link, participant answers in form & chat modes, submit, and cleanup. Screenshots saved during the flow.
  - **Frontend CI**: ESLint + Prettier checks on every push/PR that touches `frontend/**`.


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

---

## 2) Frontend
```bash
cd ../frontend
cp .env.sample .env 
npm install
npm run dev
```

### 2.1 Code Style（ESLint & Prettier）
The project uses **ESLint v9 (Flat Config)** + **Prettier**.

Run these in `frontend/`:

```bash
# Lint (no warnings allowed)
npm run lint

# Auto-fix ESLint issues
npm run lint:fix

# Check Prettier formatting (read-only)
npm run format:check

# Write Prettier formatting changes
npm run format
```

Configs:
- ESLint Flat Config: `frontend/eslint.config.js` (or `eslint.config.mjs`)
- Prettier config: `frontend/.prettierrc`
- Ignore list: `frontend/.prettierignore`

VS Code recommended settings:
```json
// frontend/.vscode/settings.json
{
  "editor.formatOnSave": true,
  "editor.defaultFormatter": "esbenp.prettier-vscode",
  "editor.codeActionsOnSave": { "source.fixAll.eslint": true }
}
```

---
## 3) Use the App
- Visit http://localhost:5173
- Go to **Admin** → enter your `Admin Key` (matches `ADMIN_API_KEY` in backend .env)
- Create a survey + questions + guideline, then **Generate Shareable Link**.
- Open `/take/<token>` to fill the survey.

---

## 4) Testing

### Backend unit tests (from `backend/`)
```bash
python -m pytest -q
```
> In CI we also generate `coverage.xml` and `pytest-report.xml`

### Playwright E2E (from `frontend/`)

Start the servers in two terminals:

**Terminal A – backend**
```bash
cd backend
export ADMIN_API_KEY=your-admin-key
export ORIGINS=http://localhost:5173
uvicorn main:app --port 8000
```

**Terminal B – frontend**
```bash
cd frontend
export VITE_API_BASE=http://127.0.0.1:8000
npm run build && npm run preview   # http://localhost:5173
```

**Terminal C – E2E**
```bash
cd frontend
# one-time:
npx playwright install --with-deps

# run tests:
npm run e2e:test

# view the HTML report:
npx playwright show-report
```

Screenshots from the E2E flow are saved under `frontend/e2e-screens/`.

---

## CI
- **backend-ci**: triggered on changes to `backend/**`; runs Python tests and uploads Coverage/JUnit.
- **frontend-ci**: triggered on changes to `frontend/**`; runs ESLint (`npm run lint`) and Prettier check (`npm run format:check`).
- Both workflows support manual trigger via `workflow_dispatch`.

---

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

## Folder layout
```
<repo>/
  backend/     # FastAPI + SQLite + LLM scorer + pytest
  frontend/    # React + AntD + Vite + Playwright E2E
```
-----

## Demo Survey below

Demo Survey
Survey title: ReadyTech Demo

Survey description: 
```
Describe a time you improved a process using automation or data. What was the problem, what did you do, and what was the impact?
```

Q1: 
``` 
Describe a time you improved a process using automation or data. What was the problem, what did you do, and what was the impact?
```

Q1 Guideline: 
```
5 – Excellent: Clear before/after contrast; concrete metrics (e.g., time/cost/error reduction); shows approach (tools/steps), trade-offs, and a brief reflection.
4 – Strong: Has approach + metrics or strong qualitative impact; minor detail gaps.
3 – Adequate: Describes action and outcome but missing metrics or not tied to business value.
2 – Weak: Vague actions; unclear outcome; no evidence of impact.
1 – Minimal: Mentions a tool/idea but no real scenario or result.
0 – Off-topic/empty.
Bonus: STAR structure, names tools, quantifies impact.
```

Q2: 
```
Design a simple survey bot architecture using React + Ant Design (frontend) and FastAPI + SQLite (backend). Include link-based access, per-question guidelines, LLM scoring, and CSV export.
```

Q2 Guideline:
```
5 – Excellent: Names key components and data model; clear API endpoints; explains LLM scoring flow (prompt, guideline context, persistence); covers security (admin key, token revocation, CORS), pagination/export, and error handling.
4 – Strong: Covers most pieces but light on either security or scoring details.
3 – Adequate: Mentions frontend/backend and rough endpoints; lacks model or scoring specifics.
2 – Weak: Vague block diagram; misses core entities or flows.
1 – Minimal: Buzzwords only.
0 – Off-topic/empty.
```





Q1 Answer: 
```
Our QA regression suite took 2.5 hrs and blocked deploys. I built a Playwright smoke subset (top 30 flows) and scheduled it in CI on each PR, with flaky-test quarantine + alerts. I added a dashboard for pass rate and runtime. Result: PR checks ran in ~6 min, caught 3 critical bugs pre-merge in the first month, and weekly full regressions dropped from 2.5 hrs → 1.4 hrs—saving ~6 engineer-hours/week. Trade-off: a few edge cases moved to nightly. Lead time to prod improved by ~18%.
```

Q2 Answer:
```
Frontend: routes /admin, /take/:token, /take/:token/chat; components for survey table + filters, create form, detail drawer, take survey with save/next/submit, chat mode with score preview.
Backend: models Survey, Question, Guideline, Link(token), Response, Answer(score,rationale).
Admin endpoints (Admin-Key): create/list/detail surveys; create/revoke links; update guideline; export CSV.
Public endpoints (token): fetch survey, start response, save answers, submit.
Scoring: on save, call LLM with question + guideline + referenced answers; store score 0–5 and rationale; re-score dependent answers after edits.
Security: Admin-Key for admin routes; token for public; CORS restricted; tokens revocable. Export: order by respondent then question order; stream CSV.
```