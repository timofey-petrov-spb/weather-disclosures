"""Build an offline passage index. Pass --fetch once to get missing source bytes."""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "cache"
MAX_BYTES = 40_000_000
AGENT = "WeatherDisclosureStudy/0.1 (public research contact: https://github.com/timofey-petrov-spb)"


def write_atomic(path, contents):
    with NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            tmp.write(contents)
        except BaseException:
            tmp.close()
            tmp_path.unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def json_bytes(data):
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


class VisibleText(HTMLParser):
    """Preserve inline text, join table cells as rows and keep NHC's bulletin body."""

    void = set("area base br col embed hr img input link meta param source track wbr".split())
    skip = set("head script style nav footer noscript template ix:header ix:hidden ix:resources".split())
    blocks = set("address article blockquote div h1 h2 h3 h4 h5 h6 li p section table ul".split())

    def __init__(self, bulletin=False):
        super().__init__(convert_charrefs=True)
        self.bulletin = bulletin
        self.stack = []
        self.fragments = []
        self.rows = []

    def hidden(self):
        return bool(self.stack and self.stack[-1][1])

    def inside(self, name):
        return any(tag == name for tag, _ in self.stack)

    def flush(self, kind="paragraph"):
        raw = "".join(self.fragments)
        self.fragments.clear()
        if self.bulletin and kind != "bulletin":
            return
        paragraphs = re.split(r"\n\s*\n", raw) if kind == "bulletin" else [raw]
        for para in paragraphs:
            text = " ".join(para.split()).strip(" |")
            if text:
                self.rows.append((kind, None, text))

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        style = re.sub(r"\s+", "", (attributes.get("style") or "").lower())
        hidden = (self.hidden() or tag in self.skip or "hidden" in attributes
                  or attributes.get("aria-hidden") == "true" or "display:none" in style
                  or "visibility:hidden" in style or attributes.get("role") == "navigation")
        if not hidden:
            if tag == "tr" or (tag in self.blocks and not self.inside("tr")) or tag == "pre":
                self.flush()
            elif tag in {"td", "th"} and self.inside("tr"):
                self.fragments.append(" | ")
            elif tag == "br":
                self.fragments.append(" ")
        if tag not in self.void:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                break
        else:
            return
        if not self.hidden():
            if tag == "pre":
                self.flush("bulletin" if self.bulletin else "paragraph")
            elif tag == "tr":
                self.flush("table_row")
            elif tag in self.blocks and not self.inside("tr"):
                self.flush()
        del self.stack[i:]

    def handle_data(self, data):
        if not self.hidden() and (not self.bulletin or self.inside("pre")):
            self.fragments.append(data)


def pdf_rows(raw, edition):
    from pypdf import PdfReader

    pdf = PdfReader(io.BytesIO(raw))
    if edition.get("pdf_title") and pdf.metadata.title != edition["pdf_title"]:
        raise ValueError("The PDF metadata no longer matches the expected accession.")
    start, end = edition.get("pages", [1, len(pdf.pages)])
    if not 1 <= start <= end <= len(pdf.pages):
        raise ValueError("The selected filing pages exceed the PDF.")
    for page_no in range(start, end + 1):
        layout = pdf.pages[page_no - 1].extract_text(extraction_mode="layout") or ""
        # A blank line separates visual blocks. Long inter-column gaps retain a
        # table's cell order. Never merge paragraphs or table rows across pages.
        for block in re.split(r"\n[ \t]*\n", layout):
            paragraph = []
            previous_indent = None
            for line in block.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                indent = len(line) - len(line.lstrip())
                # SEC PDFs often indent the first line of a new paragraph without
                # inserting a blank line. A wrapped sentence stays with its start.
                if paragraph and previous_indent is not None and indent >= previous_indent + 3:
                    if paragraph[-1].endswith((".", ":", ")", "”")) or len(paragraph[-1]) < 60:
                        yield "paragraph", page_no, " ".join(paragraph)
                        paragraph.clear()
                previous_indent = indent
                column_gap = re.search(r"\S {4,}\S", stripped)
                if column_gap and re.search(r"\d", stripped):
                    if paragraph:
                        yield "paragraph", page_no, " ".join(paragraph)
                        paragraph.clear()
                    yield "table_row", page_no, " | ".join(
                        " ".join(cell.split()) for cell in re.split(r" {4,}", stripped))
                else:
                    paragraph.append(" ".join(stripped.split()))
            if paragraph:
                yield "paragraph", page_no, " ".join(paragraph)


