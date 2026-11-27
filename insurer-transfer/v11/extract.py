"""Link hurricane disclosures to financial tables with explicit attribution evidence."""
import argparse
from collections import defaultdict
from datetime import date
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("disclosure_v10", ROOT / "v10/extract.py")
v10 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v10)
v9, v7 = v10.v9, v10.v7
I = re.I
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
TRAIL_DATE = re.compile(r"\s*\((" + MONTH + r" \d{1,2}(?:,?\s+(?:19|20)\d{2})?)\)\s*$", I)
SEASON = re.compile(r"((?:19|20)\d{2})\s+(?:named )?(?:hurricanes|storms|typhoons|cyclones)(?: season)?$", I)
REPORT_END = re.compile(r"\b(?:quarter|(?:fiscal |calendar )?year|(?:three|six|nine|twelve) months) ended\s+("+MONTH+r" \d{1,2}),?\s+((?:19|20)\d{2})\b", I)
HEAD_YEAR = re.compile(r"(?:19|20)\d{2}$")
TOTAL = re.compile(r"(?:(?:group|company|consolidated|grand)\s+)?total(?: losses)?", I)
CATEGORY = re.compile(r"(?:hurricanes?|tropical storms?|typhoons?|cyclones?)(?:\s*(?:and|&|/)\s*(?:hurricanes?|tropical storms?|typhoons?|cyclones?))*", I)
BREAKDOWN = re.compile(r"(?:sources|components|breakdown|allocation|distribution|segments?)\s+of\s+these\s+(?:incurred\s+)?losses.{0,40}(?:as follows|below|following table)", I)
TABLE_INTRO = re.compile(r"\b(?:losses incurred|incurred losses)\b.{0,90}\b(?:following table|table below|set forth below)", I)
SECTION_UNIT = re.compile(r"\b(?:in this (?:discussion|section)|throughout this (?:discussion|section)),?\s+all\s+(?:U\.?S\.?\s+)?dollar amounts\s+(?:are (?:presented|stated|expressed)|appear)\s+in\s+(thousands|millions|billions)\b", I)
AMOUNT = re.compile(r"(?:US\s*)?\$\s*([\d,]+(?:\.\d+)?)\s*(?:(thousand|million|billion)s?\b)?", I)
LOSS = re.compile(r"\b(?:incurr(?:ed|ing)|catastroph(?:e|ic)|loss(?:es)?|loss adjustment)\b", I)
NON_LOSS = re.compile(r"\b(?:premium|earnings per share|industry|market-wide|model(?:led|ed)?|scenario|limit|threshold|protection)\b", I)
BASIS = re.compile(r"\b(gross|net)\b", I)


def header_and_data(table):
    headers, data = [], []
    for row in table.rows:
        if row.passage is None:
            continue
        cells = [c for c in row.cells if c.text]
        values = [(c, *v9.printed_amount(c, cells)) for c in cells]
        values = [item for item in values if item[2] is not None]
        if not values or (all(HEAD_YEAR.fullmatch(x[1]) for x in values) and not data):
            if data:
                break
            headers.append([v9.source(table, c) for c in cells])
        else:
            data.append((row, cells, values))
    return headers, data


def column_heads(headers, cell):
    return [h for group in headers for h in group if h.cell.covers(cell.col)]


def split_measure(heads):
    words = [h for h in heads if len(h.text)<90 and not v7.period_header(h.text)
             and not v10.unit_header(h.text) and not v7.BLOCKED.search(h.text)]
    if not words or any(v7.BLOCKED.search(h.text) for h in heads):
        return None, []
    phrase = " ".join(dict.fromkeys(h.text for h in words))
    if not v9.metric(phrase) or re.search(r"\b(?:count|number of|policies|claims filed)\b",phrase,I):
        return None, []
    return v9.Evidence(phrase, words[-1].index), words


def loss_qualifier(table, rows, record, item):
    notes = record["table_observations"][0].setdefault("accounting_context", [])
    pid = rows[item.index]["passage_id"]
    if pid not in record["evidence_passage_ids"]:
        record["evidence_passage_ids"].append(pid)
    if item.cell is not None:
        addr = v7.provenance(table, item.cell, rows)
    else:
        addr = dict(table=table.number, passage_id=pid, text=item.text)
    if addr not in notes:
        notes.append(addr)


