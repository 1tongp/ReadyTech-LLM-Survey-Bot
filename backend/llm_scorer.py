# LLM-based semantic scoring against guidelines 
from __future__ import annotations
from typing import Optional
import os, re
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
    score01 = min(1.0, max(0.0, length / 200.0))     # 0-1 based on length (200 chars = full score)
    score = score01 * _SCORE_MAX                     # scale to [0, _SCORE_MAX]
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
    
    if not guideline:             
        return None, None
    
    # If no key, fall back
    if not _client:
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
        {"role":"system","content":(
            "You are a strict grader. Output ONLY JSON: "
            '{"score": number, "rationale": string}. '
            "The score MUST be a real number in [0,5]. "
            "Use 0 for off-topic/empty/contradictory answers; "
            "≈1 for poor; ≈3 for partial; ≈4 for good; 5 for perfect and fully aligned."
            "If the answer does not meet the guideline at all, you MUST use 0 or 1."
        )},
        {"role":"user","content": prompt}
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

# -------------------------------------------------------
# Extracting question references from free-text answers
# -------------------------------------------------------

ORDINAL_MAP = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

def extract_references(
    answer_text: str,
    question_text_map: dict[int, str],
    *,
    current_number: int | None = None,
    total_questions: int | None = None,
) -> tuple[list[int], str]:
    text = (answer_text or "").strip()
    if not text:
        return [], ""

    existing_numbers = set(question_text_map.keys())
    mentioned: set[int] = set()
    warnings: list[str] = []

    # 1) Absolute: Q2 / question 2
    for m in re.finditer(r"(?:\bq(?:uestion)?\s*|ques\s*)(\d+)\b", text, flags=re.I):
        try: mentioned.add(int(m.group(1)))
        except: pass

    # 2) Ordinals: first/second/...
    for w, n in ORDINAL_MAP.items():
        if re.search(rf"\b{w}\b(?:\s+question)?", text, flags=re.I):
            mentioned.add(n)

    # 3) Relative refs
    # IMPORTANT: do NOT treat "last" as "previous".
    rel_prev_patterns = r"\b(prev(?:ious)?|prior|earlier|above)\b"
    rel_next_patterns = r"\b(next|following|below|later)\b"

    if current_number is not None and total_questions is not None:
        if re.search(rel_prev_patterns, text, flags=re.I):
            num = current_number - 1
            if num >= 1: mentioned.add(num)
            else: warnings.append("Referenced previous question but there is no previous question.")
        if re.search(rel_next_patterns, text, flags=re.I):
            num = current_number + 1
            if num <= total_questions: mentioned.add(num)
            else: warnings.append("Referenced next question but there is no next question.")

        # Map "last question" and "the last question" → final question
        if re.search(r"\b(the\s+)?last\s+question\b", text, flags=re.I):
            if total_questions >= 1:
                mentioned.add(total_questions)

        # Map "the first question" explicitly
        if re.search(r"\b(the\s+)?first\s+question\b", text, flags=re.I):
            mentioned.add(1)

    # 4) Optional LLM refinement for vague phrases
    need_llm = bool(re.search(r"\b(previous|prior|earlier|above|next|following|below|later|last|first)\b", text, flags=re.I)) or not mentioned
    refined: set[int] = set()
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY", "")
        client = OpenAI(api_key=api_key) if api_key else None
        if client and need_llm:
            numbered = "\n".join([f"{i}. {t}" for i, t in question_text_map.items()])
            cn = current_number if current_number is not None else "unknown"
            tot = total_questions if total_questions is not None else len(question_text_map)
            prompt = (
                "Extract which question numbers the answer refers to. "
                "Interpret relative words (previous/next/last/first/earlier/above/below) "
                f"relative to CURRENT={cn} and TOTAL={tot}. "
                "Return JSON: {\"refs\": [ints]}.\n\n"
                f"Available questions:\n{numbered}\n\nAnswer:\n{text}\n"
            )
            resp = client.chat.completions.create(
                model=os.getenv("LLM_MODEL","gpt-4o-mini"),
                temperature=0.0,
                response_format={"type":"json_object"},
                messages=[
                    {"role":"system","content":"Return only valid JSON with key 'refs'."},
                    {"role":"user","content":prompt},
                ],
            )
            data = json.loads(resp.choices[0].message.content)
            refined = set(int(x) for x in data.get("refs", []) if str(x).isdigit())
    except Exception:
        pass

    all_nums = mentioned | refined

    # 5) Validate & warn hallucinated refs
    valid = [n for n in sorted(all_nums) if n in existing_numbers]
    invalid = [n for n in sorted(all_nums) if n not in existing_numbers]
    if invalid:
        warnings.append(f"Referenced non-existent question(s): {invalid}")

    return valid, "; ".join(warnings)
