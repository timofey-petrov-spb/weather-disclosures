"""Build the offline disclosure explorer from the two versioned reference sets."""
import argparse
import json
from pathlib import Path

from review import ROOT


def read(name):
    return json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))


def records():
    sources = {s["doc_id"]: s for s in read("sources.json")}
    all_rows = []
    for c in read("worked_claims.json"):
        s = sources[c["doc_id"]]
        value = c["amount"]
        all_rows.append(dict(id=c["id"], issuer=c["issuer"], event=" + ".join(c["events"]),
                             time=s["accepted_at_utc"], period=c["period"], status=c["status"],
                             metric=c["metric"], basis=c["basis"], affected=c["affected_entity"],
                             value=[value["low"], value["high"]] if value else None,
                             relations=c["relations"], source=s["url"], accession=s["accession"],
                             kind="Development example", group=None))
    statuses = {s["accession"]: s for s in read("validation_status.json")}
    frozen = {f["accession"]: f for f in read("evaluation_filings.json")["filings"]}
    for c in read("validation_reference.json")["claims"]:
        s = statuses[c["accession"]]
        issuer = frozen[c["accession"]]["issuer"]
        amount = c["value_usd"] / 1_000_000
        all_rows.append(dict(id=c["id"], issuer=issuer, event=" + ".join(c["events"]), time=s["accepted_at_utc"],
                             period=c["period"], status=c["status"], metric=c["metric"],
                             basis=c["locator"], affected=issuer, value=[amount, amount], relations=[],
                             source=c["source_url"], accession=c["accession"], kind="Evaluation reference",
                             group=c.get("fact_group")))
    return sorted(all_rows, key=lambda r: (r["time"], r["id"]))


def build(path):
    template = (ROOT / "research" / "explorer.html").read_text(encoding="utf-8")
    # Prevent a source string from closing the JSON script element.
    encoded = json.dumps(records(), ensure_ascii=True).replace("<", "\\u003c")
    path.write_text(template.replace("__EVIDENCE_RECORDS__", encoded), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    build(parser.parse_args().output)
