import os, json, math, csv, re
from statistics import mean
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from llm_scorer import score_answer

ROOT = Path(__file__).parent
EVAL_PATH = ROOT / "evalset.jsonl"
OUT_DIR = ROOT / "out"
OUT_DIR.mkdir(exist_ok=True, parents=True)

CANDIDATES = [
    ("gpt-4o",        {"LLM_MODEL": "gpt-4o"}),
    ("gpt-3.5-turbo", {"LLM_MODEL": "gpt-3.5-turbo"}),
    ("gpt-5",   {"LLM_MODEL": "gpt-5"}),
]


def set_env(vars: Dict[str, str]):
    for k, v in vars.items():
        os.environ[k] = v

def load_eval() -> List[dict]:
    rows = []
    with open(EVAL_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def _rankdata(values):
    """Average ranks for ties, 0-based ranks."""
    # values: list of floats
    indexed = list(enumerate(values))               # [(idx, val), ...]
    indexed.sort(key=lambda x: x[1])                # sort by value
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        # find tie group [i, j)
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        # average rank for ties
        avg_rank = (i + j - 1) / 2.0
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks

def spearman(xs, ys):
    """
    Spearman rank correlation (tie-aware), returns None if insufficient data.
    xs, ys: lists of floats (may contain None)
    """
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 2:
        return None

    x_vals = [float(x) for x, _ in pairs]
    y_vals = [float(y) for _, y in pairs]

    xr = _rankdata(x_vals)
    yr = _rankdata(y_vals)

    mx = mean(xr); my = mean(yr)
    num = sum((a - mx) * (b - my) for a, b in zip(xr, yr))
    den_x = math.sqrt(sum((a - mx) ** 2 for a in xr))
    den_y = math.sqrt(sum((b - my) ** 2 for b in yr))
    den = den_x * den_y
    return (num / den) if den else None


def eval_one(model_name: str, envs: Dict[str, str], eval_rows: List[dict]) -> List[dict]:
    set_env(envs)
    outs = []
    preds05 = []
    for r in eval_rows:
        score05, rationale = score_answer(r.get("answer",""), r.get("guideline"))
        outs.append({
            **r,
            "model": model_name,
            "score_pred": score05,    # keep 0~5 scale
            "rationale": rationale
        })
        preds05.append(score05)

    vals = [p for p in preds05 if p is not None]
    if vals:
        from statistics import mean
        print(f"[{model_name}] used LLM_MODEL={os.getenv('LLM_MODEL')}; "
              f"pred05_min={min(vals):.2f}, pred05_max={max(vals):.2f}, pred05_mean={mean(vals):.2f}")
    else:
        print(f"[{model_name}] used LLM_MODEL={os.getenv('LLM_MODEL')}; no predictions")

    # Save raw outputs
    out_path = OUT_DIR / f"raw_{model_name}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for o in outs:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
            
    vals = [o.get("score_pred") for o in outs if o.get("score_pred") is not None]
    return outs

def print_and_save_report(results: Dict[str, List[dict]], eval_rows: List[dict]):
    gold01 = [r.get("gold_score") for r in eval_rows]   # gold is 0~1 scale
    header = ["model","mae","mse","spearman","coverage"]
    rows_csv = []

    for name, outs in results.items():
        # 0–5 → 0–1
        preds01 = [(o.get("score_pred")/5.0 if o.get("score_pred") is not None else None) for o in outs]
        pairs = [(g,p) for g,p in zip(gold01,preds01) if g is not None and p is not None]
        mae = mean(abs(g-p) for g,p in pairs) if pairs else None
        mse = mean((g-p)**2 for g,p in pairs) if pairs else None
        corr = spearman([g for g,_ in pairs], [p for _,p in pairs]) if pairs else None
        coverage = sum(p is not None for p in preds01) / len(preds01) if preds01 else 0.0

        print(f"[{name}] MAE={mae}  MSE={mse}  Spearman={corr}  Coverage={coverage:.2f}")
        rows_csv.append([name, mae, mse, corr, coverage])

    # use 0-1 scale for comparison
    ref_name = list(results.keys())[0]
    ref = results[ref_name]
    for name, outs in results.items():
        if name == ref_name: continue
        diffs = []
        for r0, r1 in zip(ref, outs):
            s0 = r0.get("score_pred"); s1 = r1.get("score_pred")
            if s0 is not None and s1 is not None:
                diffs.append(abs(s0/5.0 - s1/5.0))
        rel = mean(diffs) if diffs else None
        print(f"[{name}] vs [{ref_name}] mean abs diff = {rel}")

    # Save summary CSV
    with open(OUT_DIR/"summary_gold.csv","w",newline="",encoding="utf-8") as f:
        csv.writer(f).writerows([header, *rows_csv])

def main():
    eval_rows = load_eval()
    results = {}
    for name, envs in CANDIDATES:
        outs = eval_one(name, envs, eval_rows)
        results[name] = outs
    print_and_save_report(results, eval_rows)
    print(f"\nReports saved to: {OUT_DIR.resolve()}")

if __name__ == "__main__":
    main()