def dated_rows(table, rows, headers, data, pre, post, filing, provenance, year):
    seasons = [h for group in headers for h in group if SEASON.fullmatch(h.text)]
    if len({SEASON.fullmatch(h.text)[1] for h in seasons}) != 1:
        return
    season = seasons[-1]
    y = int(SEASON.fullmatch(season.text)[1])
    if year and y > int(year):
        return
    target = rows[0]["event"]
    for row, cells, amounts in data:
        stamp = TRAIL_DATE.search(cells[0].text)
        if not stamp or not v7.named(cells[0].text[:stamp.start()], target):
            continue
        token = stamp[1].replace(",", "")
        parts = token.split()
        if len(parts)==3 and int(parts[-1])!=y:
            continue
        try:
            month_no = ("January February March April May June July August September October November December"
                        .lower().split().index(parts[0].lower()) + 1)
            occurrence = date(y, month_no, int(parts[1])).isoformat()
        except ValueError:
            continue
        for cell, literal, value, signs in amounts:
            col = column_heads(headers, cell)
            label, chain = split_measure(col)
            unit = v10.resolve_unit(col, headers, pre, post, [*col, v9.source(table,cell)])
            if not unit and any(re.fullmatch(r"\(?Dollars in (?:thousands|millions|billions)\)?",h.text,I) for h in col):
                unit = v9.units(col, headers, pre, post, [*col, v9.source(table,cell)])
            if not label or not unit:
                continue
            record = v9.build_record(table, rows, row, cell, value, literal, signs,
                                     v9.source(table,cells[0]), label, None, [], season.text, [season],
                                     str(y), unit, pre, post, False, filing, provenance)
            record["event_dates"] = [occurrence]
            if re.fullmatch(r"reinsurance recoveries",label.text,I):
                record["basis"] = "ceded reinsurance recoveries"
            for evidence in chain:
                loss_qualifier(table, rows, record, evidence)
            for other, othercells, _ in data:
                if other.passage > row.passage and re.fullmatch(r"total loss estimate",othercells[0].text,I):
                    record["status"]="estimate"
                    loss_qualifier(table,rows,record,v9.source(table,othercells[0]))
                    break
            yield record


def storm_amount(pre, target):
    # Link a single, literal loss amount by sentence or an immediate causal continuation.
    # Percentages, thresholds, ranges and combined storm totals do not authorize attribution.
    trigger = re.compile(r"\b" + re.escape(target) + r"\b", I)
    result = []
    for note in pre[:4]:
        clauses = re.split(r"(?<=[.!?])\s+|•", note.text)
        for position, clause in enumerate(clauses):
            event = trigger.search(clause)
            if not event or v10.STORMS.search(clause) or NON_LOSS.search(clause):
                continue
            if v7.v6.prior.event_names(clause)-{target.casefold()}:
                continue
            text = clause
            if position+1<len(clauses) and re.match(r"\s*(?:as a result|as a consequence)\b",clauses[position+1],I):
                text += " "+clauses[position+1]
            matches = list(AMOUNT.finditer(text))
            if len(matches)!=1 or not LOSS.search(text) or re.search(r"\b(?:between|range|at least|up to|aggregate|combined losses|including)\b|\bto\s+\$", text,I):
                continue
            amount = matches[0]
            if text[:amount.start()].rstrip().endswith(("(","-","−")) or amount[1].endswith(","):
                continue
            basis = BASIS.search(text)
            windows = REPORT_END.findall(text)
            dates = {(month_day.casefold(),y) for month_day,y in windows}
            if len(dates)!=1:
                continue
            end,y=dates.pop()
            result.append((note,Decimal(amount[1].replace(",","")),
                           v7.SCALES.get(amount[2].lower()) if amount[2] else None,
                           y,end,basis[0].lower() if basis else None))
    if len(result)==1:
        return result[0]
    return None


def scoped_unit(rows, start):
    for i in range(start-1,max(-1,start-36),-1):
        text = rows[i]["text"]
        unit = SECTION_UNIT.search(text)
        if unit and not v7.FX.search(text):
            note = v9.Evidence(text,i)
            return v7.SCALES[unit[1].lower().rstrip("s")],note,note
        if re.match(r"^(?:Item\s+[1-9]|Notes to (?:the )?Consolidated Financial Statements)", text,I):
            break
    return None


