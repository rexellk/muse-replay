"""Replay past Muse actions through the MVP checks and print a scorecard.

Usage:
    python replay.py            # all data files
    python replay.py --verbose  # also print every record and its reasons

Each record has a ground-truth label ("bad" = should not have gone out,
"ok" = fine to send). The scorecard compares the check's decision to it.
Records marked "sample": true are format examples and are reported
separately, never counted in the headline.
"""

import json
import sys
from pathlib import Path

from checks import evaluate

DATA = Path(__file__).parent / "data"


def load():
    for path in sorted(DATA.glob("*.json")):
        for rec in json.loads(path.read_text())["records"]:
            rec["_file"] = path.stem
            yield rec


def score(records):
    s = {"caught": 0, "missed": 0, "false_hold": 0, "ok_sent": 0}
    for r in records:
        decision = r["_decision"]
        if r["label"] == "bad":
            s["caught" if decision == "hold" else "missed"] += 1
        else:
            s["false_hold" if decision == "hold" else "ok_sent"] += 1
    return s


def fmt(s):
    bad = s["caught"] + s["missed"]
    ok = s["false_hold"] + s["ok_sent"]
    line = f"caught {s['caught']} of {bad} bad actions"
    line += f", {s['false_hold']} false hold{'' if s['false_hold']==1 else 's'} out of {ok} good actions" if ok else ", no good actions yet (add some to measure false holds)"
    return line


def main():
    verbose = "--verbose" in sys.argv
    records = list(load())
    for r in records:
        r["_decision"], r["_reasons"] = evaluate(r)

    if verbose:
        for r in records:
            mark = "OK " if (r["_decision"] == "hold") == (r["label"] == "bad") else "XX "
            print(f"{mark}{r['id']:<10} label={r['label']:<4} -> {r['_decision']:<4}  {r['note']}")
            for reason in r["_reasons"]:
                print(f"           - {reason}")
        print()

    groups = {}
    for r in records:
        key = "samples (format only)" if r.get("sample") else r["_file"]
        groups.setdefault(key, []).append(r)

    print("Scorecard")
    print("-" * 60)
    for name, recs in groups.items():
        print(f"{name:<28} {fmt(score(recs))}")
    real = [r for r in records if not r.get("sample")]
    print("-" * 60)
    print(f"{'HEADLINE (excludes samples)':<28} {fmt(score(real))}")


if __name__ == "__main__":
    main()