def extract(raw, source, edition):
    if edition["format"] == "pdf":
        if not raw.startswith(b"%PDF-"):
            raise ValueError("Response does not have a PDF signature.")
        rows = list(pdf_rows(raw, edition))
    else:
        html = raw.decode("utf-8-sig", errors="strict") if raw.startswith(b"\xef\xbb\xbf") else None
        if html is None:
            try:
                html = raw.decode("utf-8")
            except UnicodeDecodeError:
                html = raw.decode("windows-1252", errors="replace")
        parser = VisibleText(bulletin=source["doc_id"].startswith("NHC-"))
        parser.feed(html)
        parser.close()
        parser.flush()
        rows = parser.rows
        if "storm_id" in source and not any(source["storm_id"] in text for _, _, text in rows):
            raise ValueError("Archive response does not contain the expected storm ID.")
        if source["doc_id"].startswith("SEC-") and not any(
                source["issuer"].split()[0].lower() in text.lower() for _, _, text in rows):
            raise ValueError("Filing response does not identify the expected issuer.")
    if not rows:
        raise ValueError("No visible passages were extracted.")
    return rows


def editions(source):
    yield {"url": source["url"], "format": "html", "replay_eligible": True,
           "edition": "nhc_bulletin" if "storm_id" in source else "edgar_original"}
    if source.get("alternate"):
        yield source["alternate"]
    yield from source.get("additional_editions", [])


def acquire(source, denied, user_agent, recorded=None):
    """Stop requesting a host after a denial; alternate publishers are explicit."""
    notes = []
    for edition in editions(source):
        if recorded and edition["edition"] != recorded["edition"]:
            continue
        url = edition["url"]
        host = urlparse(url).hostname
        if host in denied:
            notes.append({"url": url, "outcome": "skipped_after_host_denial"})
            continue
        try:
            request = Request(url, headers={"User-Agent": user_agent})
            with urlopen(request, timeout=25) as response:
                raw = response.read(MAX_BYTES + 1)
                resolved = response.geturl()
            if len(raw) > MAX_BYTES:
                raise ValueError("source exceeds the 40 MB limit")
            if edition.get("expected_sha256") and sha(raw) != edition["expected_sha256"]:
                raise ValueError("Published bytes differ from the verified edition. Review before use.")
            if recorded and sha(raw) != recorded["sha256"]:
                raise ValueError("Downloaded bytes differ from the selected report's fingerprint.")
            rows = extract(raw, source, edition)
        except HTTPError as err:
            if err.code in {401, 403, 429}:
                denied.add(host)
            notes.append({"url": url, "outcome": f"HTTP {err.code}"})
            continue
        except (URLError, TimeoutError, ValueError, OSError) as err:
            notes.append({"url": url, "outcome": str(err)})
            continue
        digest = sha(raw)
        record = {"edition": edition["edition"], "url": url, "resolved_url": resolved,
                  "sha256": digest, "bytes": len(raw), "attempts": notes,
                  "fetched_at_utc": datetime.now(timezone.utc).isoformat()}
        rawfile = CACHE / f"{digest}.{edition['format']}"
        if rawfile.exists() and sha(rawfile.read_bytes()) != digest:
            raise ValueError(f"Cached content mismatch: {rawfile}")
        if not rawfile.exists():
            write_atomic(rawfile, raw)
        write_atomic(CACHE / (source["doc_id"] + ".json"), json_bytes(record))
        return record, edition, rows, notes
    return None, None, [], notes


