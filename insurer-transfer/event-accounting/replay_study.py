"""Rebuild and verify the v8 and v9 outputs on complete source filings."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
spec = importlib.util.spec_from_file_location("filing_replay", STUDY / "filing-tables/run_study.py")
filing_replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(filing_replay)


def verify_method():
    lock = json.loads((STUDY / "v9/lock.json").read_text(encoding="utf-8-sig"))
    for filename, expected in lock["implementation"].items():
        if filing_replay.digest((STUDY / filename).read_bytes()) != expected:
            raise ValueError(f"Source differs from the frozen method: {filename}")


def run_filing(filing, cache, output):
    doc_id = filing["doc_id"]
    if not doc_id.isascii() or not doc_id.replace("-", "").replace("_","").isalnum():
        raise ValueError("Invalid document ID")
    cache.mkdir(parents=True, exist_ok=True)
    folder = output / doc_id
    folder.mkdir(parents=True, exist_ok=True)
    body = filing_replay.acquire(filing, cache)
    rows = filing_replay.make_rows(dict(filing, paragraphs=filing["rows"]), body)
    source = folder / "inputs.jsonl"
    with source.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    if filing_replay.digest(source.read_bytes()) != filing["inputs_sha256"]:
        raise ValueError(f"Source passages differ: {doc_id}")
    result = {}
    for version in ("v8", "v9"):
        target = folder / (version + ".json")
        subprocess.run([sys.executable, "-B", str(STUDY / version / "extract.py"), str(source), str(cache), str(target)], check=True)
        records = json.loads(target.read_text(encoding="utf-8-sig"))
        result[version] = filing_replay.output_digest(records)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("event-accounting-replay"))
    parser.add_argument("--primary-files", type=Path, help="Read existing HTML from this directory, fetching a missing filing when needed")
    parser.add_argument("--filing", help="Run only the named document ID")
    args = parser.parse_args()
    verify_method()
    roster = json.loads((HERE / "filings.json").read_text(encoding="utf-8"))
    cases = [f for f in roster if not args.filing or f["doc_id"] == args.filing]
    if not cases:
        parser.error("Unknown document ID")
    for filing in cases:
        hashes = run_filing(filing, args.primary_files or args.output / "primary", args.output)
        if hashes != filing["output_digests"]:
            raise ValueError("Unexpected output for " + filing["doc_id"])
        print(filing["doc_id"], "verified")


if __name__ == "__main__":
    main()
