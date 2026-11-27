"""Count source-anchored matches and misattributions for the registered passage audit."""
import argparse
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent

def read(path):
    return json.loads(path.read_bytes())

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    options=parser.parse_args()
    cases=read(HERE/"reference.json")["cases"]
    results={}
    for version in ("v10","v11"):
        per_case={}
        for case in cases:
            doc=case["doc"]
            records=read(options.replay/doc/(version+".json"))
            matches=set()
            errors=set()
            inside=set()
            notes=[]
            for i,r in enumerate(records):
                if r["review"]:
                    continue
                try: number=int(r["passage_id"].rsplit("P",1)[1])
                except (IndexError,ValueError):continue
                usd=r["low_usd"] if r["low_usd"]==r["high_usd"] else None
                if usd is not None and r.get("signed_usd") is not None:
                    usd=r["signed_usd"]
                for category, dest in [("targets",matches),("decoys",errors)]:
                    for n,f in enumerate(case[category]):
                        if number in f["passages"] and usd==f["usd"]:
                            dest.add(n)
                            inside.add(i)
                            notes.append(dict(index=i,category=category,reference_index=n,usd=usd,passage=r["passage_id"]))
            other=[dict(index=i,anchor=r["passage_id"],amount_usd=[r["low_usd"],r["high_usd"]],measure=r["measure"],entity=r.get("affected_entity",r.get("issuer")),review=r["review"])
                   for i,r in enumerate(records) if i not in inside]
            per_case[doc]=dict(targets=len(case["targets"]),matched_numeric=len(matches),
                               tested_decoys=len(case["decoys"]),decoys_falsely_attributed=len(errors),
                               automatic_table_rows=sum(bool(r.get("table_observations")) and not r["review"] for r in records),
                               verified_at_anchor=notes,other_outputs=other)
        results[version]=dict(cases=per_case, numeric_matches=sum(r["matched_numeric"] for r in per_case.values()),
                              targets=sum(r["targets"] for r in per_case.values()), incorrect_decoys=sum(r["decoys_falsely_attributed"] for r in per_case.values()),
                              tested_decoys=sum(r["tested_decoys"] for r in per_case.values()))
    options.output.write_bytes((json.dumps(results,indent=2,ensure_ascii=False)+"\n").encode())
    print({v:{k:n for k,n in p.items() if k!="cases"} for v,p in results.items()})
if __name__=="__main__":
    main()

