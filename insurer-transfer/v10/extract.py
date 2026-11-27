"""Extract hurricane financial disclosures with table, context and currency provenance."""
import argparse
from collections import defaultdict
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("disclosure_v9", ROOT / "v9/extract.py")
v9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v9)
v7 = v9.v7

# Equivalents of "USD in thousands" in an accounting header, never a data value.
SHORT_UNIT = re.compile(r"""^\s*\(?\s*(?:(?:amounts?|figures|dollars?)\s+(?:in\s+)?|in\s+)?
    (?:(?:U\.?S\.?\s*)?\$|USD)\s*['’]?(000(?:,000){0,2}|[KMB])(?:['’]?s)?
    \s*\)?\s*$""", re.I | re.X)
SCALES = {"000": 1000, "000,000": 10**6, "000,000,000": 10**9,
          "K": 1000, "M": 10**6, "B": 10**9}
DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?![\d/])")
LOSS_LABEL = re.compile(r"\b(?:(?:net|gross|retained|insured|incurred|estimated|ultimate|property|"
                        r"catastrophe|catastrophic|pre-tax|after-tax|paid)\s+){1,6}"
                        r"loss(?:es)?(?: and (?:loss )?adjustment expenses?)?\b", re.I)
INTRO = re.compile(r"\b(?:the following|summari[sz]ed (?:in|below)|table (?:below|shows|presents|details)|"
                   r"set forth below|as follows|listed below)\b", re.I)
REPORT_WINDOW = re.compile(r"\b(?:as of|(?:fiscal |calendar )?year ended|(?:three|six|nine|twelve) months ended)"
                           r"\s+[A-Z][a-z]+ \d{1,2},?\s+(?:19|20)\d{2}\b", re.I)
STORMS = re.compile(r"\b(?:[Hh]urricanes?|[Ss]torms?|[Tt]yphoons?|[Cc]yclones?)\s+"
                    r"([A-Z][a-z]+(?:(?:,\s*(?:and\s+)?|\s+(?:and|&)\s+)[A-Z][a-z]+)+)")
MONEY = re.compile(r"(?:US\s*)?\$\s*\d|USD\s+\d", re.I)


def compact_scale(text):
    match = SHORT_UNIT.fullmatch(text)
    return SCALES[match[1].upper()] if match and not v7.FX.search(text) else None


def event_dates(text, report_year):
    """Resolve two-digit dates to the nearest century of the independently dated filing."""
    dates = []
    for m in DATE.finditer(text):
        month, day, year = map(int, m.groups())
        if len(m[3]) == 2:
            if report_year is None:
                return []
            century = report_year - report_year % 100
            years = sorted((century + year + delta for delta in (-100, 0, 100)),
                           key=lambda candidate: abs(candidate - report_year))
            if abs(years[0] - report_year) == abs(years[1] - report_year):
                return []
            year = years[0]
        try:
            dates.append(date(year, month, day).isoformat())
        except ValueError:
            return []
    return dates


def intro_metric(pre):
    if not pre:
        return None
    text = pre[0].text
    if not (pre[0].caption or INTRO.search(text)) or re.search(r"\bindustry|market-wide|per share", text, re.I):
        return None
    matches = list(LOSS_LABEL.finditer(text))
    # A paragraph defining a balance threshold can still give the measure, never the amount.
    definitions = [m for m in matches if re.search(r"\bdefined as\b.{0,110}$", text[:m.start()], re.I)]
    if len({m[0].lower() for m in matches}) != 1 and len(definitions) != 1:
        return None
    if not matches:
        return None
    phrase = (definitions or matches)[-1][0]
    category = re.match(r"^(?:impact of )?((?:property |natural )?catastrophe) losses\b", text, re.I)
    if category and "catastroph" not in phrase.lower():
        phrase = re.sub(r"loss(es)?\b", lambda m: category[1].lower()+" "+m[0], phrase, count=1, flags=re.I)
    return v9.Evidence(phrase, pre[0].index, caption=pre[0].caption)


def row_owner(cell):
    text = cell.text.strip(" :.").strip()
    if re.fullmatch(r"(?:company |group |grand )?(?:total|consolidated)", text, re.I):
        return ""
    if len(text) < 90 and v9.KNOWN_OWNER.search(text) and not v7.BLOCKED.search(text) and not v9.metric(text):
        return re.sub(r"\s+segment$", "", text, flags=re.I)
    return None


