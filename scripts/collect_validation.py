"""Retrieve and index the locked accession inventory, including all filed text exhibits."""
import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from http.client import IncompleteRead, RemoteDisconnected
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from collect import AGENT, VisibleText, json_bytes, sha, write_atomic


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE = DATA / "validation_cache"
DOCUMENT = re.compile(br"(?ms)^<DOCUMENT>\s*\n(.*?)^</DOCUMENT>")
TEXT = re.compile(br"(?ms)^<TEXT>\r?\n(.*?)^</TEXT>")
LIMIT = 100_000_000


def mirror_url(filing):
    accession = filing["accession"]
    return f"https://edgar-mirror.sec-api.io/{int(filing['cik'])}/{accession.replace('-', '')}/{accession}.txt"


def sgml_field(data, name):
    m = re.search(br"(?m)^<" + name.encode("ascii") + br">([^\r\n]*)", data)
    return m[1].decode("utf-8", errors="replace").strip() if m else ""


def fetch_bytes(url, limit):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={"User-Agent": AGENT}), timeout=60) as response:
                if response.geturl() != url:
                    raise ValueError("Unexpected archive redirect")
                raw = response.read(limit + 1)
                if len(raw) > limit:
                    raise ValueError("Archive exceeded the size limit")
                return raw
        except HTTPError as exc:
            if exc.code not in {500, 502, 503, 504} or attempt == 2:
                raise
        except (TimeoutError, URLError, RemoteDisconnected, IncompleteRead):
            if attempt == 2:
                raise
        time.sleep(1 + attempt)


