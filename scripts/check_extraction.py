"""Check grounded monetary-role extraction on known development examples and diagnostic probes."""
import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
import re

from extract import extract, extract_passage
from review import PASSAGES, ROOT, load_passages


FIELDS = ("metric", "status", "events", "period")
NEGATIVE_CONTROLS = {
    "SEC-4-P00571": ("$26 million",),
    "SEC-1-P00575": ("$157 million", "$145 million"),
}


def grounded(prediction, passage):
    """Offsets, exact sentence and source hash must identify the same original money mention."""
    start, end = prediction["start"], prediction["end"]
    text, quote = passage["text"], prediction["quote"]
    if not (isinstance(start, int) and isinstance(end, int) and
            0 <= start < end <= len(text) and text[start:end] == prediction["raw"] and quote):
        return False
    sentence_start = text.rfind(quote, max(0, end - len(quote)), start + len(quote))
    return (0 <= sentence_start <= start and sentence_start + len(quote) >= end
            and prediction["doc_id"] == passage["doc_id"]
            and prediction["passage_id"] == passage["passage_id"]
            and prediction["source_sha256"] == passage["source_sha256"])


def same_amount(prediction, amount):
    if amount["unit"] != "USD million":
        raise ValueError(f"Undefined development gold unit: {amount['unit']}")
    values = (prediction["low_usd"], prediction["high_usd"])
    if any(v is None for v in values):
        return False
    return tuple(Decimal(str(v)) for v in values) == tuple(
        Decimal(str(amount[k])) * 1_000_000 for k in ("low", "high"))


def events(names):
    return sorted({name.casefold() for name in names})


def summary_row(row):
    return {key: row[key] for key in ("passage_id", "start", "end", "raw", "low_usd",
                                      "high_usd", "metric", "status", "events", "period", "linked")}


def identity(row):
    return row["doc_id"], row["passage_id"], row["start"], row["end"]


def inspect_development(passages, claims, k):
    by_doc = defaultdict(list)
    for passage in passages:
        by_doc[passage["doc_id"]].append(passage)
    selections, strict_owners, meanings, cases = {}, defaultdict(set), defaultdict(set), []
    for claim in claims:
        doc, case_id = claim["doc_id"], claim["id"]
        case = dict(case=case_id, doc_id=doc, readable=bool(by_doc.get(doc)))
        cases.append(case)
        if claim["amount"] is None:
            case["outcome"] = "outside monetary scope"
            continue
        gold_passages = {p["passage_id"]: p for p in by_doc[doc]
                         if all(re.search(pattern, p["text"], re.I) for pattern in claim["find_in_passage"])}
        case.update(gold_passages=sorted(gold_passages), candidates=[], strict_matches=[])
        if not by_doc[doc] or not gold_passages:
            case["outcome"] = "unavailable source or anchor"
            continue
        query = claim["events"][0].lower()
        if (doc, query) not in selections:
            selections[doc, query] = extract(by_doc[doc], event=query, top=k, doc_id=doc)
            for row in selections[doc, query]:
                meanings[identity(row)].add((row["low_usd"], row["high_usd"], row["metric"], row["status"],
                                             row["period"], tuple(events(row["events"])), row["linked"]))
        for row in selections[doc, query]:
            passage = gold_passages.get(row["passage_id"])
            if passage is None or not grounded(row, passage) or not same_amount(row, claim["amount"]):
                continue
            checks = {field: (events(row[field]) == events(claim[field]) if field == "events"
                              else row[field] == claim[field]) for field in FIELDS}
            case["candidates"].append(dict(row=summary_row(row), checks=checks))
            if row["linked"] and all(checks.values()):
                strict_owners[identity(row)].add(case_id)
                case["strict_matches"].append(identity(row))
        case["outcome"] = "missed"

    # Two independent citations of one gold fact can support it once. A span with
    # conflicting assignments is never reused or awarded to an arbitrary claimant.
    for case in cases:
        if case["outcome"] != "missed":
            continue
        strict_matches = sorted(set(case["strict_matches"]))
        unique = [span for span in strict_matches
                  if strict_owners[span] == {case["case"]} and len(meanings[span]) == 1]
        if unique:
            case.update(outcome="exact", matched_span=unique[0])
        elif strict_matches:
            case["outcome"] = "ambiguous span assignment"

    monetary = [c for c in cases if c["outcome"] != "outside monetary scope"]
    supported = [c for c in monetary if c["gold_passages"]]
    # Diagnostics are marginal counts. Exact matching above requires every
    # field on one linked, source-grounded amount mention.
    field_counts = {field: sum(any(item["row"]["linked"] and item["checks"][field]
                                   for item in c["candidates"]) for c in supported) for field in FIELDS}
    return dict(unit="preselected monetary claim", k_per_document=k, available=len(supported),
                total=len(monetary), exact=sum(c["outcome"] == "exact" for c in monetary),
                grounded_amount=sum(bool(c["candidates"]) for c in supported),
                linked_amount=sum(any(item["row"]["linked"] for item in c["candidates"]) for c in supported),
                linked_grounded_amount_with_field=field_counts, cases=cases)


def is_attribution(row):
    return bool(row["linked"] and row["metric"])


