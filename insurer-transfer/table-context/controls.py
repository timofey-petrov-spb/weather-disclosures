"""Apply six reproducible source edits to disposable copies of development filings."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from replay_study import HERE, STUDY, filing_replay, verify_method


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Expected one occurrence of "+repr(old))
    return text.replace(old, new)


def modify(body, case):
    ordinal = case["table"]
    opening = list(re.finditer(br"<table\b", body, re.I))[ordinal-1].start()
    closing = body.lower().index(b"</table>", opening) + len(b"</table>")
    before, table, after = body[:opening], body[opening:closing], body[closing:]
    key = case["id"]
    if key in ("equivalent_unit", "flat_dollars"):
        scale = b"(USD millions)" if key == "equivalent_unit" else b"(US dollars)"
        table = once(table, b"($000&#146;s)", scale)
        if key == "equivalent_unit":
            def in_millions(match):
                integer = int(match[1].replace(b",", b""))
                return b">"+f"{Decimal(integer)/1000:.3f}".encode()+b"<"
            table, count = re.subn(br">([\d]{1,3}(?:,[\d]{3})+)<", in_millions, table)
            if count != 8:
                raise ValueError(f"Currency cells found: {count}")
    elif key == "governing_measure":
        split = before.rindex(b"Impact of property catastrophe losses:")
        before = before[:split] + once(before[split:], b"of net incurred losses:", b"of gross incurred losses:")
        table = once(table, b">44.6<", b">51.7<")
    elif key == "multiple_storms":
        table = once(table, b"Hurricane Katrina", b"Hurricanes Katrina and Rita combined")
    elif key == "four_digit_dates":
        for date in (b"8/25/", b"8/29/"):
            table = once(table, date+b"05", date+b"2005")
    elif key == "other_column":
        for label, old, new in [(b"Personal Lines Segment",b">3.5<",b">3.0<"),
                                 (b"Commercial Lines Segment",b">&#151;<",b">0.5<")]:
            row = next(r[0] for r in re.finditer(br"<tr\b.*?</tr\s*>",table,re.I|re.S) if label in r[0])
            if old not in row:
                raise ValueError("Source cell missing")
            changed = row.replace(old,new,1)
            totals = (b">9.0<", b">8.5<") if label.startswith(b"Personal") else (b">15.7<", b">16.2<")
            table = once(table,row,once(changed,*totals))
    else:
        raise ValueError(key)
    return before + table + after


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--primary-files",type=Path,required=True)
    cli.add_argument("--output",type=Path,required=True)
    args=cli.parse_args()
    verify_method()
    source=STUDY/"event-accounting"
    roster={f["doc_id"]:f for f in json.loads((source/"filings.json").read_text(encoding="utf-8"))}
    reference=json.loads((source/"independent-reference.json").read_text(encoding="utf-8"))["claims"]
    plans=json.loads((HERE/"control-cases.json").read_text(encoding="utf-8"))
    results=[]
    for case in plans:
        doc=case["doc"]
        meta=roster[doc]
        raw=filing_replay.acquire(meta,args.primary_files)
        simulated=modify(raw,case)
        new=dict(meta,primary_sha256=filing_replay.digest(simulated),paragraphs=meta["rows"])
        with TemporaryDirectory() as directory:
            cache=Path(directory)
            (cache/(doc+".htm")).write_bytes(simulated)
            inputs=cache/"inputs.jsonl"
            with inputs.open("w",encoding="utf-8",newline="\n") as stream:
                for record in filing_replay.make_rows(new,simulated):
                    stream.write(json.dumps(record,ensure_ascii=False)+"\n")
            out=cache/"predictions.json"
            subprocess.run([sys.executable,"-B",str(STUDY/"v10/extract.py"),str(inputs),str(cache),str(out)],check=True)
            records=json.loads(out.read_text(encoding="utf-8-sig"))
        gold=sorted([r for r in reference if r["doc_id"]==doc], key=lambda r:(r["row"],r["column"]))
        expected=[(r["row"],r["column"],v,b) for r,v,b in zip(gold,case["amounts"],case["basis"])]
        observed=[]
        for record in records:
            if record["review"]:
                continue
            cells=[o["amount_cell"] for o in record.get("table_observations",[]) if o["amount_cell"]["table"]==case["table"]]
            if cells:
                cell=cells[0]
                observed.append((cell["row"],cell["column"],record.get("signed_usd"),record.get("basis")))
            elif any(record["passage_id"] in g["evidence"] and record["source_channel"]=="html_table" for g in gold):
                observed.append((-1,-1,record.get("signed_usd"),record.get("basis")))
        results.append(dict(id=case["id"],expected=expected,observed=sorted(observed),matched=expected==sorted(observed)))
    args.output.write_bytes((json.dumps(results,indent=2)+"\n").encode())
    print(sum(r["matched"] for r in results),"of",len(results),"controls matched.")


if __name__=="__main__":
    main()

