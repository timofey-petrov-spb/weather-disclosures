"""Compare the development table cells with the source reference sealed in the prior study."""
import argparse
import json
from decimal import Decimal
from pathlib import Path
import re

from replay_study import HERE, STUDY, filing_replay
from review_tables import read_tables

MEASURE_WORDS = {
    "PX05-gross": ("gross", "incurred", "loss"), "PX05-net": ("net", "incurred", "loss"),
    "CV05-net": ("net", "incurred", "property", "loss"),
    "PH05-personal": ("net", "loss", "adjustment", "expense"),
    "PH05-commercial": ("net", "loss", "adjustment", "expense"),
    "PH05-total": ("net", "loss", "adjustment", "expense"),
}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("replay",type=Path)
    ap.add_argument("--primary-files",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    old=STUDY/"event-accounting"
    refs=json.loads((old/"independent-reference.json").read_text(encoding="utf-8"))["claims"]
    roster=json.loads((old/"filings.json").read_text(encoding="utf-8"))
    summary={}
    for f in roster:
        if f["role"]!="holdout":
            continue
        doc=f["doc_id"]
        rows=[json.loads(line) for line in (args.replay/doc/"inputs.jsonl").read_text(encoding="utf-8").splitlines()]
        body=filing_replay.acquire(f,args.primary_files)
        tables={tab.number:tab for tab in read_tables(body,rows)}
        evidence={r["passage_id"]:r["text"] for r in rows}
        gold=[r for r in refs if r["doc_id"]==doc]
        versions={}
        for v in ("v9","v10"):
            output=json.loads((args.replay/doc/(v+".json")).read_text(encoding="utf-8-sig"))
            details=[]
            for r in gold:
                grid=tables[r["table"]].rows[r["row"]-1]
                source=next(c for c in grid.cells if c.covers(r["column"]-1))
                assert source.text==r["printed"] and Decimal(source.text.replace(",",""))*r["usd_scale"]==r["signed_low_usd"]
                hits=[(entry,obs) for entry in output if not entry["review"] for obs in entry.get("table_observations",[])
                      if tuple(obs["amount_cell"][k] for k in ("table","row","column"))==(r["table"],r["row"],r["column"])]
                checks=[]
                for entry,obs in hits:
                    seg=r["id"].split("-")[1]
                    if seg in ("personal","commercial"):
                        owner=seg+" lines" in (entry.get("segment") or entry.get("affected_entity") or "").casefold()
                    else:
                        owner=not entry.get("segment") and entry.get("affected_entity")==f["issuer"]
                    meaning=all(w in entry["measure"].lower() for w in MEASURE_WORDS[r["id"]])
                    basis="gross" if seg=="gross" else "net"
                    correct=bool(owner and meaning and basis in (entry["basis"] or "") and entry["event"].lower() in r["event"].lower()
                                 and entry.get("signed_usd")==r["signed_low_usd"] and entry["low_usd"]==entry["high_usd"]==abs(r["signed_low_usd"])
                                 and entry.get("currency")=="USD" and entry.get("unit_scale")==r["usd_scale"])
                    chain=entry.get("evidence_passage_ids",[])
                    assert all(pid in evidence for pid in chain)
                    checks.append(dict(correct=correct,signed_usd=entry.get("signed_usd"),measure=entry["measure"],owner=entry.get("affected_entity"),
                                       basis=entry.get("basis"),tax=entry.get("tax_basis"),status=entry.get("status"),
                                       window=entry.get("reporting_or_recognition_period"),occurrences=entry.get("event_dates",[]),
                                       scale=entry.get("unit_scale"),unit=obs.get("unit_evidence"),source_passages=chain))
                details.append(dict(id=r["id"],coordinate=[r["table"],r["row"],r["column"]],original_cell=source.text,reference_usd=r["signed_low_usd"],
                                    correct=(len(checks)==1 and checks[0]["correct"]),outputs=checks))
            selected=gold[0]["table"]
            extras=[dict(passage=r["passage_id"],usd=r["low_usd"],measure=r["measure"],review=r["review"]) for r in output
                    if not any(o["amount_cell"]["table"]==selected for o in r.get("table_observations",[]))]
            versions[v]=dict(matched=sum(x["correct"] for x in details),reference=len(gold),details=details,other_records=extras)
        summary[doc]=versions
    args.output.write_bytes((json.dumps(summary,indent=2,ensure_ascii=False)+"\n").encode())
    for doc,results in summary.items():
        print(doc,{v:(r["matched"],r["reference"]) for v,r in results.items()})


if __name__=="__main__":
    main()

