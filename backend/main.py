import os, io, uuid, sqlite3
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from db import Base, engine, get_db
from models import Survey, Question, Guideline, SurveyLink, Respondent, Answer
from schemas import *
from security import verify_admin
from datetime import datetime, timedelta, timezone

# Minimal URL-safe serializer fallback to avoid external dependency on itsdangerous.
# Provides dumps(obj) -> str and loads(token) -> obj with HMAC-SHA256 signature.
import json
import hmac
import hashlib
import base64

import pandas as pd
from llm_scorer import score_answer, extract_references

app = FastAPI(title="Survey Bot API")

origins = os.getenv("ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
class URLSafeSerializer:
    """Tiny URL-safe HMAC serializer.
    
    Encodes/decodes JSON payloads with an HMAC-SHA256 signature:
    token = base64url(payload) + "." + base64url(signature).
    """

    def __init__(self, secret_key, salt=""):
        """
        Args:
            secret_key (str): Secret bytes used for HMAC.
            salt (str): Optional salt mixed into the HMAC key.
        """
        self.secret_key = (secret_key or "").encode("utf-8")
        self.salt = salt or ""

    def _b64(self, data: bytes) -> str:
        """Return base64url-encoded string without padding."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _unb64(self, s: str) -> bytes:
        """Decode base64url string that may be missing padding."""
        s_bytes = s.encode("ascii")
        padding = b"=" * (-len(s_bytes) % 4)
        return base64.urlsafe_b64decode(s_bytes + padding)

    def dumps(self, obj) -> str:
        """Serialize and sign an object.

        Args:
            obj (Any): JSON-serializable value.

        Returns:
            str: URL-safe token "<b64json>.<b64sig>".
        """
        payload = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = hmac.new(self.secret_key + self.salt.encode("utf-8"), payload, hashlib.sha256).digest()
        return f"{self._b64(payload)}.{self._b64(sig)}"

    def loads(self, token: str):
        """Verify signature and deserialize an object.

        Args:
            token (str): Token "<b64json>.<b64sig>".

        Returns:
            Any: Decoded JSON payload.

        Raises:
            ValueError: If token format or signature is invalid.
        """
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

# Helper functions for link generation
def _now_utc() -> datetime:
    """Return the current UTC time as an aware datetime."""
    return datetime.now(timezone.utc)

def load_token_with_expiry(token: str) -> tuple[dict, bool]:
    """Decode a token and determine if it is expired.

    Args:
        token (str): Signed token to validate.

    Returns:
        tuple[dict, bool]: (payload, expired_flag)

    Raises:
        ValueError: If token format/signature invalid.
    """
    data = signer.loads(token)
    exp = int(data.get("exp", 0) or 0)
    expired = bool(exp and _now_utc().timestamp() > exp)
    return data, expired

def _assert_link_is_active_by_respondent(respondent_id: int, db: Session):
    """Validate that the respondent's link is currently active (writeable).

    Args:
        respondent_id (int): Respondent session ID.
        db (Session): DB session.

    Raises:
        HTTPException: 404 if respondent not found; 403 if link is inactive.
    """
    resp = db.get(Respondent, respondent_id)
    if not resp:
        raise HTTPException(404, "Respondent not found")
    link = db.get(SurveyLink, resp.link_id)
    if not link or not link.is_active:
        raise HTTPException(403, "Survey link is read-only (deprecated)")

# --- scoring low_quality helper ---
LOW_QUALITY_THRESHOLD_5 = float(os.getenv("LOW_QUALITY_THRESHOLD_5", "2.0"))

def compute_low_quality(score: Optional[float]) -> bool:
    """Determine whether a numeric score is considered low quality.

    Args:
        score (float|None): Score from the LLM scoring pipeline.

    Returns:
        bool: True if score exists and is below threshold.
    """
    if score is None:
        return False
    return score < LOW_QUALITY_THRESHOLD_5

def get_question_text_map(db: Session, survey_id: int) -> dict[int, str]:
    """Build a map of display question number → question text for a survey.

    Args:
        db (Session): DB session.
        survey_id (int): Survey ID.

    Returns:
        dict[int, str]: { display_number (1-based): text }
    """
    qs = db.execute(
        select(Question).where(Question.survey_id==survey_id).order_by(Question.order_index)
    ).scalars().all()
    return {q.order_index + 1: q.text for q in qs}

def build_scoring_text(answer_text: str, respondent_id: int, referenced_numbers: list[int], db: Session, survey_id: int) -> str:
    """Assemble a scoring context including the primary answer and referenced answers.

    Args:
        answer_text (str): The current answer content.
        respondent_id (int): Respondent ID.
        referenced_numbers (list[int]): 1-based question numbers referenced by the answer.
        db (Session): DB session.
        survey_id (int): Survey ID.

    Returns:
        str: Combined scoring text for the LLM.
    """
    sections = [f"PRIMARY ANSWER:\n{answer_text.strip()}"]
    if referenced_numbers:
        qs = db.execute(
            select(Question).where(Question.survey_id==survey_id).order_by(Question.order_index)
        ).scalars().all()
        num_to_qid = {q.order_index+1: q.id for q in qs}
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
    """Persist referenced question IDs on an answer row based on 1-based numbers.

    Args:
        row (Answer): Answer ORM row to mutate.
        referenced_numbers (list[int]): 1-based referenced question numbers.
        db (Session): DB session.
        survey_id (int): Survey ID.
    """
    qs = db.execute(
        select(Question).where(Question.survey_id==survey_id).order_by(Question.order_index)
    ).scalars().all()
    num_to_qid = {q.order_index+1: q.id for q in qs}
    db_ids = [num_to_qid[n] for n in referenced_numbers if n in num_to_qid]
    row.referenced_question_ids = json.dumps(db_ids) if db_ids else None

def rescore_dependents_of(question_id: int, respondent_id: int, db: Session) -> None:
    """Re-score all of a respondent’s answers that reference the given question.

    Detects references (including relative forms), updates stored refs,
    rebuilds scoring context, and re-scores using the latest texts.

    Args:
        question_id (int): The question that changed.
        respondent_id (int): Respondent whose dependent answers to re-score.
        db (Session): DB session.
    """
    q_target = db.get(Question, question_id)
    if not q_target:
        return
    survey_id = q_target.survey_id

    qs = db.execute(
        select(Question).where(Question.survey_id == survey_id).order_by(Question.order_index)
    ).scalars().all()
    qid_to_num = {q.id: q.order_index + 1 for q in qs}
    num_to_qid = {q.order_index + 1: q.id for q in qs}
    qmap = {q.order_index + 1: q.text for q in qs}
    total = len(qs)

    rows = db.execute(
        select(Answer)
        .join(Question, Answer.question_id == Question.id)
        .where(Answer.respondent_id == respondent_id, Question.survey_id == survey_id)
    ).scalars().all()

    for dep in rows:
        if dep.question_id == question_id:
            continue

        hits_stored = False
        if dep.referenced_question_ids:
            try:
                ids = set(json.loads(dep.referenced_question_ids))
                if question_id in ids:
                    hits_stored = True
                ids = {i for i in ids if i in qid_to_num}
            except Exception:
                ids = set()
        else:
            ids = set()

        if not hits_stored:
            dep_num = qid_to_num.get(dep.question_id)
            ref_nums, _warn = extract_references(
                dep.answer_text or "",
                qmap,
                current_number=dep_num,
                total_questions=total,
            )
            resolved_ids = {num_to_qid[n] for n in ref_nums if n in num_to_qid}
            dep.referenced_question_ids = json.dumps(sorted(resolved_ids)) if resolved_ids else None
            hits_stored = question_id in resolved_ids

        if hits_stored:
            gl = db.execute(select(Guideline).where(Guideline.question_id == dep.question_id)).scalar_one_or_none()
            if dep.referenced_question_ids:
                try:
                    cur_ref_ids = [int(x) for x in json.loads(dep.referenced_question_ids)]
                except Exception:
                    cur_ref_ids = []
            else:
                cur_ref_ids = []
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
    """Basic readiness probe.

    Returns:
        dict: {"ok": True}
    """
    return {"ok": True}

# ------------------------
# Admin: create survey
# ------------------------
@app.post("/admin/surveys", dependencies=[Depends(verify_admin)])
def create_survey(payload: SurveyCreate, db: Session = Depends(get_db)):
    """Create a new survey with optional questions and guideline.

    Args:
        payload (SurveyCreate): Title (required), description, questions[], guideline.
        db (Session): DB session.

    Returns:
        dict: {"id": <new_survey_id>}
    """
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    survey = Survey(title=title, description=(payload.description or "").strip() or None)
    db.add(survey)
    db.flush()

    for q in sorted(payload.questions or [], key=lambda x: x.order_index):
        text = (q.text or "").strip()
        if not text:
            continue
        db.add(Question(survey_id=survey.id, text=text, order_index=q.order_index, type=q.type or "text"))

    if payload.guideline:
        db.add(Guideline(survey_id=survey.id, content=payload.guideline.strip()))

    db.commit()
    return {"id": survey.id}

@app.get("/admin/surveys", dependencies=[Depends(verify_admin)])
def list_surveys(db: Session = Depends(get_db)):
    """List all surveys with their latest active link (if any).

    Args:
        db (Session): DB session.

    Returns:
        list[dict]: [{id, title, description, created_at, link?{token,is_active,scope}}]
    """
    rows = db.execute(select(Survey)).scalars().all()
    out = []
    for s in rows:
        link = db.execute(
            select(SurveyLink)
            .where(SurveyLink.survey_id == s.id, SurveyLink.is_active == True)
            .order_by(SurveyLink.created_at.desc())
        ).scalar_one_or_none()
        out.append({
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "created_at": s.created_at,
            "link": {
                "token": link.token if link else None,
                "is_active": bool(link.is_active) if link else False,
                "scope": getattr(link, "scope", "write") if link else None,
            } if link else None
        })
    return out

@app.delete("/admin/surveys/{survey_id}", dependencies=[Depends(verify_admin)])
def delete_survey(survey_id: int, db: Session = Depends(get_db)):
    """Hard-delete a survey and all related rows (via FKs).

    Args:
        survey_id (int): Survey primary key.
        db (Session): DB session.

    Returns:
        dict: {"ok": True}

    Raises:
        HTTPException: 404 if survey not found.
    """
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
    """Add a question to a survey.

    Args:
        survey_id (int): Survey ID.
        q (QuestionCreate): {text, order_index, type}.
        db (Session): DB session.

    Returns:
        dict: {"id": <new_question_id>}

    Raises:
        HTTPException: 404 if survey not found.
    """
    if not db.get(Survey, survey_id):
        raise HTTPException(404, "Survey not found")
    row = Question(survey_id=survey_id, text=q.text, order_index=q.order_index, type=q.type)
    db.add(row)
    db.commit()
    return {"id": row.id}

@app.get("/admin/surveys/{survey_id}/detail", dependencies=[Depends(verify_admin)])
def survey_detail(survey_id: int, db: Session = Depends(get_db)):
    """Get survey detail including ordered questions and per-question guideline.

    Args:
        survey_id (int): Survey ID.
        db (Session): DB session.

    Returns:
        dict: {"survey": {...}, "questions": [{...}]}

    Raises:
        HTTPException: 404 if survey not found.
    """
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
    """Create or update a guideline for a question.

    Args:
        question_id (int): Question ID.
        body (QuestionGuidelineUpsert): {content}.
        db (Session): DB session.

    Returns:
        dict: {"ok": True}

    Raises:
        HTTPException: 404 if question not found.
    """
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(404, "Question not found")
    if q.guideline:
        q.guideline.content = body.content
    else:
        db.add(Guideline(question_id=q.id, content=body.content))
    db.commit()
    return {"ok": True}

@app.delete("/admin/questions/{question_id}/guideline", dependencies=[Depends(verify_admin)])
def delete_question_guideline(question_id: int, db: Session = Depends(get_db)):
    """Delete only the guideline for a question (idempotent).

    Args:
        question_id (int): Question ID.
        db (Session): DB session.

    Returns:
        dict: {"ok": True, "deleted": 0|1}
    """
    g = db.execute(select(Guideline).where(Guideline.question_id == question_id)).scalar_one_or_none()
    if not g:
        return {"ok": True, "deleted": 0}
    db.delete(g)
    db.commit()
    return {"ok": True, "deleted": 1}

@app.delete("/admin/questions/{question_id}", dependencies=[Depends(verify_admin)])
def delete_question(question_id: int, db: Session = Depends(get_db)):
    """Delete a question and its dependent rows (guideline/answers via FK).

    Args:
        question_id (int): Question ID.
        db (Session): DB session.

    Returns:
        dict: {"ok": True}

    Raises:
        HTTPException: 404 if question not found.
    """
    q = db.get(Question, question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    db.delete(q)
    db.commit()
    return {"ok": True}

# ------------------------
# Admin: shareable link (create or reuse active)
# ------------------------
@app.post("/admin/links", dependencies=[Depends(verify_admin)])
def create_link(link: LinkCreate, db: Session = Depends(get_db)):
    """Create (or reuse) an active shareable link for a survey.

    If an active link already exists, returns it. Otherwise, creates a new
    unique token with random nonce to avoid collisions.

    Args:
        link (LinkCreate): {survey_id}.
        db (Session): DB session.

    Returns:
        dict: {"token": str, "url": str, "existing": bool}

    Raises:
        HTTPException: 404 if survey not found; 500 if token generation fails repeatedly.
    """
    s = db.get(Survey, link.survey_id)
    if not s:
        raise HTTPException(404, "Survey not found")

    existing = db.execute(
        select(SurveyLink).where(
            SurveyLink.survey_id == s.id,
            SurveyLink.is_active == True
        )
    ).scalar_one_or_none()
    if existing:
        return {"token": existing.token, "url": f"/take/{existing.token}", "existing": True}

    for _ in range(5):
        token = signer.dumps({"survey_id": s.id, "nonce": uuid.uuid4().hex})
        row = SurveyLink(survey_id=s.id, token=token, is_active=True)
        db.add(row)
        try:
            db.commit()
            return {"token": token, "url": f"/take/{token}", "existing": False}
        except IntegrityError:
            db.rollback()
            continue

    raise HTTPException(500, "Failed to generate a unique link token")

@app.post("/admin/links/{token}/revoke", dependencies=[Depends(verify_admin)])
def revoke_link(token: str, db: Session = Depends(get_db)):
    """Mark a link inactive (read-only mode for existing respondents).

    Args:
        token (str): Link token to deactivate.
        db (Session): DB session.

    Returns:
        dict: {"ok": True}

    Raises:
        HTTPException: 404 if link not found.
    """
    row = db.execute(select(SurveyLink).where(SurveyLink.token==token)).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Link not found")
    row.is_active = False
    db.commit()
    return {"ok": True}


# ------------------------
# Public: load survey by token
# ------------------------
@app.get("/public/surveys/{token}", response_model=SurveyDetail)
def load_public_survey(token: str, db: Session = Depends(get_db)):
    """Resolve a token to survey content for public consumption.

    Includes questions and link meta (scope/expiry/read-only) for UI decisions.

    Args:
        token (str): Shareable token.
        db (Session): DB session.

    Returns:
        SurveyDetail: {survey, questions, link_meta{scope,expired,read_only,expires_at}}

    Raises:
        HTTPException: 404 if token invalid/inactive.
    """
    try:
        data, expired = load_token_with_expiry(token)
    except ValueError:
        raise HTTPException(404, "Link invalid")

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

    scope = data.get("scope", "submit")
    exp = int(data.get("exp", 0) or 0)
    read_only = expired or scope != "submit"

    return {
        "survey": {"id": s.id, "title": s.title, "description": s.description},
        "questions": out_qs,
        "link_meta": {
            "scope": scope,
            "expired": expired,
            "read_only": read_only,
            "expires_at": exp,
        }
    }


# ------------------------
# Public: respondent session
# ------------------------
@app.post("/public/respondents")
def create_respondent(r: RespondentCreate, db: Session = Depends(get_db)):
    """Create a respondent session bound to a link token.

    Args:
        r (RespondentCreate): {link_token, display_name?}
        db (Session): DB session.

    Returns:
        dict: {"respondent_id": int}

    Raises:
        HTTPException: 400 if link token is invalid.
    """
    link = db.execute(select(SurveyLink).where(SurveyLink.token==r.link_token)).scalar_one_or_none()
    if not link:
        raise HTTPException(400, "Invalid link")
    resp = Respondent(link_id=link.id, display_name=r.display_name or None, status="in_progress")
    db.add(resp); db.commit()
    return {"respondent_id": resp.id}

# ------------------------
# Public: answers CRUD
# ------------------------
@app.post("/public/answers")
def create_answer(a: AnswerCreate, db: Session = Depends(get_db)):
    """Create a new answer, auto-score it, and persist reference metadata.

    Args:
        a (AnswerCreate): {respondent_id, question_id, answer_text, flagged?}
        db (Session): DB session.

    Returns:
        dict: {"id", "score", "rationale", "low_quality", "reference_warning", "referenced_question_ids"}

    Raises:
        HTTPException: 403 if link is read-only; 404 if question not found.
    """
    _assert_link_is_active_by_respondent(a.respondent_id, db)
    qrow = db.get(Question, a.question_id)
    if not qrow:
        raise HTTPException(404, "Question not found")
    survey_id = qrow.survey_id

    qmap = get_question_text_map(db, survey_id)
    ref_nums, warn = extract_references(a.answer_text or "", qmap)

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
    db.flush()
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
    """Update an existing answer (text/flag), re-score, and propagate dependent rescoring.

    Args:
        answer_id (int): Answer PK.
        a (AnswerUpdate): {answer_text?, flagged?}
        db (Session): DB session.

    Returns:
        dict: {"ok", "score", "rationale", "low_quality", "reference_warning", "referenced_question_ids", "flagged"}

    Raises:
        HTTPException: 404 if answer not found; 403 if link is read-only.
    """
    row = db.get(Answer, answer_id)
    if not row:
        raise HTTPException(404, "Answer not found")
    _assert_link_is_active_by_respondent(row.respondent_id, db)
    
    if a.answer_text is not None:
        row.answer_text = a.answer_text
    if a.flagged is not None:
        row.flagged = a.flagged

    qrow = db.get(Question, row.question_id)
    survey_id = qrow.survey_id

    qmap = get_question_text_map(db, survey_id)
    ref_nums, warn = extract_references(row.answer_text or "", qmap)

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

    # cascade re-score
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
    """Delete an answer (requires active/writeable link).

    Args:
        answer_id (int): Answer PK.
        db (Session): DB session.

    Returns:
        dict: {"ok": True}

    Raises:
        HTTPException: 404 if not found; 403 if link is read-only.
    """
    row = db.get(Answer, answer_id)
    if not row: raise HTTPException(404, "Answer not found")
    _assert_link_is_active_by_respondent(row.respondent_id, db)
    db.delete(row); db.commit()
    return {"ok": True}

@app.get("/public/respondents/{respondent_id}/answers")
def list_answers(respondent_id: int, db: Session = Depends(get_db)):
    """List all answers for a respondent.

    Args:
        respondent_id (int): Respondent PK.
        db (Session): DB session.

    Returns:
        list[dict]: Answers with scoring/flags metadata.
    """
    rows = db.execute(select(Answer).where(Answer.respondent_id==respondent_id)).scalars().all()
    return [{
        "id": r.id, "question_id": r.question_id, "answer_text": r.answer_text,
        "flagged": r.flagged, "score": r.score, "rationale": r.rationale, "low_quality": r.low_quality, "updated_at": r.updated_at
    } for r in rows]

@app.post("/public/submit")
def submit_survey(s: SubmitSurvey, db: Session = Depends(get_db)):
    """Mark a respondent as submitted (requires at least one answer).

    Args:
        s (SubmitSurvey): {respondent_id}
        db (Session): DB session.

    Returns:
        dict: {"ok": True}

    Raises:
        HTTPException: 403 if link is read-only; 404 if respondent missing; 400 if no answers exist.
    """
    _assert_link_is_active_by_respondent(s.respondent_id, db)
    resp = db.get(Respondent, s.respondent_id)
    if not resp: raise HTTPException(404, "Respondent not found")
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
    """Return a raw flat list of responses for a survey (for admin views).

    Args:
        survey_id (int): Survey PK.
        db (Session): DB session.

    Returns:
        list[dict]: Rows including respondent/answer/score/flags.
    """
    q = select(Respondent.id, Respondent.status, Answer.id, Answer.question_id, Answer.answer_text, Answer.flagged, Answer.score, Answer.rationale, Answer.low_quality).join(Answer, Answer.respondent_id==Respondent.id, isouter=True).join(Question, Question.id==Answer.question_id, isouter=True).where(Question.survey_id==survey_id)
    rows = db.execute(q).all()
    data = [{
        "respondent_id": r[0], "status": r[1], "answer_id": r[2], "question_id": r[3],
        "answer_text": r[4], "flagged": r[5], "score": r[6], "rationale": r[7], "low_quality": r[8]
    } for r in rows]
    return data

@app.get("/admin/surveys/{survey_id}/export.csv", dependencies=[Depends(verify_admin)])
def export_csv(survey_id: int, db: Session = Depends(get_db)):
    """Export survey responses as CSV (sorted by respondent, then question order).

    Args:
        survey_id (int): Survey PK.
        db (Session): DB session.

    Returns:
        Response: text/csv attachment `survey_<id>_responses.csv`.
    """
    q = select(Respondent.id.label("respondent_id"), Respondent.status, Question.order_index, Question.text.label("question"),
                Answer.answer_text, Answer.flagged, Answer.score, Answer.rationale, Answer.low_quality).join(Answer, Answer.respondent_id==Respondent.id, isouter=True).join(Question, Question.id==Answer.question_id, isouter=True).where(Question.survey_id==survey_id).order_by(Respondent.id, Question.order_index)
    df = pd.read_sql(q, db.bind)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    return Response(content=csv_bytes, media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=survey_{survey_id}_responses.csv"})