def read_cache(source, receipt_path):
    record = json.loads(receipt_path.read_text(encoding="utf-8"))
    edition = next((e for e in editions(source) if e["url"] == record["url"]
                    and e["edition"] == record["edition"]), None)
    if not edition:
        raise ValueError(f"Cached edition differs from the manifest for {source['doc_id']}")
    if not re.fullmatch(r"[a-f0-9]{64}", record["sha256"]):
        raise ValueError(f"Invalid source digest for {source['doc_id']}")
    rawfile = CACHE / f"{record['sha256']}.{edition['format']}"
    raw = rawfile.read_bytes()
    if sha(raw) != record["sha256"] or len(raw) != record["bytes"]:
        raise ValueError(f"Cache integrity check failed for {source['doc_id']}")
    if edition.get("expected_sha256") and record["sha256"] != edition["expected_sha256"]:
        raise ValueError(f"Cached digest differs from the verified edition for {source['doc_id']}")
    return record, edition, extract(raw, source, edition), record.get("attempts", [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Fetch only sources absent from the cache.")
    parser.add_argument("--recorded-editions", type=Path, metavar="REPORT",
                        help="Use the editions and byte fingerprints printed in a development retrieval report.")
    args = parser.parse_args()
    CACHE.mkdir(exist_ok=True)
    sources = json.loads((DATA / "sources.json").read_text(encoding="utf-8"))
    recorded = {}
    if args.recorded_editions:
        report = json.loads(args.recorded_editions.read_text(encoding="utf-8-sig"))
        recorded = {r["doc_id"]: r for r in report["sources"]}
        if set(recorded) != {s["doc_id"] for s in sources}:
            parser.error("The report and source manifest describe different documents.")
    status_path = DATA / "collection_status.json"
    previous = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else []
    last_status = {s["doc_id"]: s for s in previous}
    denied, output, status = set(), [], []
    for s in sources:
        doc = s["doc_id"]
        receipt = CACHE / (doc + ".json")
        expected = recorded.get(doc)
        matching_cache = receipt.is_file()
        if matching_cache and expected:
            cached = json.loads(receipt.read_text(encoding="utf-8"))
            matching_cache = (cached["edition"] == expected.get("edition")
                              and cached["sha256"] == expected.get("sha256"))
        if expected and expected["status"] != "available":
            record, edition, rows, attempts = None, None, [], [{"outcome": "unavailable_in_selected_report"}]
        elif matching_cache:
            record, edition, rows, attempts = read_cache(s, receipt)
        elif args.fetch:
            record, edition, rows, attempts = acquire(s, denied, os.getenv("EDGAR_USER_AGENT", AGENT), expected)
            time.sleep(0.3)
        else:
            record, edition, rows = None, None, []
            attempts = last_status.get(doc, {}).get("attempts", [])
        if expected and expected["status"] == "available" and not record:
            sys.exit(f"{doc} could not be reproduced at its recorded fingerprint: {attempts}. "
                     "The previous passage index was preserved. Check network access or the source's edition.")
        if not expected and not record and last_status.get(doc, {}).get("status") == "available":
            sys.exit(f"{doc} was previously available and is missing from the cache. "
                     "The earlier passage index was preserved. Restore the cache or run with --fetch.")
        note = {"doc_id": doc, "status": "available" if record else "missing",
                "passage_count": len(rows), "attempts": attempts}
        if record:
            note.update(edition=record["edition"], url=record["url"], sha256=record["sha256"],
                        fetched_at_utc=record["fetched_at_utc"], bytes=record["bytes"],
                        replay_eligible=edition["replay_eligible"])
            for index, (kind, page, text) in enumerate(rows, 1):
                output.append({"doc_id": doc, "passage_id": f"{doc}-P{index:05d}", "text": text,
                               "issuer": s["issuer"], "source_kind": s["source_kind"], "kind": kind,
                               "url": record["url"], "canonical_url": s["url"],
                               "accepted_at_utc": s.get("accepted_at_utc"), "issued_at_utc": s.get("issued_at_utc"),
                               "source_edition": edition["edition"], "source_sha256": record["sha256"],
                               "replay_eligible": edition["replay_eligible"], "page": page})
        status.append(note)
        print(f"{doc} {note['status']}: {len(rows)} passages", flush=True)
    if not output and (DATA / "passages.jsonl").exists():
        sys.exit("No cache available. Existing passage index was preserved.")
    jsonl = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output)
    write_atomic(DATA / "passages.jsonl", jsonl.encode("utf-8"))
    write_atomic(status_path, json_bytes(status))
    print(f"{len(output)} passages. See data/collection_status.json for coverage and retrieval failures.")


if __name__ == "__main__":
    main()