def contextual_rows(table, rows, headers, data, pre, post, filing, provenance):
    if not pre or not data:
        return
    storm = storm_amount(pre, rows[0]["event"])
    if not storm:
        return
    anchor, value, scale, y, end, stated_basis = storm
    link_breakdown = pre[0].index == anchor.index and BREAKDOWN.search(anchor.text)
    link_category = TABLE_INTRO.search(pre[0].text) and re.search(r"\b(?:by|type|category)\b",pre[0].text,I)
    if not link_breakdown and not link_category:
        return
    for row,cells,amounts in data:
        stub = cells[0]
        if link_breakdown:
            if not re.fullmatch(r"(?:gross |net )?(?:loss(?:es)? incurred|incurred loss(?:es)?)(?: and (?:loss )?adjustment expenses?)?",stub.text,I):
                continue
            metric = v9.source(table,stub)
        elif link_category and CATEGORY.fullmatch(stub.text):
            metric = v9.Evidence("Catastrophe losses incurred",pre[0].index)
        else:
            continue
        entries = []
        for cell,literal,signed,signs in amounts:
            heads = column_heads(headers,cell)
            if any(v7.BLOCKED.search(h.text) for h in heads):
                continue
            period = v9.period(heads,headers,pre,filing)
            if not period or period[2]!=y or end not in period[0].casefold():
                continue
            symbols = [v9.source(table,c) for c in cells if c.text in ("$","US$","USD")]
            unit = v10.resolve_unit(heads,headers,pre,post,symbols+[v9.source(table,cell)])
            declared = [h for group in headers for h in group if v10.unit_header(h.text) or v7.FX.search(h.text)]
            if not unit and not declared and link_category:
                unit=scoped_unit(rows,anchor.index)
            if not unit or (scale and unit[0]!=scale):
                continue
            owner_head = next((h for h in reversed(heads)
                            if re.fullmatch(r"[A-Za-z][\w .&/'-]{1,70}",h.text)
                            and not v7.period_header(h.text) and not v10.unit_header(h.text)),None) if link_breakdown else None
            if link_breakdown and not owner_head:
                continue
            owner = owner_head.text if owner_head and not TOTAL.fullmatch(owner_head.text) else None
            rec = v9.build_record(table,rows,row,cell,signed,literal,signs,anchor,metric,owner,
                                  [owner_head] if owner_head else [],*period,unit,pre,post,False,filing,provenance)
            if stated_basis and not rec["basis"]:
                rec["basis"] = stated_basis
            if link_category:
                loss_qualifier(table,rows,rec,v9.source(table,stub))
                for footnote in post:
                    if re.match(r"^\(\d+\)\s*total losses incurred includes losses",footnote.text,I):
                        loss_qualifier(table,rows,rec,footnote)
                        break
            entries.append((signed * unit[0],rec))
        totals = [(n,r) for n,r in entries if not r.get("segment") and n==value*(scale or r["unit_scale"])]
        if len(totals)!=1:
            continue
        total,record=totals[0]
        if link_breakdown:
            parts=[(n,r) for n,r in entries if r.get("segment")]
            if (not parts or len(entries)!=len(parts)+1 or len({r["segment"] for _,r in parts})!=len(parts)
                or sum(n for n,_ in parts)!=total):
                continue
            yield from (r for _,r in entries)
        else:
            yield record


def extract_filing(rows, body):
    previous = v10.extract_filing(rows, body)
    filing, report_year, provenance = v7.v6.prior.filing_period(rows)
    existing = {v10.addr(obs) for record in previous for obs in record.get("table_observations",[])}
    new = []
    for table in v7.read_tables(body,rows):
        if not any(r.passage is not None for r in table.rows):
            continue
        _,pre,post = v10.context(table,rows)
        headers,data = header_and_data(table)
        for record in [*dated_rows(table,rows,headers,data,pre,post,filing,provenance,report_year),
                       *contextual_rows(table,rows,headers,data,pre,post,filing,provenance)]:
            location=v10.addr(record["table_observations"][0])
            if location not in existing:
                existing.add(location)
                new.append(record)
    return previous+new


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs",type=Path)
    parser.add_argument("primary",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--event")
    args=parser.parse_args()
    groups=defaultdict(list)
    for line in args.inputs.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            record=json.loads(line)
            record["event"]=args.event or record["event"]
            groups[record["doc_id"],record["event"]].append(record)
    records=[r for (doc,_),rows in groups.items()
             for r in extract_filing(rows,(args.primary/(doc+".htm")).read_bytes())]
    args.output.parent.mkdir(exist_ok=True,parents=True)
    args.output.write_bytes((json.dumps(records,ensure_ascii=False,indent=2)+"\n").encode())


if __name__=="__main__":
    main()

