"""Find passages for human review in the local development corpus."""
import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PASSAGES = ROOT / "data" / "passages.jsonl"
STORMS = {"helene": r"\bHelene\b", "milton": r"\bMilton\b",
          "ian": r"\b(?:Hurricane|Storm)\s+Ian\b"}
TRIGGERS = {"helene": "NHC-1", "milton": "NHC-2", "ian": "NHC-3"}
IMPACT = re.compile(r"loss|lost revenue|expenses?|disrupt|closed|damage|recoveries|"
                    r"insurance|charges?|suspend|flood|interrupt|shut\s?down", re.I)
NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"
SCALE = r"(?:\s*(?:billion|million|thousand)\b)?"
USD = rf"(?:US\$|\$|USD\s+)\s*{NUMBER}{SCALE}"
AMOUNT = re.compile(rf"(?<![\w$]){USD}(?:\s*(?:to\b|[-–—])\s*(?:US\$|\$|USD)?\s*"
                    rf"{NUMBER}{SCALE})?(?:\s+(?:per|a)\s+(?:diluted\s+)?share\b)?", re.I)


def instant(value):
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.utcoffset() is None:
        raise ValueError("Use an explicit time zone in the cutoff, e.g. 2024-12-31T23:59:59Z")
    return timestamp


def load_passages(path):
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def review(passages, event, top, as_of=None, doc_id=None):
    """Rank direct mentions first and include adjacent context. Each hit is one evidence window."""
    storm = re.compile(STORMS[event.lower()], re.I)
    trigger_id = TRIGGERS[event.lower()]
    trigger = None
    if as_of is not None:
        bulletin = next((p for p in passages if p["doc_id"] == trigger_id and p.get("issued_at_utc")
                         and p.get("replay_eligible")), None)
        if bulletin is None or instant(bulletin["issued_at_utc"]) > as_of:
            return []
        trigger = instant(bulletin["issued_at_utc"])
    documents = defaultdict(list)
    for row in passages:
        if not row["doc_id"].startswith("SEC-") or (doc_id and row["doc_id"] != doc_id):
            continue
        if as_of is not None:
            if not row.get("replay_eligible") or not row.get("accepted_at_utc"):
                continue
            if not trigger <= instant(row["accepted_at_utc"]) <= as_of:
                continue
        documents[row["doc_id"]].append(row)
    hits = []
    for key, rows in documents.items():
        ranked = []
        for i, row in enumerate(rows):
            if not storm.search(row["text"]):
                continue
            neighbors = rows[max(0, i - 1):i + 2]
            score = (bool(IMPACT.search(row["text"])), bool(AMOUNT.search(row["text"])),
                     any(AMOUNT.search(n["text"]) for n in neighbors))
            ranked.append((score, i, neighbors))
        ranked.sort(key=lambda entry: (entry[0], -entry[1]), reverse=True)
        for rank, (_, index, neighbors) in enumerate(ranked[:top], 1):
            anchor = rows[index]
            evidence = []
            for neighbor in neighbors:
                text = neighbor["text"]
                evidence.append(dict(passage_id=neighbor["passage_id"], text=text,
                                     money_mentions=[m.group() for m in AMOUNT.finditer(text)]))
            hits.append(dict(doc_id=key, rank=rank, anchor=anchor["passage_id"], event=event.title(),
                             accepted_at_utc=anchor.get("accepted_at_utc"),
                             replay_eligible=anchor.get("replay_eligible", False),
                             source_edition=anchor.get("source_edition"), url=anchor["url"],
                             source_sha256=anchor.get("source_sha256"), evidence=evidence,
                             trigger_id=trigger_id if trigger else None,
                             trigger_issued_at=trigger.isoformat() if trigger else None))
    return hits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, type=str.lower, choices=sorted(STORMS))
    parser.add_argument("--as-of", type=instant, help="Inclusive ISO 8601 cutoff including timezone.")
    parser.add_argument("--doc", help="Restrict the search to a development document, e.g. SEC-2.")
    parser.add_argument("--top", type=int, default=3, help="Maximum windows per filing.")
    parser.add_argument("--json", action="store_true", help="Write complete evidence and source details as JSON.")
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be greater than zero")
    if not PASSAGES.exists():
        parser.exit(1, "Run scripts/collect.py to build the local development corpus.\n")
    hits = review(load_passages(PASSAGES), args.event, args.top, args.as_of, args.doc)
    if args.json:
        print(json.dumps(hits, indent=2, ensure_ascii=True))
        return
    print(f"{len(hits)} evidence windows. Amounts below are unverified mentions; windows can overlap.")
    for hit in hits:
        print(f"\n{hit['anchor']}  |  {hit['source_edition']}  |  {hit['url']}")
        for evidence in hit["evidence"]:
            print(evidence["passage_id"], evidence["text"])


if __name__ == "__main__":
    main()
