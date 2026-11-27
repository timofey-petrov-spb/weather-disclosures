"""Replay controlled edits on throwaway copies of three development filings."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from replay_study import HERE, STUDY, filing_replay, verify_method


def once(body, before, after):
    if body.count(before) != 1:
        raise ValueError("Expected a unique source edit")
    return body.replace(before, after)


def edit(primary, name):
    if name == "caption_scale":
        start = primary.index(b"The large catastrophic losses, acquisition costs,")
        end = primary.lower().index(b"<table", start)
        caption = primary[start:end]
        changed = once(caption, b"in millions of U.S. dollars", b"in thousands of U.S. dollars")
        return primary[:start] + changed + primary[end:]
    needles = {"premium_revision": (b"Hurricane Katrina (1)", b"(563"),
               "premium_sign": (b"(74.6", b"(34.7"),
               "different_year": (b"$427.5",), "other_event": (b"$427.5",)}
    rows = re.findall(br"<tr\b[^>]*>.*?</tr\s*>", primary, re.I | re.S)
    row, = [r for r in rows if all(n in r for n in needles[name])]
    if name == "premium_revision":
        changed = once(once(row, b">54<", b">71<"), b">(511<", b">(494<")
    elif name == "premium_sign":
        changed = row
        for before, after in [(b"74.6", b"74.6"), (b"34.7", b"114.5")]:
            pattern = br">\(" + re.escape(before) + br"(<.*?<td\s+align=left>\s*<font[^>]*>)\)"
            changed, n = re.subn(pattern, lambda m: b">" + after + m[1], changed, flags=re.I | re.S)
            if n != 1:
                raise ValueError("Unexpected split sign layout")
    elif name == "different_year":
        changed = once(row, b"$15.3", b"$81.2")
    else:
        changed = once(row, b"Katrina", b"Felicia")
    return once(primary, row, changed)


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--primary-files", type=Path, required=True)
    args.add_argument("--output", type=Path, required=True)
    options = args.parse_args()
    verify_method()
    roster = json.loads((STUDY / "filing-tables/filings.json").read_text(encoding="utf-8"))
    by_id = {f["doc_id"]:f for f in roster}
    reference = json.loads((STUDY / "filing-tables/reference.json").read_text(encoding="utf-8"))["claims"]
    cases = json.loads((HERE / "control-cases.json").read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory() as folder:
        temp = Path(folder)
        for case in cases:
            doc = case["doc"]
            filing = by_id[doc]
            original = (options.primary_files / (doc + ".htm")).read_bytes()
            if filing_replay.digest(original) != filing["primary_sha256"]:
                raise ValueError("Different original: " + doc)
            changed = edit(original, case["id"])
            simulated = dict(filing, primary_sha256=hashlib.sha256(changed).hexdigest(), paragraphs=filing["rows"])
            (temp / (doc + ".htm")).write_bytes(changed)
            inputs = temp / "inputs.jsonl"
            with inputs.open("w", encoding="utf-8", newline="\n") as stream:
                for rec in filing_replay.make_rows(simulated, changed):
                    stream.write(json.dumps(rec, ensure_ascii=False) + "\n")
            output = temp / "v9.json"
            subprocess.run([sys.executable,"-B",str(STUDY / "v9/extract.py"),str(inputs),str(temp),str(output)],check=True)
            observed = []
            original_facts = sorted((r for r in reference if (r["doc_id"],r["table"],r["row"]) ==
                                    (doc,case["table"],case["row"])),key=lambda r:r["visible_column"])
            source_rows = {r["passage_id"] for r in original_facts}
            expected = [(g["visible_column"],amount,g["measure"].casefold()) for g,amount in zip(original_facts,case["expected_signed_usd"])]
            for rec in json.loads(output.read_text(encoding="utf-8-sig")):
                if rec["review"]:
                    continue
                cells = [o["amount_cell"] for o in rec.get("table_observations", [])]
                hits = [c for c in cells if c["table"] == case["table"] and c["row"] == case["row"]]
                if hits or rec["passage_id"] in source_rows:
                    observed.append({"column":hits[0]["column"] if hits else -1, "usd":rec.get("signed_usd"),
                                     "measure":rec["measure"], "owner":rec["issuer"]})
            actual = [(r["column"],r["usd"],r["measure"].casefold()) for r in sorted(observed,key=lambda r:r["column"])]
            results.append(dict(id=case["id"],expected=case["expected_signed_usd"],observed=observed,
                                matched_source_fields=actual==expected))
    options.output.write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n",encoding="utf-8")
    print(sum(r["matched_source_fields"] for r in results), "of", len(results), "matched")


if __name__ == "__main__":
    main()
