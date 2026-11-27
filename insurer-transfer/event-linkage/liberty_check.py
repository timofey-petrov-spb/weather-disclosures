"""Reproduce the separate check of two signed values in a transcribed PDF table."""
import argparse
import json
from pathlib import Path
import tempfile

from replay_study import HERE, run_filing, filing_replay, verify_method


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    verify_method()
    ref=json.loads((HERE/"liberty-reference.json").read_bytes())
    src=ref["source"]
    html="""<html><body><p>Liberty Mutual Holding Company Inc.</p>
<p>Consolidated operations through September 30, 2005. Dollar amounts in millions.</p>
<table><tr><th>$ in Millions</th><th>Three Months Ended September 30, 2005</th><th>Nine Months Ended September 30, 2005</th></tr>
<tr><td>Catastrophes</td><td></td><td></td></tr>
<tr><td>Hurricane Katrina</td><td>(818)</td><td>(809)</td></tr>
</table></body></html>""".encode()
    from replay import VisibleText
    reader=VisibleText()
    reader.feed(html.decode());reader.close();reader.flush()
    f=dict(doc_id="LMQ05",issuer="Liberty Mutual Holding Company Inc.",source_url=src,event="Katrina",
           form="Earnings release",accession=None,accepted_at_utc=None,rows=len(reader.rows),primary_bytes=len(html),
           primary_sha256=filing_replay.digest(html))
    data="".join(json.dumps(x,ensure_ascii=False)+"\n" for x in filing_replay.make_rows(dict(f,paragraphs=f["rows"]),html)).encode()
    f["inputs_sha256"]=filing_replay.digest(data)
    with tempfile.TemporaryDirectory() as d:
        stage=Path(d)
        (stage/"LMQ05.htm").write_bytes(html)
        hashes=run_filing(f,stage,stage/"replay")
        results={}
        for version in ("v10","v11"):
            predictions=json.loads((stage/"replay"/"LMQ05"/(version+".json")).read_bytes())
            matched=[]
            for gold in ref["gold"]:
                for r in predictions:
                    fields=any(all(o["amount_cell"][k]==gold[k] for k in ("table","row","column")) for o in r.get("table_observations",[]))
                    if fields and r.get("signed_usd")==gold["signed_usd"] and not r["review"]:
                        matched.append(gold["column"]);break
            results[version]=dict(matched_signed_cells=len(matched),total=len(ref["gold"]),actual=predictions,hash=hashes[version])
        args.output.write_bytes((json.dumps(results,indent=2,ensure_ascii=False)+"\n").encode())
        print([(v,r["matched_signed_cells"],r["total"]) for v,r in results.items()])


if __name__=="__main__":
    main()