def context(table, rows):
    used = [r for r in table.rows if r.passage is not None]
    pre = v9.neighboring(rows, used[0].passage, -1)
    if table.caption:
        cap = v7.tidy("".join(table.caption))
        src = next((x.index for x in pre if x.text == cap), None)
        pre.insert(0, v9.Evidence(cap, src, caption=True))
    # EDGAR sometimes wraps a printed footnote in a separate one-row layout table.
    # Cross that boundary only for a footnote marker attached to non-tabular text.
    post = []
    for idx in range(used[-1].passage + 1, min(len(rows), used[-1].passage + 4)):
        r = rows[idx]
        if r["kind"] == "table_row" and not (
                re.match(r"^\s*(?:\(\d{1,2}\)|\*+)\s+\w", r["text"]) and "|" not in r["text"]):
            break
        post.append(v9.Evidence(r["text"], idx))
    return used, pre, post


def accounting_context(record, pre, post, rows):
    label = record["measure"]
    extra = []
    if pre and re.search(r"\bbefore tax\b", pre[0].text, re.I) and re.search(r"\b(?:summary|table|below)\b", pre[0].text, re.I):
        record["tax_basis"] = "pretax"
        extra.append(pre[0])
        if "reinstatement" in pre[0].text.lower() and "premiums" in pre[0].text.lower():
            record["premium_treatment"] = "before reinstatement and additional premium effects"
    if pre and re.search(r"net loss retention.{0,70}table below", pre[0].text, re.I):
        record["basis"] = "retained net of catastrophe reinsurance" if "reinsurance" in pre[0].text.lower() else "retained net"
        if "pre-tax" in pre[0].text.lower():
            record["retention_tax_basis"] = "pretax"
        extra.append(pre[0])
    for note in post:
        marker = re.search(r"\((\d+)\)\s*$", label)
        if marker and re.match(r"\("+marker[1]+r"\)\s+net of (?:outwards? )?reinsurance recoveries", note.text, re.I):
            record["basis"] = "net of reinsurance recoveries"
            extra.append(note)
        if "incurred" in label.lower() and re.search(r"best estimate of (?:our |the )?ultimate liability", note.text, re.I):
            record["status"] = "incurred; estimated ultimate loss"
            extra.append(note)
        if re.match(r"\*.*\b(?:in total|combined)\b", note.text, re.I):
            extra.append(note)
    observation = record["table_observations"][0]
    notes = observation.setdefault("accounting_context", [])
    for item in extra:
        if item.index is None:
            continue
        pid = rows[item.index]["passage_id"]
        if pid not in record["evidence_passage_ids"]:
            record["evidence_passage_ids"].append(pid)
        if not any(n.get("passage_id") == pid for n in notes):
            notes.append({"passage_id": pid, "text": item.text})


def unit_header(text):
    # A stub such as "($ in millions)" may sit on the same row as named financial columns.
    if compact_scale(text):
        return compact_scale(text)
    if len(text) < 70 and not v9.MEASURE.search(text):
        return v9.unit_scale(text)
    return None


def resolve_unit(column, headers, pre, post, symbols):
    """A notation in the stub heads the table. Per-column notations bind only down their column."""
    local = [h for h in column if unit_header(h.text)]
    shared = [h for group in headers for h in group if unit_header(h.text) and (h.cell.col == 0 or len(group) == 1)]
    candidates = local or shared
    if not candidates:
        return v9.units(column, headers, pre, post, symbols)
    scales = {unit_header(h.text) for h in candidates + shared}
    for h in [*column, *shared, *[g[0] for g in headers if len(g) == 1], *pre[:1], *post[:1]]:
        if v7.FX.search(h.text) and (v9.SCALE.search(h.text) or h in column):
            return None
        if (h.cell is not None or v9.is_unit_note(h.text)) and v9.unit_scale(h.text):
            scales.add(v9.unit_scale(h.text))
    if len(scales) != 1:
        return None
    explicit_currency = next((h for h in [*candidates, *symbols] if v7.USD.search(h.text)), None)
    return (scales.pop(), candidates[-1], explicit_currency) if explicit_currency else None


def dated_window(column, headers, pre, filing, cover, report_year):
    result = v9.period(column, headers, pre, filing)
    dates = [(h, event_dates(h.text, report_year)) for h in column if DATE.search(h.text)]
    if any(not parsed for h, parsed in dates):
        return None
    if not result:
        # Distinguish the financial reporting window from loss-event dates.
        intro = next((n for n in pre[:1] if REPORT_WINDOW.search(n.text) and INTRO.search(n.text)), None)
        if intro:
            window = REPORT_WINDOW.search(intro.text)[0]
            result = window, [intro], v9.YEAR.search(window)[0]
        elif dates and cover is not None and filing and report_year:
            result = filing, [cover], str(report_year)
        else:
            return None
    window, evidence, year = result
    if len(window) > 100 and REPORT_WINDOW.search(window):
        window = REPORT_WINDOW.search(window)[0]
    return window, evidence, year, dates


