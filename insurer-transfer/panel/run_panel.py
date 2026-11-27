"""Rebuild the four held-out issuer tests and the two development checks on Chubb.

Run this script from a checkout of weather-disclosures. By default the script
downloads the full archived submissions pinned in filings.json. Use
--primary-files DIRECTORY to use copies of the primary HTML named by document ID.
Python 3.10+; no external packages.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
sys.path.insert(0, str(STUDY))
from replay import digest, fetch_primary, make_rows


def checksum(records):
    return digest(json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(",",":")).encode())


def run_case(case, cache, output, expected):
    folder = output / case["id"]
    primary = folder / "primary"
    primary.mkdir(parents=True, exist_ok=True)
    inputs = folder / "inputs.jsonl"
    with inputs.open("w", encoding="utf-8", newline="\n") as out:
        for f in case["filings"]:
            filename = f["doc_id"] + ".htm"
            cache_file = cache / filename
            if not cache_file.exists():
                cache_file.write_bytes(fetch_primary(f))
            body = cache_file.read_bytes()
            dest = primary / filename
            if dest != cache_file:
                dest.write_bytes(body)
            for row in make_rows(dict(f, event=case["event"]), body):
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
    for ver in ("v5", "v6"):
        result = folder / (ver + "_outputs.json")
        subprocess.run([sys.executable, "-B", str(STUDY/ver/"extract.py"),
                        str(inputs), str(primary), str(result)], check=True)
        records = json.loads(result.read_text(encoding="utf-8-sig"))
        if checksum(records) != expected[case["id"]][ver]:
            raise ValueError(f"Unexpected output for {case['id']} {ver}")
        auto = sum(not r["review"] for r in records)
        print(f"{case['id']} / {ver}: {auto} automatic records, {len(records)-auto} for review; verified")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", type=Path, default=Path("panel-replay"))
    cli.add_argument("--primary-files", type=Path, help="Optional directory of verified primary HTML")
    cli.add_argument("--case", help="Replay only one case ID from filings.json")
    args = cli.parse_args()
    roster = json.loads((HERE/"filings.json").read_text(encoding="utf-8"))
    expected = json.loads((HERE/"output-digests.json").read_text(encoding="utf-8"))
    groups = [case for case in roster if not args.case or case["id"] == args.case]
    if not groups:
        cli.error("Unknown case: "+args.case)
    cache = args.primary_files or args.output / "source-cache"
    cache.mkdir(parents=True, exist_ok=True)
    for case in groups:
        run_case(case, cache, args.output, expected)


if __name__ == "__main__":
    main()

