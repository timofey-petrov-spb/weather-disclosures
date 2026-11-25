"""Replay the worked annotations using the SEC acceptance time as an availability proxy."""
import argparse
import json

from review import ROOT, instant


def timeline(claims, sources, cutoff, issuer):
    by_doc = {source["doc_id"]: source for source in sources}
    result = []
    for claim in claims:
        if issuer and issuer.casefold() not in claim["issuer"].casefold():
            continue
        source = by_doc[claim["doc_id"]]
        acceptance = instant(source["accepted_at_utc"])
        if acceptance <= cutoff:
            row = {k: v for k, v in claim.items() if k != "find_in_passage"}
            row.update(accepted_at_utc=source["accepted_at_utc"], canonical_url=source["url"],
                       provenance="worked annotation checked against the canonical SEC document")
            result.append(row)
    return sorted(result, key=lambda row: instant(row["accepted_at_utc"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=instant, required=True)
    parser.add_argument("--issuer", help="Substring of the reporting company's name.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    data = ROOT / "data"
    claims = json.loads((data / "worked_claims.json").read_text(encoding="utf-8"))
    sources = json.loads((data / "sources.json").read_text(encoding="utf-8"))
    rows = timeline(claims, sources, args.as_of, args.issuer)
    if args.json:
        print(json.dumps(rows, ensure_ascii=True, indent=2))
        return
    print(f"{len(rows)} manually checked annotations of canonical SEC filings at this cutoff.")
    print("Dates use SEC acceptance time. This replay reports no automated detections.")
    for row in rows:
        amount = row["amount"]
        value = "unquantified"
        if amount:
            quantity = str(amount["low"]) if amount["low"] == amount["high"] else f"{amount['low']}-{amount['high']}"
            value = f"{quantity} {amount['unit']}"
        print(f"{row['accepted_at_utc']} | {row['id']} | {row['period']} | {row['status']} | "
              f"{row['metric']} | {value} | {', '.join(row['events'])}")


if __name__ == "__main__":
    main()