def candidates(table, rows, filing, cover, report_year):
    used, pre, post = context(table, rows)
    target = rows[0]["event"]
    if not any(v7.named(c.text, target) for row in used for c in row.cells):
        return
    if pre and re.search(r"\b(?:industry-wide|industry losses|industry insured losses|losses for the industry)\b", pre[0].text, re.I):
        return
    caption_label = intro_metric(pre)
    headers, section = [], None
    symbols = [v9.source(table, c) for row in used for c in row.cells if c.text in ("$", "USD", "US$")]
    for row in used:
        cells = [c for c in row.cells if c.text]
        amounts = [(c, *v9.printed_amount(c, cells)) for c in cells]
        amounts = [item for item in amounts if item[2] is not None]
        if len(amounts) == 1 and compact_scale(amounts[0][0].text) and (
                len(cells) == 1 or any(v9.metric(c.text) for c in cells)):
            amounts = []
        if not amounts or (all(v9.YEAR.fullmatch(a[1]) for a in amounts) and not any(v7.named(c.text, target) for c in cells)):
            hs = [v9.source(table,c) for c in cells]
            if len(hs) == 1 and cells[0].col == 0 and not (v7.period_header(cells[0].text) or v9.unit_scale(cells[0].text) or compact_scale(cells[0].text)):
                section = hs[0] if v9.metric(cells[0].text) else None
            headers.append(hs)
            continue
        row_event = next((c for c in cells if v7.named(c.text, target)), None)
        for amount, literal, number, signs in amounts:
            column = [h for group in headers for h in group if h.cell.covers(amount.col)]
            if any(v7.BLOCKED.search(h.text) for h in column):
                continue
            col_event = next((h for h in reversed(column) if v7.named(h.text, target)), None)
            # Suppress accidental cross-binding if the selected column also names a different storm.
            if any(v7.v6.prior.event_names(h.text) - {target.casefold()} for h in column):
                continue
            if not row_event and not col_event:
                continue
            unit = resolve_unit(column, headers, pre, post, symbols + [v9.source(table, amount)])
            dated = dated_window(column, headers, pre, filing, cover, report_year)
            if not unit or not dated:
                continue
            window, evidence, year, dates = dated
            owner, owner_cells = None, []
            if row_event:
                anchored = v9.source(table, row_event)
                if amount.col <= row_event.col or any(c for c in cells if row_event.col < c.col < amount.col and re.search(r"[a-z]{2}", c.text, re.I) and not v7.USD.fullmatch(c.text)):
                    continue
                labels = [h for h in column if v9.metric(h.text) and h.cell.col > row_event.col]
                if labels and (compact_scale(unit[1].text) or (unit[1].cell is not None and unit[1].cell.col == 0)):
                    label = labels[-1]
                elif caption_label and len(amounts) == 1 and not labels and section is None:
                    label = caption_label
                else:
                    continue
            else:
                anchored = col_event
                if section is None or not cells or cells[0].col >= amount.col:
                    continue
                if (dates or compact_scale(unit[1].text)) and v9.metric(cells[0].text):
                    label = v9.source(table, cells[0])
                else:
                    if section is None:
                        continue
                    owner = row_owner(cells[0])
                    if owner is None:
                        continue
                    owner_cells = [v9.source(table, cells[0])]
                    label = section
            record = v9.build_record(table, rows, row, amount, number, literal, signs, anchored, label, owner,
                                     owner_cells, window, evidence, year, unit, pre, post, False, filing,
                                     rows[cover.index]["passage_id"] if cover is not None else None)
            if dates:
                observation = record["table_observations"][0]
                record["event_dates"] = list(dict.fromkeys(d for h, parsed in dates for d in parsed))
                observation["event_date_cells"] = [v7.provenance(table, h.cell, rows) for h, parsed in dates]
                record["evidence_passage_ids"] = list(dict.fromkeys([*record["evidence_passage_ids"], *[rows[h.index]["passage_id"] for h, parsed in dates]]))
            if label is caption_label and "net" in label.text.lower():
                record["basis"] = "net"
            if label is caption_label:
                record["table_observations"][0]["metric_cell"]["text"] = pre[0].text
            accounting_context(record, pre, post, rows)
            yield record


