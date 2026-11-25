"""Measure retrieval of seven preselected, annotated examples, before any model comparison."""
import argparse
import json
import re
from review import PASSAGES, ROOT, load_passages, review


def evaluate(passages, claims, k):
    available_docs = {p["doc_id"] for p in passages}
    results = []
    for claim in claims:
        doc = claim["doc_id"]
        if doc not in available_docs:
            results.append(dict(case=claim["id"], outcome="document unavailable"))
            continue
        hits = review(passages, claim["events"][0], k, doc_id=doc)
        found = None
        for hit in hits:
            for evidence in hit["evidence"]:
                if all(re.search(pattern, evidence["text"], re.I) for pattern in claim["find_in_passage"]):
                    found = dict(anchor=hit["anchor"], evidence=evidence["passage_id"], rank=hit["rank"],
                                 source_sha256=hit["source_sha256"])
                    break
            if found:
                break
        results.append(dict(case=claim["id"], outcome="located" if found else "missed", match=found))
    located = sum(row["outcome"] == "located" for row in results)
    missing = sum(row["outcome"] == "document unavailable" for row in results)
    return dict(unit="preselected development question", k_per_document=k, all_cases=len(claims),
                readable_cases=len(claims) - missing, located=located, unavailable=missing, cases=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", action="store_true",
                        help="Print a reproducible JSON report at k=1 and k=3, including source fingerprints.")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be greater than zero")
    if not PASSAGES.is_file():
        parser.exit(1, "Run scripts/collect.py first.\n")
    claims = json.loads((ROOT / "data" / "worked_claims.json").read_text(encoding="utf-8"))
    passages = load_passages(PASSAGES)
    if args.report:
        status = json.loads((ROOT / "data" / "collection_status.json").read_text(encoding="utf-8"))
        fields = ("doc_id", "status", "passage_count", "edition", "replay_eligible", "sha256")
        report = dict(task="Text retrieval on seven previously known development cases.",
                      sources=[{k: row[k] for k in fields if k in row} for row in status],
                      checks=[evaluate(passages, claims, k) for k in (1, 3)])
        print(json.dumps(report, indent=2))
        return
    summary = evaluate(passages, claims, args.k)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Located {summary['located']} / {summary['all_cases']} known development cases at k={args.k}.")
        print(f"Readable cases: {summary['readable_cases']}; unavailable: {summary['unavailable']}.")
        for row in summary["cases"]:
            print(row["case"], row["outcome"], (row.get("match") or {}).get("evidence", ""))


if __name__ == "__main__":
    main()
