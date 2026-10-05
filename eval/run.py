"""Offline evaluation: does the bot take the right route, and does it ever answer when it
should have handed off?

    python -m eval.run            # writes reports/eval.md and reports/eval.json
    python -m eval.run --gate     # CI: also fail if there is any wrong answer or accuracy < 90%

Each case in eval/cases.jsonl is sent as the first message of a fresh conversation, with the
LLM switched off (so the result is deterministic and free). Expected values:
  faq:<slug>[|<slug>...]   answer from one of these articles
  handoff / booking / cancel / my_bookings / smalltalk / refusal

The most important number is "wrong answers": messages the bot answered (or answered from the
wrong article) when it should have done something else. That is what "no made-up answers"
means in practice. The answer threshold is chosen from the sweep below.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from sqlalchemy import text

from clinic import config
from clinic.agent import Agent
from clinic.db import make_engine
from clinic.rag import Retriever
from data.seed import seed

CASES = Path(__file__).with_name("cases.jsonl")
NOW = datetime(2026, 10, 4, 10, 0)  # a Sunday morning


def load_cases() -> list[dict]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(threshold: float, cases: list[dict], engine, retriever: Retriever) -> dict:
    with engine.begin() as conn:  # every sweep run starts with no chats handed off and no bookings
        for table in ("conversations", "handoffs", "appointments"):
            conn.execute(text(f"DELETE FROM {table}"))
    agent = Agent(engine, retriever, notify=None, clock=lambda: NOW, threshold=threshold, staff_to="")
    results = []
    for i, case in enumerate(cases):
        reply = agent.chat(f"+9655{i:07d}", case["message"])
        got = f"faq:{reply.sources[0]}" if reply.route == "faq" else reply.route
        exp = case["expected"]
        if exp.startswith("faq:"):
            ok = reply.route == "faq" and reply.sources[0] in exp[4:].split("|")
        else:
            ok = reply.route == exp
        # dangerous = we answered from the knowledge base when we should not have, or used the wrong article
        dangerous = reply.route == "faq" and not ok
        results.append({**case, "got": got, "ok": ok, "dangerous": dangerous, "score": reply.score})
    n = len(results)
    faq_cases = [r for r in results if r["expected"].startswith("faq:")]
    return {
        "threshold": threshold,
        "accuracy": sum(r["ok"] for r in results) / n,
        "wrong_answers": sum(r["dangerous"] for r in results),
        "kb_questions_answered": sum(r["ok"] for r in faq_cases) / len(faq_cases),
        "n": n,
        "results": results,
    }


def main() -> None:
    cases = load_cases()
    retriever = Retriever()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch.object(config, "GEMINI_API_KEY", ""):
        engine = make_engine(f"sqlite:///{tmp}/eval.db")
        seed(engine, busy_days=0)
        sweep = [run(t / 100, cases, engine, retriever) for t in range(4, 21, 1)]
        chosen = run(config.ANSWER_THRESHOLD, cases, engine, retriever)
        engine.dispose()

    lines = [
        "# Evaluation", "",
        f"{chosen['n']} hand-written Gulf-Arabic and English messages (`eval/cases.jsonl`), each the first "
        "message of a new chat, LLM off.", "",
        f"**Threshold {chosen['threshold']}** → route accuracy **{chosen['accuracy']:.1%}**, "
        f"knowledge-base questions answered from the right article **{chosen['kb_questions_answered']:.1%}**, "
        f"wrong answers **{chosen['wrong_answers']}**.", "",
        "## Threshold sweep", "",
        "| threshold | accuracy | KB questions answered | wrong answers |", "|---|---|---|---|",
        *[f"| {s['threshold']:.2f} | {s['accuracy']:.1%} | {s['kb_questions_answered']:.1%} | {s['wrong_answers']} |"
          for s in sweep],
        "", "A low threshold answers more questions but risks answering things the clinic never wrote down; "
        "a high one hands off too often. We pick the value with zero wrong answers and the most questions answered.",
        "", "Caveat: the threshold was chosen on these same 66 messages, so treat the numbers as optimistic. "
        "Add real (anonymised) chats to `eval/cases.jsonl` as they come in and re-run.",
        "", "## Misses at the chosen threshold", "",
        "| message | expected | got | score |", "|---|---|---|---|",
        *[f"| {r['message']} | {r['expected']} | {r['got']} | {r['score']} |" for r in chosen["results"] if not r["ok"]],
    ]
    config.REPORTS_DIR.mkdir(exist_ok=True)
    (config.REPORTS_DIR / "eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {k: v for k, v in chosen.items() if k != "results"}
    (config.REPORTS_DIR / "eval.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    for s in sweep:
        print(f"t={s['threshold']:.2f} acc={s['accuracy']:.3f} kb={s['kb_questions_answered']:.3f} wrong={s['wrong_answers']}")
    for r in chosen["results"]:
        if not r["ok"]:
            print("MISS", r["expected"], "->", r["got"], r["score"], "|", r["message"])
    if "--gate" in sys.argv and (chosen["wrong_answers"] > 0 or chosen["accuracy"] < 0.9):
        sys.exit("Release gate failed: the bot answered something it should not have, or accuracy < 90%")


if __name__ == "__main__":
    main()
