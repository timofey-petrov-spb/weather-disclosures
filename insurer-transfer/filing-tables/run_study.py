"""Rebuild the v7/v8 filing-table comparison from complete original HTML."""
import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
sys.path.insert(0, str(STUDY))
from replay import digest, fetch_primary, make_rows


def output_digest(records):
    text = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return digest(text.encode("utf-8"))


def check_method():
    lock = json.loads((STUDY / "v8/lock.json").read_text(encoding="utf-8-sig"))
    for name, expected in lock["implementation"].items():
        if digest((STUDY / name).read_bytes()) != expected:
            raise ValueError(f"Method differs from its freeze: {name}")


def acquire(filing, cache):
    path = cache / (filing["doc_id"] + ".htm")
    if path.exists():
        body = path.read_bytes()
    elif filing.get("source_sgml_url"):
        body = fetch_primary(filing)
    else:
        req = Request(filing["download_url"], headers={"User-Agent": "Hurricane Disclosures research / github.com/timofey-petrov-spb/weather-disclosures"})
        with urlopen(req, timeout=60) as response:
            body = response.read()
        if body.startswith(b"\x1f\x8b"):
            body = gzip.decompress(body)
    if len(body) != filing["primary_bytes"] or digest(body) != filing["primary_sha256"]:
        raise ValueError(f"Different primary document: {filing['doc_id']}")
    if not path.exists():
        path.write_bytes(body)
    return body


def run_case(filing, cache, output):
    doc = filing["doc_id"]
    if not doc.isascii() or not doc.isalnum():
        raise ValueError("Unexpected document ID")
    folder = output / doc
    folder.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    body = acquire(filing, cache)
    inputs = folder / "inputs.jsonl"
    with inputs.open("w", encoding="utf-8", newline="\n") as out:
        for row in make_rows(dict(filing, paragraphs=filing["rows"]), body):
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
    if digest(inputs.read_bytes()) != filing["inputs_sha256"]:
        raise ValueError(f"Different source passages: {doc}")
    fingerprints = {}
    for version in ("v7", "v8"):
        target = folder / (version + ".json")
        subprocess.run([sys.executable, "-B", str(STUDY / version / "extract.py"),
                        str(inputs), str(cache), str(target)], check=True)
        data = json.loads(target.read_text(encoding="utf-8-sig"))
        fingerprints[version] = output_digest(data)
    return fingerprints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("filing-table-replay"))
    parser.add_argument("--primary-files", type=Path, help="Directory of primary HTML files named by document ID. Missing documents are fetched.")
    parser.add_argument("--filing", help="Run one document ID")
    args = parser.parse_args()
    check_method()
    roster = json.loads((HERE / "filings.json").read_text(encoding="utf-8"))
    cases = [f for f in roster if not args.filing or args.filing == f["doc_id"]]
    if not cases:
        parser.error("Unknown document ID")
    for f in cases:
        got = run_case(f, args.primary_files or args.output / "primary", args.output)
        if got != f["output_digests"]:
            raise ValueError(f"Output mismatch for {f['doc_id']}")
        print(f"{f['doc_id']}: source and both frozen outputs verified")


if __name__ == "__main__":
    main()
