"""Replay the three development documents, including source-controlled changes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

from replay_study import HERE, STUDY, filing_replay
sys.path.insert(0,str(STUDY/"v11"))
import extract as reader

PREVIOUS=STUDY/"table-context"
CONTROLS={
    "FN05": [("different date","Katrina\n                  (August 25)","Katrina\n                  (August 29)",[14600000,11600000,3000000],["2005-08-29"]),
             ("other storm","Katrina\n                  (August 25)","Maria\n                  (August 25)",[],[])],
    "MD12": [("unreconciled total",">6.5<",">5.5<",[],[]),
             ("other storm lead","in losses from Sandy, which increased","in losses from Rita, which increased",[],[])],
    "SF12": [("source-cell mismatch"," 7,977<"," 7,978<",[],[]),
             ("different accounting window","of catastrophe losses for the quarter ended December&nbsp;31","of catastrophe losses for the quarter ended September&nbsp;30",[],[])],
}

def read(p):
    return json.loads(p.read_bytes())

def analyze(f, cache, gold):
    doc=f["doc_id"]
    raw=filing_replay.acquire(f,cache)
    rows=list(filing_replay.make_rows(dict(f,paragraphs=f["rows"]),raw))
    table=gold[0]["table"]
    def table_rows(facts):
        return [(r,o["amount_cell"]) for r in facts if not r["review"]
                 for o in r.get("table_observations",[]) if o["amount_cell"]["table"]==table]
    def filtered(body):
        local=dict(f,primary_sha256=filing_replay.digest(body),paragraphs=f["rows"])
        rr=list(filing_replay.make_rows(local,body))
        return table_rows(reader.extract_filing(rr,body))
    prev=reader.v10.extract_filing(rows,raw)
    got=reader.extract_filing(rows,raw)
    ref={(r["row"],r["visible_column"]):r["signed_low_usd"] for r in gold}
    seen={(c["row"],c["column"]):r["signed_usd"] for r,c in table_rows(got)}
    assert seen==ref,(doc,seen,ref)
    cases=[]
    for name,old,new,money,dates in CONTROLS[doc]:
        if doc in ("MD12","SF12") and name in ("unreconciled total","source-cell mismatch"):
            import re
            raw_rows=re.findall(br"<tr\b[^>]*>.*?</tr\s*>",raw,re.I|re.S)
            context=next(n for n in raw_rows if old.encode() in n and
                         (b"Losses Incurred" in n if doc=="MD12" else b"Hurricane and tropical storms" in n))
            assert context.count(old.encode())==1
            edited=raw.replace(context,context.replace(old.encode(),new.encode()),1)
        else:
            assert old.encode() in raw,(doc,name)
            edited=raw.replace(old.encode(),new.encode())
        out=filtered(edited)
        observed=sorted(r["signed_usd"] for r,_ in out)
        observed_dates=sorted({d for r,_ in out for d in r.get("event_dates",[])})
        assert observed==sorted(money) and observed_dates==dates,(doc,name,observed,observed_dates)
        cases.append(dict(name=name,expected_usd=sorted(money),observed_usd=observed,dates=observed_dates))
    return doc,dict(reference=len(gold),previous=len(table_rows(prev)),recovered=len(seen),
        matched=[dict(cell=c,signed_usd=r["signed_usd"],measure=r["measure"],
                      owner=r["affected_entity"],basis=r["basis"],event_dates=r.get("event_dates",[]),
                      evidence=r["evidence_passage_ids"]) for r,c in table_rows(got)],controls=cases)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-files",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    gold=read(PREVIOUS/"reference.json")["claims"]
    roster=read(PREVIOUS/"source-filings.json")
    with ThreadPoolExecutor(3) as pool:
        jobs=[pool.submit(analyze,f,args.primary_files,[r for r in gold if r["doc_id"]==f["doc_id"]]) for f in roster]
        result=dict(job.result() for job in jobs)
    args.output.write_bytes((json.dumps(result,indent=2,ensure_ascii=False)+"\n").encode())
    print([(doc,x["previous"],x["recovered"],len(x["controls"])) for doc,x in result.items()])

if __name__=="__main__":
    main()