def multi_event_total(record):
    """Reject one dollar assertion explicitly governed by a coordinated storm list."""
    if record.get("review") or record.get("table_observations"):
        return False
    text, literal = record.get("evidence", ""), record.get("amount_text", "")
    if not literal or literal not in text:
        return False
    i = text.index(literal)
    for group in STORMS.finditer(text):
        if not re.search(r"\b"+re.escape(record["event"])+r"\b", group[1], re.I):
            continue
        if group.end() <= i:
            bridge = text[group.end():i]
            if len(bridge) <= 130 and not MONEY.search(bridge) and re.fullmatch(
                    r"\s*(?:of|(?:in [\w -]+,?\s+)?with (?:a )?(?:total |combined |aggregate )?"
                    r"(?:net |gross )?(?:impact|loss(?:es)?|cost)(?: of)?|"
                    r"(?:together |combined )?(?:caused|amounted to|totaled|were))\s*", bridge, re.I):
                return True
        else:
            bridge = text[i + len(literal):group.start()]
            if re.fullmatch(r"\s*(?:(?:in total|combined)\s+)?(?:from|for|due to|attributable to)\s*", bridge, re.I):
                return True
    return False


def ambiguous_declared_unit(record, by_number):
    # Earlier versions permitted a scale of one when they saw a dollar sign.
    # A header that also declares an unreadable, foreign or conflicting unit
    # invalidates that fallback even when no newer record can replace it.
    for o in record.get("table_observations", []):
        a = o["amount_cell"]
        table = by_number.get(a["table"])
        if table is None:
            continue
        col = a["column"] - 1
        declarations = set()
        for row in table.rows[:a["row"]-1]:
            values = [c for c in row.cells if c.text]
            if not values:
                continue
            for c in values:
                if c.col != 0 and not c.covers(col) and len(values) != 1:
                    continue
                t = c.text.strip()
                scale = unit_header(t)
                if scale:
                    declarations.add(scale)
                elif re.fullmatch(r"\(?\s*(?:[A-Z]{0,3}\$|USD)\s*['’]?0{3}[\w, ?'’.-]*\s*\)?", t, re.I):
                    return True
                elif v7.FX.search(t) and re.search(r"(?:[KMB]\b|thousand|million|billion|000)",t,re.I):
                    return True
        if len(declarations) > 1 or (declarations and record.get("unit_scale") not in declarations):
            return True
    return False


def addr(observation):
    cell = observation["amount_cell"]
    return cell["table"], cell["row"], cell["column"]


def extract_filing(rows, body):
    previous = v9.extract_filing(rows, body)
    filing, report_year, provenance = v7.v6.prior.filing_period(rows)
    if filing and rows[0].get("source_kind", "").upper() in ("20-F", "40-F"):
        filing = "FY"+str(report_year)
    cover = next((v9.Evidence(r["text"], i) for i, r in enumerate(rows) if r["passage_id"] == provenance), None)
    new = {}
    by_number = {}
    for table in v7.read_tables(body, rows):
        by_number[table.number] = table
        if any(r.passage is not None for r in table.rows):
            for record in candidates(table, rows, filing, cover, report_year):
                new[addr(record["table_observations"][0])] = record
    out = []
    for record in previous:
        if multi_event_total(record) or ambiguous_declared_unit(record, by_number):
            continue
        old = record.get("table_observations", [])
        if any(addr(o) in new for o in old):
            if len(old) > 1 and not all(addr(o) in new for o in old):
                remaining = [o for o in old if addr(o) not in new]
                out.append(dict(record, table_observations=remaining))
            continue
        if record.get("source_channel") == "single_value_table" and any(
                r["passage_id"] == record["passage_id"] and r["low_usd"] == record["low_usd"] for r in new.values()):
            continue
        out.append(record)
    return [*out, *new.values()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("primary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--event")
    args = parser.parse_args()
    groups = defaultdict(list)
    for line in args.input.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            row = json.loads(line)
            if args.event:
                row["event"] = args.event
            groups[row["doc_id"],row["event"]].append(row)
    records = []
    for (doc, _), rows in groups.items():
        records.extend(extract_filing(rows, (args.primary / (doc+".htm")).read_bytes()))
    args.output.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf8", dir=args.output.parent, delete=False) as out:
        json.dump(records, out, ensure_ascii=False, indent=2)
        out.write("\n")
    os.replace(out.name, args.output)


if __name__ == "__main__":
    main()

