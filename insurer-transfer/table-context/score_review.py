"""Measure source-table retrieval separately from extraction of financial amounts."""
import argparse
import json
from pathlib import Path

from replay_study import HERE, STUDY, filing_replay
from review_tables import rank


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("replay",type=Path)
    cli.add_argument("--primary-files",type=Path,required=True)
    cli.add_argument("--output",type=Path,required=True)
    args=cli.parse_args()
    dev=read(STUDY/"event-accounting/independent-reference.json")["claims"]
    test=read(HERE/"independent-reference.json")["claims"]
    tables={r["doc_id"]:r["table"] for r in dev+test}
    results=[]
    for f in read(HERE/"filings.json"):
        doc=f["doc_id"]
        text=(args.replay/doc/"inputs.jsonl").read_text(encoding="utf-8")
        rows=[json.loads(line) for line in text.splitlines()]
        suggestions=rank(filing_replay.acquire(f,args.primary_files),rows,f["event"])
        target=tables[doc]
        position=next((i for i,r in enumerate(suggestions,1) if r["table"]==target),None)
        results.append(dict(doc_id=doc,role=f["role"],url=f["source_url"],reference_table=target,
                            rank=position,candidate_count=len(suggestions),suggestions=suggestions))
    args.output.write_bytes((json.dumps(results,indent=2,ensure_ascii=False)+"\n").encode())
    for role in ("development","holdout"):
        group=[r for r in results if r["role"]==role]
        print(role,sum(r["rank"] is not None for r in group),"of",len(group))


if __name__=="__main__":
    main()

