"""Run the leasing-assistant eval and write evals/results.md.

    python evals/run_eval.py --provider mock               # CI smoke test, no API key
    python evals/run_eval.py --provider anthropic          # real Claude, needs credentials

Creates a throwaway database (leaseloop_eval), loads fixture.py, runs each inquiry
in a rolled-back transaction with the clock fixed at fixture.EVAL_NOW, and scores:
outcome (answer vs handoff), expected facts, forbidden strings, expected tool calls,
and whether a tour was booked.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings_test")

# $/MTok (input, output) for cost estimates; keep in sync with the model in use.
PRICING = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


def norm(text: str) -> str:
    return " ".join(text.lower().replace(",", "").split())


def has_fact(text: str, fact: str) -> bool:
    return any(norm(alt) in norm(text) for alt in fact.split("|"))


def score(item: dict, reply, booked: bool) -> dict:
    exp = item["expect"]
    called = {c["name"] for c in reply.tools_called if c["ok"]}
    checks = {"outcome": reply.handed_off == (exp["outcome"] == "handoff")}
    if exp["outcome"] == "answer":
        checks["facts"] = all(has_fact(reply.text, f) for f in exp.get("facts", []))
    checks["not"] = not any(has_fact(reply.text, f) for f in exp.get("not", []))
    if exp.get("tools"):
        checks["tools"] = set(exp["tools"]) <= called
    if "booked" in exp:
        checks["booked"] = booked == exp["booked"]
    elif exp["outcome"] == "handoff":
        checks["booked"] = not booked
    if exp.get("reason"):
        checks["reason"] = reply.handoff_reason == exp["reason"]
    return checks


def pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def run(args) -> dict:
    import django

    django.setup()
    from apps.assistant.guardrails import ungrounded_prices
    from apps.assistant.providers import get_provider
    from apps.assistant.service import Assistant
    from apps.assistant.tools import AssistantContext
    from apps.crm.models import Channel, Conversation, Prospect, Tour
    from django.conf import settings
    from django.db import connection, transaction

    from evals import fixture

    original_name = settings.DATABASES["default"]["NAME"]
    connection.settings_dict["TEST"]["NAME"] = "leaseloop_eval"
    connection.creation.create_test_db(verbosity=0, autoclobber=True, keepdb=False)
    try:
        data = fixture.build()
        lines = (ROOT / "evals/inquiries.jsonl").read_text().splitlines()
        items = [json.loads(line) for line in lines if line.strip()]
        if args.category:
            items = [i for i in items if i["category"] == args.category]
        if args.ids:
            wanted = set(args.ids.split(","))
            items = [i for i in items if i["id"] in wanted]
        if args.limit:
            items = items[: args.limit]
        assistant = Assistant(get_provider(args.provider))
        rows = []
        for n, item in enumerate(items, 1):
            with transaction.atomic():
                prop = data[item["property"]]
                prospect = Prospect.objects.create(
                    organization=data["org"],
                    first_name="Eval",
                    last_name=item["id"],
                    email=f"{item['id']}@eval.test",
                    source="CHAT",
                    interested_property=prop,
                )
                conv = Conversation.objects.create(
                    organization=data["org"], prospect=prospect, channel=Channel.CHAT
                )
                ctx = AssistantContext(
                    prop=prop,
                    now=fixture.EVAL_NOW,
                    mode="chat",
                    prospect=prospect,
                    conversation=conv,
                )
                started = time.perf_counter()
                reply = assistant.respond(ctx, item["question"])
                elapsed = (time.perf_counter() - started) * 1000
                booked = Tour.objects.filter(prospect=prospect, booked_by="ASSISTANT").exists()
                checks = score(item, reply, booked)
                rows.append(
                    {
                        "id": item["id"],
                        "category": item["category"],
                        "question": item["question"],
                        "expect": item["expect"],
                        "reply": reply.text,
                        "handoff_reason": reply.handoff_reason,
                        "guardrail": reply.guardrail,
                        "tools": [c["name"] for c in reply.tools_called],
                        "invalid_tool_calls": sum(not c["ok"] for c in reply.tools_called),
                        "booked": booked,
                        "checks": checks,
                        "correct": all(checks.values()),
                        "final_ungrounded": sorted(
                            map(str, ungrounded_prices(reply.text, reply.sources))
                        )
                        if not reply.handed_off
                        else [],
                        "latency_ms": round(elapsed),
                        "input_tokens": reply.input_tokens,
                        "output_tokens": reply.output_tokens,
                        "model": reply.model,
                    }
                )
                transaction.set_rollback(True)
            if args.verbose or not rows[-1]["correct"]:
                r = rows[-1]
                print(
                    f"[{n}/{len(items)}] {'PASS' if r['correct'] else 'FAIL'} {r['id']}: "
                    f"{r['question'][:60]!r} -> {r['handoff_reason'] or r['reply'][:80]!r} "
                    f"{ {k: v for k, v in r['checks'].items() if not v} or ''}",
                    flush=True,
                )
        return {
            "rows": rows,
            "provider": args.provider,
            "model": next((r["model"] for r in rows if r["model"]), args.provider),
        }
    finally:
        connection.creation.destroy_test_db(original_name, verbosity=0)


def summarize(result: dict) -> dict:
    rows = result["rows"]
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    tool_rows = [r for r in rows if r["expect"].get("tools")]
    exp_h = [r for r in rows if r["expect"]["outcome"] == "handoff"]
    got_h = [r for r in rows if r["handoff_reason"]]
    tp = sum(1 for r in got_h if r["expect"]["outcome"] == "handoff")
    fh = [r for r in rows if r["expect"].get("reason") == "FAIR_HOUSING"]
    lat = [r["latency_ms"] for r in rows]
    return {
        "n": len(rows),
        "correct": sum(r["correct"] for r in rows),
        "by_category": {c: (sum(r["correct"] for r in rs), len(rs)) for c, rs in by_cat.items()},
        "tool_correct": sum(r["checks"].get("tools", False) for r in tool_rows),
        "tool_n": len(tool_rows),
        "invalid_tool_calls": sum(r["invalid_tool_calls"] for r in rows),
        "booking_correct": sum(r["checks"]["booked"] for r in rows if "booked" in r["expect"]),
        "booking_n": sum(1 for r in rows if "booked" in r["expect"]),
        "handoff_tp": tp,
        "handoff_pred": len(got_h),
        "handoff_exp": len(exp_h),
        "fh_caught": sum(1 for r in fh if r["handoff_reason"] == "FAIR_HOUSING"),
        "fh_n": len(fh),
        "price_caught": sum(1 for r in rows if r["guardrail"] == "ungrounded price"),
        "price_final": sum(len(r["final_ungrounded"]) for r in rows),
        "lat_p50": statistics.median(lat) if lat else 0,
        "lat_p95": sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else 0,
        "in_tok": sum(r["input_tokens"] for r in rows),
        "out_tok": sum(r["output_tokens"] for r in rows),
    }


def write_markdown(result: dict, s: dict, path: Path) -> None:
    rows = result["rows"]
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    prec = s["handoff_tp"] / s["handoff_pred"] if s["handoff_pred"] else 0
    rec = s["handoff_tp"] / s["handoff_exp"] if s["handoff_exp"] else 0
    lines = [
        "# Leasing assistant eval results",
        "",
        f"- Provider: **{result['provider']}** (model: `{result['model']}`)",
        f"- Run: {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, commit `{commit}`, "
        f"{s['n']} inquiries from `evals/inquiries.jsonl`",
        "- Data: `evals/fixture.py`, clock fixed at Monday 2026-11-02 10:00 America/New_York",
        "",
    ]
    if result["provider"] == "mock":
        lines += [
            "> **These numbers come from the mock provider**, a deterministic keyword router "
            "that drives the same tool loop and guardrails as the real model. They show that "
            "the pipeline, tools, guardrails and scoring work end to end without an API key. "
            "They are **not** a measure of language-model quality. Run with "
            "`--provider anthropic` for that.",
            "",
        ]
    lines += [
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Overall accuracy | **{pct(s['correct'], s['n'])}** ({s['correct']}/{s['n']}) |",
        f"| Tool-call correctness (expected tool called successfully) | "
        f"{pct(s['tool_correct'], s['tool_n'])} ({s['tool_correct']}/{s['tool_n']}) |",
        f"| Tour booking outcome correct | {pct(s['booking_correct'], s['booking_n'])} "
        f"({s['booking_correct']}/{s['booking_n']}) |",
        f"| Invalid tool calls (tool returned an error) | {s['invalid_tool_calls']} |",
        f"| Handoff precision | {prec:.2f} ({s['handoff_tp']}/{s['handoff_pred']}) |",
        f"| Handoff recall | {rec:.2f} ({s['handoff_tp']}/{s['handoff_exp']}) |",
        f"| Fair-housing questions handed off as FAIR_HOUSING | {s['fh_caught']}/{s['fh_n']} |",
        f"| Hallucinated prices in final answers | **{s['price_final']}** |",
        f"| Answers blocked by the price-grounding guardrail | {s['price_caught']} |",
        f"| Latency per inquiry p50 / p95 | {s['lat_p50']:.0f} ms / {s['lat_p95']:.0f} ms |",
    ]
    if s["in_tok"]:
        cin, cout = PRICING.get(result["model"], (0, 0))
        cost = (s["in_tok"] * cin + s["out_tok"] * cout) / 1e6
        lines.append(
            f"| Tokens in / out (estimated cost) | {s['in_tok']:,} / {s['out_tok']:,} "
            f"(${cost:.2f}) |"
        )
    lines += [
        "",
        "## Accuracy by category",
        "",
        "| Category | Correct | Accuracy |",
        "|---|---:|---:|",
    ]
    for cat, (ok, n) in s["by_category"].items():
        lines.append(f"| {cat} | {ok}/{n} | {pct(ok, n)} |")
    fails = [r for r in rows if not r["correct"]]
    lines += ["", f"## Failures ({len(fails)})", ""]
    if fails:
        lines += ["| ID | Question | Failed checks | Got |", "|---|---|---|---|"]
        for r in fails:
            got = f"handoff: {r['handoff_reason']}" if r["handoff_reason"] else r["reply"][:120]
            failed = ", ".join(k for k, v in r["checks"].items() if not v)
            q = r["question"].replace("|", "/")
            lines.append(f"| {r['id']} | {q} | {failed} | {got.replace('|', '/')} |")
    lines += [
        "",
        "## How it is scored",
        "",
        "An inquiry is correct only if every applicable check passes:",
        "- **outcome**: answered vs handed off, as expected;",
        "- **facts**: each expected fact appears in the reply (`a|b` = either);",
        "- **not**: no forbidden string appears (for example a false price from the question);",
        "- **tools**: the expected tools were called and succeeded;",
        "- **booked**: a tour was booked if and only if expected;",
        "- **reason**: the handoff reason matches, where one is specified.",
        "",
        "A hallucinated price is a dollar amount in a final answer that doesn't appear in "
        "a tool result or in the policy text given to the model. Small multiples and sums "
        "of those amounts are allowed.",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="mock", choices=["mock", "anthropic"])
    ap.add_argument("--out", default=str(ROOT / "evals/results.md"))
    ap.add_argument("--json", default="")
    ap.add_argument("--category")
    ap.add_argument("--ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument(
        "--min-accuracy",
        type=float,
        default=0.0,
        help="exit 1 if overall accuracy is below this fraction (CI gate)",
    )
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    result = run(args)
    s = summarize(result)
    write_markdown(result, s, Path(args.out))
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1, default=str))
    acc = s["correct"] / s["n"] if s["n"] else 0
    print(
        f"\naccuracy {acc:.1%} ({s['correct']}/{s['n']}), hallucinated prices "
        f"{s['price_final']}, handoff P/R {s['handoff_tp']}/{s['handoff_pred']} "
        f"{s['handoff_tp']}/{s['handoff_exp']} -> {args.out}"
    )
    if s["price_final"] > 0 or acc < args.min_accuracy:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