def receipt_or_fetch(f, fetch, pin):
    acc = f["accession"]
    raw_path, receipt_path = CACHE / f"{acc}.txt", CACHE / f"{acc}.retrieval.json"
    if raw_path.exists() and receipt_path.exists():
        raw = raw_path.read_bytes()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if sha(raw) != receipt["sha256"] or len(raw) != receipt["bytes"] or receipt["retrieved_url"] != mirror_url(f):
            raise ValueError(f"Receipt mismatch for {acc}")
    elif fetch:
        url = mirror_url(f)
        raw = fetch_bytes(url, LIMIT)
        receipt = {"retrieved_url": url, "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                   "sha256": sha(raw), "bytes": len(raw)}
    else:
        raise FileNotFoundError(f"Cache unavailable for {acc}. Use --fetch.")
    if len(raw) > LIMIT or not raw.startswith(f"<SEC-DOCUMENT>{acc}.txt".encode()) or b"</SEC-DOCUMENT>" not in raw[-200:]:
        raise ValueError(f"Invalid or truncated submission {acc}")
    if pin and pin != receipt["sha256"]:
        raise ValueError(f"Archive bytes differ from the pinned accession {acc}")
    if not raw_path.exists() or not receipt_path.exists():
        write_atomic(raw_path, raw)
        write_atomic(receipt_path, json_bytes(receipt))
    return raw, receipt


def filed_inventory(f, fetch, pin):
    path = CACHE / (f["accession"] + "-index.htm")
    if path.exists():
        raw = path.read_bytes()
    elif fetch:
        u = mirror_url(f)[:-4] + "-index.htm"
        raw = fetch_bytes(u, 2_000_000)
    else:
        raise FileNotFoundError(f"Filing index missing for {f['accession']}")
    if (pin and pin != sha(raw)) or f["accession"].encode() not in raw:
        raise ValueError(f"Wrong filing index for {f['accession']}")
    parser = VisibleText()
    parser.feed(raw.decode("utf-8"))
    parser.close()
    parser.flush()
    members, size = {}, None
    for kind, _, line in parser.rows:
        if kind != "table_row":
            continue
        cells = [c.strip() for c in line.split("|")]
        if "Complete submission text file" in cells:
            size = int(cells[-1])
        elif cells[0].isdigit() and len(cells) >= 5:
            file, typ = cells[-3].split()[0], cells[-2]
            if typ == f["form"] or (typ.startswith("EX-") and not typ.startswith(("EX-101", "EX-104"))):
                members[(int(cells[0]), file)] = typ
    if size is None or not members:
        raise ValueError(f"Could not parse filing document table in {f['accession']}")
    if not path.exists():
        write_atomic(path, raw)
    return members, size, sha(raw)


def filing_header(raw, f, utc_offset):
    header = raw.split(b"</SEC-HEADER>", 1)[0]
    for field, expected in (("ACCESSION NUMBER", f["accession"]), ("CONFORMED SUBMISSION TYPE", f["form"]),
                            ("FILED AS OF DATE", f["filing_date"].replace("-", "")), ("CENTRAL INDEX KEY", f["cik"])):
        matches = re.findall(rb"(?m)^\s*" + field.encode() + rb":[ \t]+([^\n\r]+)", header)
        if expected not in (v.decode().strip() for v in matches):
            raise ValueError(f"Unexpected {field} in {f['accession']}")
    local = datetime.strptime(sgml_field(header, "ACCEPTANCE-DATETIME"), "%Y%m%d%H%M%S")
    accepted = local.replace(tzinfo=timezone(timedelta(hours=utc_offset))).astimezone(timezone.utc)
    expected = int(re.search(br"PUBLIC DOCUMENT COUNT:\s*(\d+)", header)[1])
    return accepted.isoformat().replace("+00:00", "Z"), expected


def visible(payload, file):
    try:
        data = payload.decode("utf-8")
    except UnicodeDecodeError:
        data = payload.decode("windows-1252", errors="replace")
    if file.lower().endswith(".txt") and not re.search(r"<(?:html|body|p|div)\b", data, re.I):
        return [("paragraph", None, " ".join(x.split())) for x in re.split(r"\n\s*\n", data) if x.strip()]
    p = VisibleText()
    p.feed(data)
    p.close()
    p.flush()
    return p.rows


def parse(f, raw, receipt, offset, index):
    acc = f["accession"]
    accepted, declared_docs = filing_header(raw, f, offset)
    index_members, index_bytes, index_digest = index
    if index_bytes != len(raw):
        raise ValueError(f"The raw submission size differs from the EDGAR filing index in {acc}")
    pieces, rows = [], []
    for block in DOCUMENT.finditer(raw):
        header, marker, _ = block[1].partition(b"<TEXT>")
        file, typ, seq = (sgml_field(header, name) for name in ["FILENAME", "TYPE", "SEQUENCE"])
        if not file or not typ or not seq.isdigit():
            raise ValueError(f"Missing document identity in {acc}")
        doc_id = f"{acc}-{int(seq):03d}"
        canonical = f["filing_index"].rsplit("/", 1)[0] + "/" + file
        part = {"doc_id": doc_id, "filename": file, "document_type": typ, "sequence": int(seq),
                "canonical_url": canonical, "passages": 0}
        pieces.append(part)
        if typ != f["form"] and (not typ.startswith("EX-") or typ.startswith(("EX-101", "EX-104"))):
            part["status"] = "outside_main_and_text_exhibits"
            continue
        if not file.lower().endswith((".htm", ".html", ".txt")):
            part["status"] = "requires_external_format_reader"
            continue
        text = TEXT.search(block[1]) if marker else None
        if not text:
            part["status"] = "missing_text"
            continue
        payload = text[1]
        part["sha256"] = sha(payload)
        part["images"] = len(re.findall(rb"<img\b", payload, re.I))
        passages = visible(payload, file)
        nwords = sum(len(t.split()) for _, _, t in passages)
        part["words"] = nwords
        part["passages"] = len(passages)
        part["status"] = ("empty_body" if not passages else "image_dominated" if part["images"] and
                          nwords < 10 * part["images"] else "text_available")
        for i, (kind, page, t) in enumerate(passages, 1):
            rows.append({"accession": acc, "doc_id": doc_id, "passage_id": f"{doc_id}-P{i:05d}",
                         "issuer": f["issuer"], "source_kind": typ, "document_type": typ, "kind": kind,
                         "text": t, "page": page, "accepted_at_utc": accepted, "replay_eligible": True,
                         "source_edition": "archived_sec_sgml_member", "url": receipt["retrieved_url"],
                         "canonical_url": canonical, "source_sha256": part["sha256"]})
    if len({p["doc_id"] for p in pieces}) != len(pieces):
        raise ValueError(f"Duplicate component sequence number in {acc}")
    actual = {(p["sequence"], p["filename"]): p["document_type"] for p in pieces
              if p["status"] != "outside_main_and_text_exhibits"}
    if actual != index_members:
        raise ValueError(f"Primary form and exhibits differ from the EDGAR filing index in {acc}")
    if sum(p["document_type"] == f["form"] for p in pieces) != 1:
        raise ValueError(f"Expected one primary {f['form']} in {acc}")
    return {"accession": acc, "issuer": f["issuer"], "accepted_at_utc": accepted, "filing_index": f["filing_index"],
            "raw_sha256": receipt["sha256"], "raw_bytes": receipt["bytes"], "url": receipt["retrieved_url"],
            "index_sha256": index_digest, "index_full_submission_bytes": index_bytes,
            "header_public_document_count": declared_docs, "parsed_sgml_members": len(pieces),
            "source_edition": "archived_sec_sgml", "components": pieces}, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Download missing copies from the documented public archive")
    args = parser.parse_args()
    CACHE.mkdir(exist_ok=True)
    locked = json.loads((DATA / "evaluation_filings.json").read_text(encoding="utf-8"))["filings"]
    manifest = json.loads((DATA / "validation_sources.json").read_text(encoding="utf-8"))
    pins = {x["accession"]: x for x in manifest["submissions"]}
    if set(pins) != {f["accession"] for f in locked}:
        raise ValueError("Source inventory differs from locked roster")
    statuses, rows = [], []
    allow_download = args.fetch
    for f in locked:
        acc = f["accession"]
        try:
            if allow_download and not (CACHE / f"{acc}.txt").exists():
                time.sleep(.7)
            raw, receipt = receipt_or_fetch(f, allow_download, pins[acc].get("sha256"))
            index = filed_inventory(f, allow_download, pins[acc].get("index_sha256"))
            status, parts = parse(f, raw, receipt, pins[acc]["acceptance_utc_offset_hours"], index)
            if pins[acc].get("accepted_at_utc") and pins[acc]["accepted_at_utc"] != status["accepted_at_utc"]:
                raise ValueError(f"Acceptance time for {acc} disagrees with the inventory")
            if pins[acc].get("primary_document"):
                primary = next(p for p in status["components"] if p["document_type"] == f["form"])
                if primary["filename"] != pins[acc]["primary_document"]:
                    raise ValueError(f"Unexpected primary filename in {acc}")
            rows.extend(parts)
            status["status"] = "complete_text_scope" if all(
                p["status"] in {"text_available", "outside_main_and_text_exhibits"}
                for p in status["components"]) else "partial_text_scope"
        except (OSError, IncompleteRead) as e:
            if isinstance(e, HTTPError) and e.code in {401, 403, 429}:
                allow_download = False
            status = {"accession": acc, "issuer": f["issuer"], "filing_index": f["filing_index"],
                      "status": "unavailable", "reason": str(e), "components": []}
        statuses.append(status)
        print(acc, status["status"], flush=True)
    if any(s["status"] == "unavailable" for s in statuses) and (DATA / "validation_passages.jsonl").exists():
        previous = {s["accession"] for s in statuses if s["status"] == "unavailable"}
        with (DATA / "validation_passages.jsonl").open(encoding="utf-8") as existing:
            if any(json.loads(line)["accession"] in previous for line in existing):
                raise ValueError("A previously indexed accession is now missing. Earlier outputs preserved.")
    content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8")
    write_atomic(DATA / "validation_passages.jsonl", content)
    write_atomic(DATA / "validation_status.json", json_bytes(statuses))
    print(f"{len(rows)} passages. SHA-256 {hashlib.sha256(content).hexdigest()}")


if __name__ == "__main__":
    main()
