import os, io, uuid, sqlite3
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from db import Base, engine, get_db
from models import Survey, Question, Guideline, SurveyLink, Respondent, Answer
from schemas import *
from security import verify_admin

# Minimal URL-safe serializer fallback to avoid external dependency on itsdangerous.
# Provides dumps(obj) -> str and loads(token) -> obj with HMAC-SHA256 signature.
import json
import hmac
import hashlib
import base64

import pandas as pd
from llm_scorer import score_answer, extract_references
class URLSafeSerializer:
    def __init__(self, secret_key, salt=""):
        self.secret_key = (secret_key or "").encode("utf-8")
        self.salt = salt or ""

    def _b64(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _unb64(self, s: str) -> bytes:
        s_bytes = s.encode("ascii")
        padding = b"=" * (-len(s_bytes) % 4)
        return base64.urlsafe_b64decode(s_bytes + padding)

    def dumps(self, obj) -> str:
        payload = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = hmac.new(self.secret_key + self.salt.encode("utf-8"), payload, hashlib.sha256).digest()
        return f"{self._b64(payload)}.{self._b64(sig)}"

    def loads(self, token: str):
        try:
            payload_b64, sig_b64 = token.rsplit(".", 1)
            payload = self._unb64(payload_b64)
            sig = self._unb64(sig_b64)
        except Exception:
            raise ValueError("Invalid token format")
        expected = hmac.new(self.secret_key + self.salt.encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("Invalid signature")
        return json.loads(payload.decode("utf-8"))

Base.metadata.create_all(bind=engine)

# # ---- migrate survey-level guidelines → question-level (SQLite) ----
# def migrate_guidelines_to_question_level():
#     with engine.begin() as conn:
#         # detect if guidelines table exists
#         tables = [r[0] for r in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").all()]
#         if "guidelines" not in tables:
#             return
#         cols = conn.exec_driver_sql("PRAGMA table_info('guidelines')").all()
#         col_names = {c[1] for c in cols}
#         # If already question_id based, nothing to do
#         if "question_id" in col_names:
#             return
#         # If it's old (survey_id), rebuild
#         if "survey_id" in col_names:
#             conn.exec_driver_sql("""
#                 CREATE TABLE IF NOT EXISTS guidelines_new (
#                     id INTEGER PRIMARY KEY,
#                     question_id INTEGER NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE,
#                     content TEXT NOT NULL
#                 )
#             """)
#             # For each survey guideline, copy content to all its questions
#             conn.exec_driver_sql("""
#                 INSERT OR IGNORE INTO guidelines_new (question_id, content)
#                 SELECT q.id AS question_id, g.content
#                 FROM guidelines g
#                 JOIN questions q ON q.survey_id = g.survey_id
#             """)
#             conn.exec_driver_sql("DROP TABLE guidelines")
#             conn.exec_driver_sql("ALTER TABLE guidelines_new RENAME TO guidelines")

# migrate_guidelines_to_question_level()

def ensure_reference_columns():
    with engine.connect() as conn:
        cols = conn.exec_driver_sql("PRAGMA table_info('answers')").all()
        names = {c[1] for c in cols}
        if "referenced_question_ids" not in names:
            conn.exec_driver_sql("ALTER TABLE answers ADD COLUMN referenced_question_ids TEXT")
        if "reference_warning" not in names:
            conn.exec_driver_sql("ALTER TABLE answers ADD COLUMN reference_warning TEXT")
ensure_reference_columns()


# --- scoring low_quality helper ---
LOW_QUALITY_THRESHOLD_5 = float(os.getenv("LOW_QUALITY_THRESHOLD_5", "2.0"))

def compute_low_quality(score: Optional[float]) -> bool:
    if score is None:
        return False
    
    return score < LOW_QUALITY_THRESHOLD_5

app = FastAPI(title="Survey Bot API")

origins = os.getenv("ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_question_text_map(db: Session, survey_id: int) -> dict[int, str]:
    qs = db.execute(
        select(Question).where(Question.survey_id==survey_id).order_by(Question.order_index)
    ).scalars().all()
    # map visible numbers (order_index+1) -> text
    return {q.order_index + 1: q.text for q in qs}

def build_scoring_text(answer_text: str, respondent_id: int, referenced_numbers: list[int], db: Session, survey_id: int) -> str:
    """
    Build a single text blob that includes the primary answer plus any referenced answers.
    The LLM will grade the primary answer considering the referenced parts.
    """
    sections = [f"PRIMARY ANSWER:\n{answer_text.strip()}"]
    if referenced_numbers:
        # Map visible numbers -> actual question rows
        qs = db.execute(
            select(Question).where(Question.survey_id==survey_id).order_by(Question.order_index)
        ).scalars().all()
        num_to_qid = {q.order_index+1: q.id for q in qs}
        # pull respondent's answers to those questions
        for num in referenced_numbers:
            qid = num_to_qid.get(num)
            if not qid:
                continue
            arow = db.execute(
                select(Answer).where(Answer.respondent_id==respondent_id, Answer.question_id==qid)
            ).scalar_one_or_none()
            if arow and (arow.answer_text or "").strip():
                sections.append(f"REFERENCED ANSWER Q{num}:\n{arow.answer_text.strip()}")
            else:
                sections.append(f"REFERENCED ANSWER Q{num}: <no answer>")
    return "\n\n".join(sections)

def store_refs_on_row(row: Answer, referenced_numbers: list[int], db: Session, survey_id: int) -> None:
    """Persist referenced question IDs (DB ids, not numbers) as JSON."""
    qs = db.execute(
        select(Question).where(Question.survey_id==survey_id).order_by(Question.order_index)
    ).scalars().all()
    num_to_qid = {q.order_index+1: q.id for q in qs}
    db_ids = [num_to_qid[n] for n in referenced_numbers if n in num_to_qid]
    row.referenced_question_ids = json.dumps(db_ids) if db_ids else None

def rescore_dependents_of(question_id: int, respondent_id: int, db: Session) -> None:
    """
    Re-score all answers by this respondent that *currently* reference `question_id`,
    even if they used relative phrases ("previous/next/last/first") and did not have
    stored reference IDs yet. After detection, persist resolved refs for future runs.
    """
    # Survey / numbering context
    q_target = db.get(Question, question_id)
    if not q_target:
        return
    survey_id = q_target.survey_id

    # Precompute numbering maps for this survey
    qs = db.execute(
        select(Question).where(Question.survey_id == survey_id).order_by(Question.order_index)
    ).scalars().all()
    qid_to_num = {q.id: q.order_index + 1 for q in qs}
    num_to_qid = {q.order_index + 1: q.id for q in qs}
    qmap = {q.order_index + 1: q.text for q in qs}
    total = len(qs)
    target_num = qid_to_num.get(question_id)

    # Walk all answers from this respondent *in this survey*
    rows = db.execute(
        select(Answer)
        .join(Question, Answer.question_id == Question.id)
        .where(Answer.respondent_id == respondent_id, Question.survey_id == survey_id)
    ).scalars().all()

    for dep in rows:
        # Skip the row being edited itself
        if dep.question_id == question_id:
            continue

        # If we already have stored refs, check first
        hits_stored = False
        if dep.referenced_question_ids:
            try:
                ids = set(json.loads(dep.referenced_question_ids))
                if question_id in ids:
                    hits_stored = True
                # Clean up any stale ids not in this survey (rare)
                ids = {i for i in ids if i in qid_to_num}
            except Exception:
                ids = set()
        else:
            ids = set()

        # If stored refs don't indicate a dependency, re-detect now using relative logic
        if not hits_stored:
            dep_num = qid_to_num.get(dep.question_id)
            ref_nums, _warn = extract_references(
                dep.answer_text or "",
                qmap,
                current_number=dep_num,
                total_questions=total,
            )
            resolved_ids = {num_to_qid[n] for n in ref_nums if n in num_to_qid}
            # Persist for next time (acts as a cache)
            dep.referenced_question_ids = json.dumps(sorted(resolved_ids)) if resolved_ids else None
            hits_stored = question_id in resolved_ids

        # If this dependent actually references the edited question → rebuild context & rescore
        if hits_stored:
            gl = db.execute(select(Guideline).where(Guideline.question_id == dep.question_id)).scalar_one_or_none()

            # Build context from current refs (ensure up-to-date)
            # Prefer the just-computed mapping if present; else reload from stored
            if dep.referenced_question_ids:
                try:
                    cur_ref_ids = [int(x) for x in json.loads(dep.referenced_question_ids)]
                except Exception:
                    cur_ref_ids = []
            else:
                cur_ref_ids = []

            # map ids→numbers for build_scoring_text
            ref_nums_now = [qid_to_num[i] for i in cur_ref_ids if i in qid_to_num]

            context_text = build_scoring_text(dep.answer_text or "", respondent_id, ref_nums_now, db, survey_id)
            new_score, new_rationale = score_answer(context_text, gl.content if gl else None)
            dep.score = new_score
            dep.rationale = new_rationale
            try:
                dep.low_quality = compute_low_quality(new_score)
            except NameError:
                pass

    db.commit()


# Utility: token generator (stable but opaque); links can be revoked later
secret = os.getenv("LINK_SECRET", "dev-secret")
signer = URLSafeSerializer(secret_key=secret, salt="survey-link")

@app.get("/health")
def health():
    return {"ok": True}

# ------------------------
# Admin: create survey
# ------------------------
@app.post("/admin/surveys", dependencies=[Depends(verify_admin)])
def create_survey(payload: SurveyCreate, db: Session = Depends(get_db)):
    """
    Create a survey with optional questions and guideline.
    Body: SurveyCreate { title, description?, questions[], guideline? }
    Returns: { id }
    """
    
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    # Create Survey
    survey = Survey(title=title, description=(payload.description or "").strip() or None)
    db.add(survey)
    db.flush()  # Get survey.id before committing

    # Create Questions
    for q in sorted(payload.questions or [], key=lambda x: x.order_index):
        text = (q.text or "").strip()
        if not text:
            continue
        db.add(Question(survey_id=survey.id, text=text, order_index=q.order_index, type=q.type or "text"))

    # Optionally Create the Guideline
    if payload.guideline:
        db.add(Guideline(survey_id=survey.id, content=payload.guideline.strip()))

    db.commit()
    return {"id": survey.id}

@app.post("/admin/links", dependencies=[Depends(verify_admin)])
def create_link(link: LinkCreate, db: Session = Depends(get_db)):
    s = db.get(Survey, link.survey_id)
    if not s:
        raise HTTPException(404, "Survey not found")

    # return the existing active link if present
    existing = db.execute(
        select(SurveyLink).where(
            SurveyLink.survey_id == s.id,
            SurveyLink.is_active == True
        )
    ).scalar_one_or_none()
    if existing:
        return {"token": existing.token, "url": f"/take/{existing.token}", "existing": True}

    # create a new link if none exists
    token = signer.dumps({"survey_id": s.id, "nonce": uuid.uuid4().hex})
    row = SurveyLink(survey_id=s.id, token=token, is_active=True)
    db.add(row)
    db.commit()
    return {"token": token, "url": f"/take/{token}", "existing": False}


@app.get("/admin/surveys", dependencies=[Depends(verify_admin)])
def list_surveys(db: Session = Depends(get_db)):
    rows = db.execute(select(Survey)).scalars().all()
    return [{"id": s.id, "title": s.title, "description": s.description, "created_at": s.created_at} for s in rows]

@app.delete("/admin/surveys/{survey_id}", dependencies=[Depends(verify_admin)])
def delete_survey(survey_id: int, db: Session = Depends(get_db)):
    s = db.get(Survey, survey_id)
    if not s:
        raise HTTPException(404, "Survey not found")
    db.delete(s)
    db.commit()
    return {"ok": True}

# ------------------------
# Admin: manage questions
# ------------------------
@app.post("/admin/surveys/{survey_id}/questions", dependencies=[Depends(verify_admin)])
def add_question(survey_id: int, q: QuestionCreate, db: Session = Depends(get_db)):
    if not db.get(Survey, survey_id):
        raise HTTPException(404, "Survey not found")
    row = Question(survey_id=survey_id, text=q.text, order_index=q.order_index, type=q.type)
    db.add(row)
    db.commit()
    return {"id": row.id}

@app.get("/admin/surveys/{survey_id}/detail", dependencies=[Depends(verify_admin)])
def survey_detail(survey_id: int, db: Session = Depends(get_db)):
    s = db.get(Survey, survey_id)
    if not s:
        raise HTTPException(404, "Survey not found")
    qs = db.execute(
        select(Question).where(Question.survey_id == survey_id).order_by(Question.order_index)
    ).scalars().all()
    out_qs = []
    for q in qs:
        g = q.guideline.content if q.guideline else None
        out_qs.append({
            "id": q.id,
            "order_index": q.order_index,
            "text": q.text,
            "type": q.type,
            "guideline": {"content": g} if g else None
        })
    return {
        "survey": {"id": s.id, "title": s.title, "description": s.description},
        "questions": out_qs
    }

# ------------------------
# Admin: guideline
# ------------------------
@app.put("/admin/questions/{question_id}/guideline", dependencies=[Depends(verify_admin)])
def upsert_question_guideline(question_id: int, body: QuestionGuidelineUpsert, db: Session = Depends(get_db)):
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(404, "Question not found")
    if q.guideline:
        q.guideline.content = body.content
    else:
        db.add(Guideline(question_id=q.id, content=body.content))
    db.commit()
    return {"ok": True}

# DELETE only the guideline for a question
@app.delete("/admin/questions/{question_id}/guideline", dependencies=[Depends(verify_admin)])
def delete_question_guideline(question_id: int, db: Session = Depends(get_db)):
    g = db.execute(select(Guideline).where(Guideline.question_id == question_id)).scalar_one_or_none()
    if not g:
        # idempotent – deleting a non-existent guideline is fine
        return {"ok": True, "deleted": 0}
    db.delete(g)
    db.commit()
    return {"ok": True, "deleted": 1}

# DELETE a question (and cascade delete its guideline & answers)
@app.delete("/admin/questions/{question_id}", dependencies=[Depends(verify_admin)])
def delete_question(question_id: int, db: Session = Depends(get_db)):
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(q)             # with FK PRAGMA ON, answers & guideline are removed
    db.commit()
    return {"ok": True}


# ------------------------
# Admin: shareable link
# ------------------------
@app.post("/admin/links", dependencies=[Depends(verify_admin)])
def create_link(link: LinkCreate, db: Session = Depends(get_db)):
    s = db.get(Survey, link.survey_id)
    if not s: raise HTTPException(404, "Survey not found")
    token = signer.dumps({"survey_id": s.id})
    row = SurveyLink(survey_id=s.id, token=token, is_active=True)
    db.add(row); db.commit()
    return {"token": token, "url": f"/take/{token}"}

@app.post("/admin/links/{token}/revoke", dependencies=[Depends(verify_admin)])
def revoke_link(token: str, db: Session = Depends(get_db)):
    row = db.execute(select(SurveyLink).where(SurveyLink.token==token)).scalar_one_or_none()
    if not row: raise HTTPException(404, "Link not found")
    row.is_active = False
    db.commit()
    return {"ok": True}

# ------------------------
# Public: load survey by token
# ------------------------
@app.get("/public/surveys/{token}", response_model=SurveyDetail)
def load_public_survey(token: str, db: Session = Depends(get_db)):
    data = signer.loads(token)
    link = db.execute(select(SurveyLink).where(SurveyLink.token == token)).scalar_one_or_none()
    if not link or not link.is_active:
        raise HTTPException(404, "Link invalid or inactive")
    s = db.get(Survey, data["survey_id"])
    qs = db.execute(
        select(Question).where(Question.survey_id == s.id).order_by(Question.order_index)
    ).scalars().all()
    out_qs = []
    for q in qs:
        g = q.guideline.content if q.guideline else None
        out_qs.append({
            "id": q.id,
            "order_index": q.order_index,
            "text": q.text,
            "type": q.type,
            "guideline": {"content": g} if g else None
        })
    return {"survey": {"id": s.id, "title": s.title, "description": s.description}, "questions": out_qs}


# ------------------------
# Public: respondent session
# ------------------------
@app.post("/public/respondents")
def create_respondent(r: RespondentCreate, db: Session = Depends(get_db)):
    link = db.execute(select(SurveyLink).where(SurveyLink.token==r.link_token)).scalar_one_or_none()
    if not link or not link.is_active:
        raise HTTPException(400, "Invalid link")
    resp = Respondent(link_id=link.id, display_name=r.display_name or None, status="in_progress")
    db.add(resp); db.commit()
    return {"respondent_id": resp.id}

# ------------------------
# Public: answers CRUD
# ------------------------
@app.post("/public/answers")
def create_answer(a: AnswerCreate, db: Session = Depends(get_db)):
    # lookup survey_id for this question
    qrow = db.get(Question, a.question_id)
    if not qrow:
        raise HTTPException(404, "Question not found")
    survey_id = qrow.survey_id

    # detect references against this survey's questions
    qmap = get_question_text_map(db, survey_id)
    ref_nums, warn = extract_references(a.answer_text or "", qmap)

    # build scoring context
    gl = db.execute(select(Guideline).where(Guideline.question_id == a.question_id)).scalar_one_or_none()
    context_text = build_scoring_text(a.answer_text or "", a.respondent_id, ref_nums, db, survey_id)
    score, rationale = score_answer(context_text, gl.content if gl else None)
    low_quality = compute_low_quality(score) if 'compute_low_quality' in globals() else False

    row = Answer(
        respondent_id=a.respondent_id,
        question_id=a.question_id,
        answer_text=a.answer_text,
        flagged=a.flagged,
        score=score,
        rationale=rationale,
        low_quality=low_quality,
        reference_warning=warn or None,
    )
    db.add(row)
    db.flush()  # to get row.id for storing refs
    store_refs_on_row(row, ref_nums, db, survey_id)
    db.commit()

    return {
        "id": row.id,
        "score": score,
        "rationale": rationale,
        "low_quality": low_quality,
        "reference_warning": row.reference_warning,
        "referenced_question_ids": row.referenced_question_ids,
    }


@app.put("/public/answers/{answer_id}")
def update_answer(answer_id: int, a: AnswerUpdate, db: Session = Depends(get_db)):
    row = db.get(Answer, answer_id)
    if not row:
        raise HTTPException(404, "Answer not found")

    if a.answer_text is not None:
        row.answer_text = a.answer_text
    if a.flagged is not None:
        row.flagged = a.flagged

    # survey for this question
    qrow = db.get(Question, row.question_id)
    survey_id = qrow.survey_id

    # detect references again
    qmap = get_question_text_map(db, survey_id)
    ref_nums, warn = extract_references(row.answer_text or "", qmap)

    # build scoring context + score
    gl = db.execute(select(Guideline).where(Guideline.question_id == row.question_id)).scalar_one_or_none()
    context_text = build_scoring_text(row.answer_text or "", row.respondent_id, ref_nums, db, survey_id)
    score, rationale = score_answer(context_text, gl.content if gl else None)
    row.score = score
    row.rationale = rationale
    row.reference_warning = warn or None
    try:
        row.low_quality = compute_low_quality(score)
    except NameError:
        pass
    store_refs_on_row(row, ref_nums, db, survey_id)
    db.commit()

    # cascade: any answers referencing THIS question must be rescored
    rescore_dependents_of(question_id=row.question_id, respondent_id=row.respondent_id, db=db)

    return {
        "ok": True,
        "score": row.score,
        "rationale": row.rationale,
        "low_quality": getattr(row, "low_quality", False),
        "reference_warning": row.reference_warning,
        "referenced_question_ids": row.referenced_question_ids,
        "flagged": row.flagged,
    }


@app.delete("/public/answers/{answer_id}")
def delete_answer(answer_id: int, db: Session = Depends(get_db)):
    row = db.get(Answer, answer_id)
    if not row: raise HTTPException(404, "Answer not found")
    db.delete(row); db.commit()
    return {"ok": True}

@app.get("/public/respondents/{respondent_id}/answers")
def list_answers(respondent_id: int, db: Session = Depends(get_db)):
    rows = db.execute(select(Answer).where(Answer.respondent_id==respondent_id)).scalars().all()
    return [{
        "id": r.id, "question_id": r.question_id, "answer_text": r.answer_text,
        "flagged": r.flagged, "score": r.score, "rationale": r.rationale, "low_quality": r.low_quality, "updated_at": r.updated_at
    } for r in rows]

@app.post("/public/submit")
def submit_survey(s: SubmitSurvey, db: Session = Depends(get_db)):
    resp = db.get(Respondent, s.respondent_id)
    if not resp: raise HTTPException(404, "Respondent not found")
    # Ensure at least one answer exists
    count = db.execute(select(func.count()).select_from(Answer).where(Answer.respondent_id==resp.id)).scalar_one()
    if count == 0:
        raise HTTPException(400, "No answers to submit")
    resp.status = "submitted"
    db.commit()
    return {"ok": True}

# ------------------------
# Admin: view/export responses
# ------------------------
@app.get("/admin/surveys/{survey_id}/responses", dependencies=[Depends(verify_admin)])
def survey_responses(survey_id: int, db: Session = Depends(get_db)):
    q = select(Respondent.id, Respondent.status, Answer.id, Answer.question_id, Answer.answer_text, Answer.flagged, Answer.score, Answer.rationale, Answer.low_quality).join(Answer, Answer.respondent_id==Respondent.id, isouter=True).join(Question, Question.id==Answer.question_id, isouter=True).where(Question.survey_id==survey_id)
    rows = db.execute(q).all()
    data = [{
        "respondent_id": r[0], "status": r[1], "answer_id": r[2], "question_id": r[3],
        "answer_text": r[4], "flagged": r[5], "score": r[6], "rationale": r[7], "low_quality": r[8]
    } for r in rows]
    return data

@app.get("/admin/surveys/{survey_id}/export.csv", dependencies=[Depends(verify_admin)])
def export_csv(survey_id: int, db: Session = Depends(get_db)):
    q = select(Respondent.id.label("respondent_id"), Respondent.status, Question.order_index, Question.text.label("question"),
                Answer.answer_text, Answer.flagged, Answer.score, Answer.rationale, Answer.low_quality).join(Answer, Answer.respondent_id==Respondent.id, isouter=True).join(Question, Question.id==Answer.question_id, isouter=True).where(Question.survey_id==survey_id).order_by(Respondent.id, Question.order_index)
    df = pd.read_sql(q, db.bind)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    return Response(content=csv_bytes, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=survey_{survey_id}_responses.csv"})
