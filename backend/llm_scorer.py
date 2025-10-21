# LLM-based semantic scoring against guidelines 
from __future__ import annotations
from typing import Optional, Tuple
import os
import json
from openai import OpenAI, APIConnectionError, APIStatusError, RateLimitError
from dotenv import load_dotenv

load_dotenv()

# Config
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
_SCORE_MIN = float(os.getenv("SCORE_MIN", "0.0"))
_SCORE_MAX = float(os.getenv("SCORE_MAX", "5.0"))

_client = None
if _OPENAI_API_KEY:
    _client = OpenAI(api_key=_OPENAI_API_KEY)

# JSON schema for structured output
_SCORE_SCHEMA = {
    "name": "survey_score",
    "schema": {
        "type": "object",
        "properties": {
            "score": {
                "type": "number",
                "description": "A numeric score between {_SCORE_MIN} and {_SCORE_MAX} inclusive indicating how well the answer satisfies the guideline.",
                "minimum": _SCORE_MIN,
                "maximum": _SCORE_MAX,
            },
            "rationale": {
                "type": "string",
                "description": "A brief explanation (1-3 sentences) referencing the guideline criteria."
            }
        },
        "required": ["score", "rationale"],
        "additionalProperties": False
    },
    "strict": True
}

_HEURISTIC_MSG = "Heuristic fallback based on answer length (no LLM scoring)."

def _heuristic(answer_text: str) -> tuple[Optional[float], Optional[str]]:
    if not answer_text:
        return None, None
    length = len(answer_text.strip())
    score = max(_SCORE_MIN, min(_SCORE_MAX, (length / 200.0)))  # ~200 chars → 1.0
    return score, _HEURISTIC_MSG

def score_answer(answer_text: str, guideline: str | None) -> tuple[Optional[float], Optional[str]]:
    """
    Return (score in [0,5], rationale). Falls back to heuristic if:
    - no OPENAI_API_KEY
    - guideline missing
    - API errors / rate limits
    """
    # No answer → nothing to score
    if not answer_text:
        return None, None

    # If no key or no guideline, fall back
    if not _client or not guideline:
        return _heuristic(answer_text)

    try:
        prompt = (
            "You are an impartial grader. Score the candidate's answer strictly "
            "against the provided guideline. Return a JSON object with fields:\n"
            "  - score: number in [{_SCORE_MIN},{_SCORE_MAX}]\n"
            "  - rationale: 1–3 concise sentences referencing the guideline.\n"
            "Do not include anything except valid JSON.\n\n"
            f"GUIDELINE:\n{guideline}\n\n"
            f"ANSWER:\n{answer_text}\n"
        )

        resp = _client.chat.completions.create(
            model=_MODEL,                     
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You are a strict grading assistant. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
        )

        content = resp.choices[0].message.content
        data = json.loads(content)
        score = float(data["score"])
        rationale = str(data["rationale"]).strip()
        score = max(_SCORE_MIN, min(_SCORE_MAX, score))
        return score, rationale or "Scored by LLM."


    except (RateLimitError, APIStatusError, APIConnectionError, KeyError, ValueError, json.JSONDecodeError):
        # Any issue → degrade gracefully
        return _heuristic(answer_text)
