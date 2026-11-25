"""Replay the frozen retriever and amount rules against a source-first filing audit."""
import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

from check_extraction import grounded
from extract import extract_passage
from review import ROOT, load_passages, review


EVENTS = ("helene", "milton")
K = 3


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold().replace("’", "'")
    return re.sub(r"\s+", " ", re.sub(r"\$\s+", "$", text)).strip()


def build_queue(passages):
    """Collect candidates separately for each event without counting an overlapping span twice."""
    groups = defaultdict(list)
    for row in passages:
        groups[row["doc_id"]].append(row)
    selected = defaultdict(set)
    predictions = defaultdict(dict)
    for doc, rows in groups.items():
        # The development corpus uses SEC-* document aliases. Only this routing
        # key changes. Ranking, passage boundaries and text stay untouched.
        routing_key = doc if doc.startswith("SEC-") else "SEC-" + doc
        routed = [dict(row, doc_id=routing_key) for row in rows]
        by_id = {row["passage_id"]: row for row in rows}
        for event in EVENTS:
            ids = {p["passage_id"] for hit in review(routed, event, K, doc_id=routing_key) for p in hit["evidence"]}
            for pid in sorted(ids):
                selected[doc].add(pid)
                for item in extract_passage(by_id[pid], event):
                    if item["linked"] and grounded(item, by_id[pid]):
                        key = (pid, item["start"], item["end"], tuple(sorted(item["events"])))
                        predictions[doc][key] = item
    return selected, predictions


def inspect_claim(claim, rows, selected, predictions):
    # The audit supplies a short verbatim anchor and the identity of the original
    # document. A dollar amount appearing elsewhere cannot satisfy this test.
    anchor = normalize(claim["anchor"])
    if not anchor:
        raise ValueError(f"Empty audit anchor for {claim['id']}")
    amount_text = normalize(claim["raw"])
    if amount_text not in anchor:
        raise ValueError(f"Anchor omits the annotated amount in {claim['id']}")
    matched = {p["passage_id"]: p for p in rows if anchor in normalize(p["text"])}
    fields = ["metric", "status", "events", "period"]
    supported = []
    for item in predictions.values():
        if item["passage_id"] not in matched or item["low_usd"] != claim["value_usd"] or item["high_usd"] != claim["value_usd"]:
            continue
        passage = matched[item["passage_id"]]["text"]
        # Restrict the match to the particular money occurrence within the cited anchor.
        marker = "zzamountoccurrencezz"
        marked = normalize(passage[:item["start"]] + marker + passage[item["end"]:])
        if anchor.replace(amount_text, marker, 1) not in marked:
            continue
        checks = dict(metric=item["metric"] == claim["metric"], status=item["status"] == claim["status"],
                      events=sorted(map(str.lower, item["events"])) == sorted(map(str.lower, claim["events"])),
                      period=normalize(item["period"] or "").replace("-", " ") == normalize(claim["period"]).replace("-", " "))
        supported.append(dict(passage_id=item["passage_id"], start=item["start"], end=item["end"], checks=checks))
    return dict(id=claim["id"], accession=claim["accession"], doc_id=claim["doc_id"],
                value_usd=claim["value_usd"], metric=claim["metric"], events=claim["events"], period=claim["period"],
                source_url=claim["source_url"], anchor=claim["anchor"], located=bool(matched),
                retrieved=bool(set(matched) & selected), linked_amount=bool(supported),
                strict_match=any(all(s["checks"][field] for field in fields) for s in supported),
                matched_passages=sorted(matched), candidates=supported)


def evaluate(passages, reference, filings):
    pool = {f["accession"] for f in filings}
    if pool != {f["accession"] for f in reference["filings"]}:
        raise ValueError("Audit and frozen selection differ")
    if not passages or any(p["accession"] not in pool for p in passages):
        raise ValueError("Missing validation passages or unexpected accession")
    groups = defaultdict(list)
    for row in passages:
        groups[row["doc_id"]].append(row)
    selected, predictions = build_queue(passages)
    cases = [inspect_claim(c, groups[c["doc_id"]], selected[c["doc_id"]], predictions[c["doc_id"]])
             for c in reference["claims"]]
    summary = {key: sum(c[key] for c in cases) for key in ("located", "retrieved", "linked_amount", "strict_match")}
    actual_accessions = {p["accession"] for p in passages}
    return dict(rules_commit="e94cca9", events=EVENTS, windows_per_document_per_event=K,
                evaluation_unit="A reference monetary disclosure in one document; an issuer may repeat a fact in another filing.",
                accessions_selected=len(pool), accessions_with_text=len(actual_accessions),
                missing_accessions=sorted(pool - actual_accessions), documents=len(groups), passages=len(passages),
                documents_with_windows=sum(bool(v) for v in selected.values()),
                unique_passages_queued=sum(map(len, selected.values())),
                emitted_grounded_linked_spans=sum(map(len, predictions.values())),
                documented_claims=len(cases), reference_matches=summary, cases=cases,
                limits="Two companies in one sector. The reference is an AI-assisted source review. "
                       "Counts describe the documented cases. Coverage of all possible claims and population precision are unknown.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write the complete measured report to this path.")
    args = parser.parse_args()
    data = ROOT / "data"
    files = {k: data / n for k, n in dict(passages="validation_passages.jsonl",
                                            audit="validation_reference.json", selection="evaluation_filings.json").items()}
    missing = [p.name for p in files.values() if not p.is_file()]
    if missing:
        parser.exit(1, f"Missing {', '.join(missing)}. See the collection instructions in README.md.\n")
    report = evaluate(load_passages(files["passages"]), json.loads(files["audit"].read_text(encoding="utf-8")),
                      json.loads(files["selection"].read_text(encoding="utf-8"))["filings"])
    report["input_sha256"] = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items() if k not in {"cases", "input_sha256"}}, indent=2))


if __name__ == "__main__":
    main()
