"""Reproduce the insurance extraction comparison on original SEC primary documents.

Use Python 3.10 or newer. The embedded roster fixes the original submissions.
All timestamps are UTC. Cached primary files must be named AQ.htm, AK.htm,
CQ.htm, CK.htm, BQ.htm and BK.htm. Run python replay.py --help for the available options.
"""
import argparse
import gzip
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from v4.source_reader import VisibleText

HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fetch_primary(filing):
    request = Request(filing["source_sgml_url"], headers={
        "User-Agent": "Disclosure research / github.com/timofey-petrov-spb/weather-disclosures"
    })
    for attempt in range(3):
        try:
            with urlopen(request, timeout=90) as response:
                full = response.read(filing["source_sgml_bytes"] + 1)
            if full.startswith(b"\x1f\x8b"):
                full = gzip.decompress(full)
            break
        except (TimeoutError, URLError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    if digest(full) != filing["source_sgml_sha256"]:
        raise ValueError(f"Archive digest mismatch for {filing['accession']}")
    blocks = re.findall(br"(?ms)^<DOCUMENT>\s*$(.*?)^</DOCUMENT>", full)
    name = re.escape(filing["primary_name"].encode())
    primary = [block for block in blocks if re.search(
        br"(?m)^<FILENAME>"+name+br"\s*$", block.partition(b"<TEXT>")[0])]
    if len(primary) != 1:
        raise ValueError("Missing or ambiguous primary document")
    return re.search(br"(?ms)^<TEXT>\r?\n(.*?)^</TEXT>", primary[0])[1]


def make_rows(filing, body):
    if digest(body) != filing["primary_sha256"]:
        raise ValueError(f"Primary HTML digest mismatch for {filing['doc_id']}")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("windows-1252")
    parser = VisibleText()
    parser.feed(text)
    parser.close()
    parser.flush()
    if len(parser.rows) != filing["paragraphs"]:
        raise ValueError(f"Passage count mismatch for {filing['doc_id']}")
    for number, (kind, page, text) in enumerate(parser.rows, 1):
        key = filing["doc_id"]
        url = filing["source_url"]
        yield dict(doc_id=key, passage_id=f"{key}-P{number:05d}", text=text, kind=kind,
                   event=filing["event"], issuer=filing["issuer"], source_url=url, url=url,
                   canonical_url=url, source_sha256=filing["primary_sha256"],
                   accepted_at_utc=filing["accepted_at_utc"], accession=filing["accession"],
                   source_kind=filing["form"], document_type=filing["form"],
                   page=page, replay_eligible=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-files", type=Path, help="Optional directory of verified primary HTML documents")
    parser.add_argument("--output", type=Path, default=Path("replay-output"))
    args = parser.parse_args()
    roster = json.loads((HERE / "filings.json").read_text(encoding="utf-8"))
    for cohort in roster:
        folder = args.output / cohort["id"]
        primary_dir = folder / "primary"
        primary_dir.mkdir(parents=True, exist_ok=True)
        source_rows = []
        for filing in cohort["filings"]:
            filename = filing["doc_id"]+".htm"
            location = (args.primary_files or primary_dir) / filename
            if args.primary_files or location.exists():
                body = location.read_bytes()
            else:
                body = fetch_primary(filing)
            source_rows.extend(make_rows(filing, body))
            (primary_dir / filename).write_bytes(body)
        inputs = folder / "inputs.jsonl"
        inputs.write_bytes("".join(json.dumps(row, ensure_ascii=False)+"\n" for row in source_rows).encode())
        for version, script in (("v3", HERE/"extractor_v3.py"), ("v4", HERE/"v4"/"extract.py"),
                                ("v5", HERE/"v5"/"extract.py")):
            output = folder / (version + "_outputs.json")
            command = [sys.executable, "-B", str(script), str(inputs)]
            if version != "v3":
                command.append(str(primary_dir))
            subprocess.run([*command, str(output)], check=True)
            current = json.loads(output.read_text(encoding="utf-8-sig"))
            fingerprint = digest(json.dumps(current, sort_keys=True, ensure_ascii=False, separators=(",",":")).encode())
            expected = cohort["output_digests"][version]
            if fingerprint != expected:
                raise ValueError(f"Output differs from the scored run: {cohort['id']} {version}")
        print(f"{cohort['id']}: {len(source_rows):,} passages; all three outputs match their fingerprints")


if __name__ == "__main__":
    main()

