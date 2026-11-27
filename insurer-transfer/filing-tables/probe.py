"""Run the registered development controls on disposable copies of two filings."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
sys.path.insert(0, str(STUDY))
from replay import make_rows


def replace_once(body, before, after):
    before, after = before.encode(), after.encode()
    if body.count(before) != 1:
        raise ValueError("Expected exactly one occurrence: " + before.decode())
    return body.replace(before, after)


def edit(body, case):
    if case == "regional_event":
        return replace_once(body, "South (Ian)", "South (Eloise)")
    if case == "commercial_and_total":
        rows = [r for r in re.findall(br"<tr\b[^>]*>.*?</tr>", body, re.I | re.S) if b"South (Ian)" in r]
        if len(rows) != 1 or rows[0].count(b">26<") != 2 or rows[0].count(b">220<") != 2:
            raise ValueError("Cincinnati source row changed")
        return body.replace(rows[0], rows[0].replace(b">26<", b">39<").replace(b">220<", b">233<"))
    note = "Catastrophe losses were related to losses from Hurricane Ian which primarily impacted our Commercial All Risk line of business."
    if case == "other_storm":
        return replace_once(body, note, note.replace("Hurricane Ian", "Hurricane Eloise"))
    if case == "mixed_storms":
        return replace_once(body, note, note.replace("Hurricane Ian", "Hurricanes Ian and Fiona"))
    if case == "partly_attributed":
        return replace_once(body, note, "Only part of these catastrophe losses arose from Hurricane Ian. The company has not quantified its share.")
    if case == "wrong_year":
        lead = "Our catastrophe loss ratio was 16.0% during the three months ended September 30, 2022."
        return replace_once(body, lead, lead.replace("2022", "2020"))
    raise ValueError(case)


def locates(record, target):
    if record.get("passage_id") == target:
        return True
    return any(o.get("amount_cell", {}).get("passage_id") == target for o in record.get("table_observations", []))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--primary-files", type=Path, required=True, help="Directory containing archived CIQ.htm and PLQ.htm")
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    cases = json.loads((HERE / "probe-cases.json").read_text(encoding="utf-8"))["cases"]
    roster = json.loads((STUDY / "table-study/supplemental-filings.json").read_text(encoding="utf-8"))
    sources = {f["doc_id"]: f for f in roster}
    results = []
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        for case in cases:
            doc = case["doc"]
            filing = copy.copy(sources[doc])
            raw = (args.primary_files / (doc + ".htm")).read_bytes()
            if hashlib.sha256(raw).hexdigest() != filing["primary_sha256"]:
                raise ValueError("Original HTML mismatch: " + doc)
            body = edit(raw, case["id"])
            filing.update(primary_sha256=hashlib.sha256(body).hexdigest(), event="Ian", paragraphs=filing["rows"])
            (work / (doc + ".htm")).write_bytes(body)
            with (work / "inputs.jsonl").open("w", encoding="utf-8", newline="\n") as out:
                for row in make_rows(filing, body):
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
            target = work / "output.json"
            subprocess.run([sys.executable, "-B", str(STUDY / "v8/extract.py"), str(work / "inputs.jsonl"), str(work), str(target)], check=True)
            records = json.loads(target.read_text(encoding="utf-8-sig"))
            matched = [r for r in records if not r.get("review") and locates(r, case["row"])]
            actual = [r.get("signed_usd") for r in matched]
            results.append(dict(case=case["id"], expected=case["expected_signed_usd"], actual=actual,
                                passed=sorted(actual, key=str) == sorted(case["expected_signed_usd"], key=str)))
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(sum(r["passed"] for r in results), "of", len(results), "controls met the registered expectation")


if __name__ == "__main__":
    main()
