"""Reproduce the supplementary Hurricane Ian screen on complete SEC primary filings.

The default roster is supplemental-filings.json next to this script. Each
entry is a source inventory plus output_digests with keys v6 and v7.
Python 3.10+ and its standard library suffice.
"""
import argparse
import gzip
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
sys.path.insert(0, str(STUDY))
from replay import digest, make_rows
from run_study import checksum


def download(filing):
    request = Request(filing["download_url"], headers={
        "User-Agent": "Disclosure research / github.com/timofey-petrov-spb/weather-disclosures"
    })
    for attempt in range(3):
        try:
            with urlopen(request, timeout=90) as response:
                body = response.read()
            return gzip.decompress(body) if body.startswith(b"\x1f\x8b") else body
        except (TimeoutError, URLError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def run_filing(filing, output, primary_files):
    doc = filing["doc_id"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", doc):
        raise ValueError(f"Invalid document ID {doc!r}")
    folder = output / doc
    folder.mkdir(parents=True, exist_ok=True)
    filename = doc + ".htm"
    cache = (primary_files or folder / "primary") / filename
    body = cache.read_bytes() if primary_files or cache.exists() else download(filing)
    if len(body) != filing["primary_bytes"] or digest(body) != filing["primary_sha256"]:
        raise ValueError(f"Primary HTML length or digest mismatch for {doc}")
    with TemporaryDirectory(dir=folder) as temp:
        stage = Path(temp)
        primary = stage / "primary"
        primary.mkdir()
        (primary / filename).write_bytes(body)
        rows = make_rows(dict(filing, event="Ian", paragraphs=filing["rows"]), body)
        inputs = stage / "inputs.jsonl"
        with inputs.open("w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        if digest(inputs.read_bytes()) != filing["inputs_sha256"]:
            raise ValueError(f"Reconstructed input digest mismatch for {doc}")
        files = [Path("primary") / filename, Path("inputs.jsonl")]
        for ver in ("v6", "v7"):
            name = Path(ver + "_outputs.json")
            subprocess.run([sys.executable, "-B", str(STUDY / ver / "extract.py"),
                            str(inputs), str(primary), str(stage / name)], check=True)
            records = json.loads((stage / name).read_text(encoding="utf-8-sig"))
            if checksum(records) != filing["output_digests"][ver]:
                raise ValueError(f"Output digest mismatch for {doc} {ver}")
            files.append(name)
        (folder / "primary").mkdir(exist_ok=True)
        for name in files:
            (stage / name).replace(folder / name)
    print(f"{doc}: verified {filing['rows']:,} input passages and both frozen outputs")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roster", type=Path, default=HERE / "supplemental-filings.json",
                        help="Array of pinned filing inventories and expected output digests")
    parser.add_argument("--output", type=Path, default=Path("supplement-replay"),
                        help="Destination directory, with a subdirectory for each document ID")
    parser.add_argument("--primary-files", type=Path,
                        help="Read verified primary HTML from DIRECTORY/DOC_ID.htm, offline")
    parser.add_argument("--filing", help="Replay a single document ID from the roster")
    args = parser.parse_args()
    roster = json.loads(args.roster.read_text(encoding="utf-8-sig"))
    ids = [f["doc_id"] for f in roster]
    if len(set(ids)) != len(ids):
        parser.error("Duplicate document ID in roster")
    if args.filing and args.filing not in ids:
        parser.error("Unknown document ID: " + args.filing)
    for filing in roster:
        if not args.filing or args.filing == filing["doc_id"]:
            run_filing(filing, args.output, args.primary_files)


if __name__ == "__main__":
    main()
