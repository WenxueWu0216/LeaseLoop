"""Print top retrieval scores for dev questions (not part of the eval) to pick
ASSISTANT_MIN_RETRIEVAL_SCORE.

    python evals/calibrate_retrieval.py
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings_test")


def main() -> None:
    import django

    django.setup()
    from apps.assistant.retrieval import search
    from django.conf import settings
    from django.db import connection

    from evals import fixture

    original = settings.DATABASES["default"]["NAME"]
    connection.settings_dict["TEST"]["NAME"] = "leaseloop_eval"
    connection.creation.create_test_db(verbosity=0, autoclobber=True, keepdb=False)
    try:
        prop = fixture.build()["maple"]
        rows = [
            json.loads(x)
            for x in (ROOT / "evals/dev_questions.jsonl").read_text().split("\n")
            if x.strip()
        ]
        for r in sorted(rows, key=lambda r: r["answerable"]):
            top = search(prop, r["question"], k=1)
            score = top[0].score if top else 0.0
            label = "answerable  " if r["answerable"] else "unanswerable"
            print(f"{score:.3f}  {label}  {r['question']}")
    finally:
        connection.creation.destroy_test_db(original, verbosity=0)


if __name__ == "__main__":
    main()