def check_probe(passage, event, expected):
    found = extract_passage(passage, event=event)
    # Each diagnostic specification identifies a unique literal. Fail loudly if
    # a future probe needs a more precise span identifier.
    expected_raw = {e["raw"] for e in expected}
    if len(expected_raw) != len(expected) or any(passage["text"].count(raw) != 1 for raw in expected_raw):
        raise ValueError(f"Ambiguous or missing probe annotation in {passage['passage_id']}")
    results = []
    covered = set()
    for target in expected:
        # For abstention controls, "$0.08" in a longer "$0.08 per share"
        # annotation is the very same occurrence. Positive probes still demand
        # the exact annotated surface form as well as its meaning.
        start = passage["text"].index(target["raw"])
        end = start + len(target["raw"])
        detected = [r for r in found if r["start"] < end and start < r["end"]]
        covered.update(identity(r) for r in detected)
        assigned = [r for r in detected if is_attribution(r)]
        if target["metric"] is None:
            passed = not assigned
        else:
            passed = (len(assigned) == 1 and assigned[0]["raw"] == target["raw"] and grounded(assigned[0], passage)
                      and assigned[0]["metric"] == target["metric"] and assigned[0]["status"] == target["status"])
        results.append(dict(raw=target["raw"], expected_metric=target["metric"], expected_status=target["status"],
                            detected=[summary_row(r) for r in detected],
                            attributed=[summary_row(r) for r in assigned], passed=passed))
    extras = [summary_row(r) for r in found if is_attribution(r) and identity(r) not in covered]
    return dict(passage_id=passage["passage_id"], event=event, source_sha256=passage["source_sha256"],
                checks=results, detected=[summary_row(r) for r in found], extra_attributions=extras,
                missed=[r["raw"] for r in results if not r["passed"] and r["expected_metric"] is not None],
                passed=all(r["passed"] for r in results) and not extras)


def run_probes(probes):
    output = []
    for probe in probes:
        sentence = probe["sentence"]
        event = re.search(r"\bHurricanes?\s+([A-Za-z]+)", sentence, re.I)
        if event is None:
            raise ValueError(f"Specify a named storm in {probe['id']}")
        row = dict(doc_id=probe["id"], passage_id=probe["id"], text=sentence, issuer="Synthetic issuer",
                   page=1, url=None, canonical_url=None, accepted_at_utc=None,
                   source_sha256=hashlib.sha256(sentence.encode("utf-8")).hexdigest())
        output.append(check_probe(row, event.group(1).lower(), probe["expect"]))
    return output


def run_controls(passages):
    by_id = {row["passage_id"]: row for row in passages}
    results = []
    for passage_id, amounts in NEGATIVE_CONTROLS.items():
        if passage_id not in by_id:
            results.append(dict(passage_id=passage_id, outcome="unavailable", passed=None))
            continue
        expected = [dict(raw=amount, metric=None, status="unknown") for amount in amounts]
        results.append(check_probe(by_id[passage_id], "helene", expected))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=3, help="Maximum anchor windows per document.")
    parser.add_argument("--json", action="store_true", help="Show individual matches, hits, misses and provenance.")
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be greater than zero")
    if not PASSAGES.is_file():
        parser.exit(1, "Run scripts/collect.py to build the development corpus.\n")
    data = ROOT / "data"
    claims_file, probes_file = data / "worked_claims.json", data / "money_role_probes.json"
    passages = load_passages(PASSAGES)
    dev = inspect_development(passages, json.loads(claims_file.read_text(encoding="utf-8")), args.k)
    probes = run_probes(json.loads(probes_file.read_text(encoding="utf-8")))
    controls = run_controls(passages)
    if args.json:
        report = dict(development=dev, synthetic_probes=probes, document_negative_controls=controls,
                      input_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                    for path in (PASSAGES, claims_file, probes_file)},
                      limits="Incomplete development annotations. No corpus precision or generalization estimate. "
                             "Probes and document controls test attribution directly and bypass retrieval. "
                             "Exact development matches cover the selected monetary field set; issuer is given by "
                             "the filing. Entity, business segment, insurance basis and cross-filing revisions are "
                             "not scored. Synthetic probes score only the annotated money roles and statuses.")
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return
    print(f"Known monetary claims: {dev['exact']}/{dev['total']} exact at k={args.k} "
          f"({dev['available']} source-anchored); no corpus precision estimate.")
    for case in dev["cases"]:
        print(case["case"], case["outcome"])
    for label, group in (("Synthetic", probes), ("Document controls", controls)):
        print(f"{label}: {sum(r['passed'] is True for r in group)}/{len(group)} full cases passed.")
        for row in group:
            for check in row.get("checks", []):
                roles = ", ".join(f"{v['metric']} / {v['status']}" for v in check["attributed"]) or "abstained"
                print(row["passage_id"], check["raw"], roles, "OK" if check["passed"] else "FAIL")
            for extra in row.get("extra_attributions", []):
                print(row["passage_id"], extra["raw"], "unexpected attribution")
            if row["passed"] is None:
                print(row["passage_id"], "unavailable")


if __name__ == "__main__":
    main()
