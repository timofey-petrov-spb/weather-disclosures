"""Source-linked financial tables with a governing title or a period-specific attribution note.

Run: python v8/extract.py INPUTS.jsonl PRIMARY_HTML_DIRECTORY OUTPUT.json
"""

import argparse
from collections import defaultdict
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "v7"))
_spec = importlib.util.spec_from_file_location("previous_table_reader", ROOT / "v7/extract.py")
v7 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v7)

I = re.I
DIFFERENCE = re.compile(r"\b(?:change|difference|variance|percentage|ratio|development)\b|%", I)
DURATION = re.compile(
    r"\b(three months?|nine months?|six months?|twelve months?|quarter|year)\s+ended\b", I
)
CALENDAR = re.compile(r"\b(" + v7.DATE.pattern + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", I)
SEGMENT = re.compile(
    r"^(?:commercial|personal|specialty|excess(?: and | & )surplus|E&S|"
    r"reinsurance|insurance|property|casualty|other|total|consolidated|"
    r".{1,55}(?:segment|division|lines?|operations?|business))$",
    I,
)
PARTIAL = re.compile(
    r"\b(?:includ(?:ed|es|ing)|partial(?:ly)?|portion|among|several|various|"
    r"primarily|largely|mainly|predominantly|some|partly|additional|industry|"
    r"exclud(?:ed|es|ing)|unrelated|except|not|none)\b",
    I,
)
UNITS = re.compile(r"\b(?:U\.?S\.?\s+)?dollars?\s+in\b", I)


def window(texts):
    text = " ".join(dict.fromkeys(texts))
    years = set(v7.YEAR.findall(text))
    dates = {(m[1].lower(), int(m[2])) for m in CALENDAR.finditer(text)}
    periods = {m[1].lower() for m in DURATION.finditer(text)}
    periods = {
        "three months" if s in ("quarter", "three month") else "year" if s == "twelve months" else s
        for s in periods
    }
    if len(years) == len(dates) == len(periods) == 1:
        month, day = next(iter(dates))
        return (next(iter(years)), month, day, next(iter(periods)))
    if len(years) == 1 and not dates and periods == {"year"}:
        return (next(iter(years)), "annual", 0, "year")
    return None


def visible(row):
    return [c for c in row.cells if c.text]


def source_title(table, rows, before):
    candidates = []
    if table.caption:
        candidates.append((v7.tidy("".join(table.caption)), None))
    for i, t in reversed(before):
        lead = re.search(
            r"(?:the following table|the table (?:below|that follows))\s+"
            r"(?:summari[sz]es|shows|presents|sets (?:out|forth)|details)\s+(?:our |the )?"
            r"(?P<measure>[^:.]{3,130}?)(?=[,.;:]|\s+for (?:the|each)|$)",
            t,
            I,
        )
        if lead:
            candidates.append((lead["measure"].strip(), i))
        elif len(t) < 150 and not re.search(r"[:;]|[.!?]\s+\w", t):
            if not v7.metric(t) and not v7.UNIT.search(t) and not DURATION.search(t):
                # A new, unrelated section heading breaks the previous title's scope.
                break
            candidates.append((t, i))
    for t, i in candidates:
        if (
            v7.metric(t)
            and re.search(r"\b(?:catastroph(?:e|ic)|storm|weather|event|losses incurred)\b", t, I)
            and not PARTIAL.search(t)
        ):
            return t, i
    return None, None


def geography_alias(c, headers, target):
    # A regional descriptor in the explicitly labelled geography column can carry
    # one storm in parentheses. Parentheses anywhere else are not event evidence.
    if not any(
        h.covers(c.col) and re.fullmatch(r"region|location|geography|territory|area", h.text, I)
        for h in headers
    ):
        return False
    match = re.fullmatch(r"([A-Za-z][A-Za-z .,\-]{0,70})\s*\(\s*" + re.escape(target) + r"\s*\)", c.text, I)
    return bool(
        match
        and not re.search(
            r"\b(?:total|other|aggregate|storms?|events?|catastrophes?|including|combined)\b", match[1], I
        )
    )


def segment_for_column(cols):
    words = [c for c in cols if not (v7.period_header(c.text) or v7.UNIT.search(c.text))]
    if not words or all(c.text.casefold() in ("amount", "amounts", "reported amount") for c in words):
        return "Total", words
    if any(v7.metric(c.text) or DIFFERENCE.search(c.text) for c in words):
        return None, []
    raw = " ".join(c.text for c in words)
    name = re.sub(r"\bComm\.(?=\s|$)", "Commercial", raw, flags=I)
    name = re.sub(r"\bPers\.(?=\s|$)", "Personal", name, flags=I)
    if not SEGMENT.fullmatch(name) or name.casefold() in ("line", "lines"):
        return None, []
    return name, words


def note_rows(rows, last):
    result = []
    for i in range(last + 1, min(last + 5, len(rows))):
        p = rows[i]
        # The immediate narrative after the grid can contain parallel period notes.
        # A heading, another grid or an intervening unrelated paragraph ends the scope.
        if p["kind"] == "table_row" or not re.search(
            r"\b(?:loss(?:es)?|claims?|expenses?|premiums?|recoveries)\b", p["text"], I
        ):
            break
        if not (CALENDAR.search(p["text"]) or v7.v6.prior.event_names(p["text"])):
            break
        result.append((i, p["text"]))
    return result


def note_for(label, notes, period, target, amount):
    if not period:
        return None
    subject = re.escape(label.rstrip(":. "))
    storm = rf"(?:(?:{v7.v6.PERIL})\s+)?{re.escape(target)}"
    causality = (
        r"(?:were|was|are|is)\s+(?:(?:entirely|solely)\s+)?"
        r"(?:attributable to|related to|caused by|due to|from)|resulted from|arose from|"
        r"consisted (?:entirely |solely )?of"
    )
    quoted = r"(?:\s+of\s+(?:US\$|\$|USD\s*)\s*(?P<quoted>[\d,]+(?:\.\d+)?)\s*(?P<unit>thousand|million|billion)?s?)?"
    attribution = re.compile(
        rf"^(?:(?:our|the|these)\s+)?{subject}{quoted}\s+(?:{causality})\s+"
        rf"(?:(?:losses?|claims?|damage)\s+(?:from|caused by|associated with)\s+)?"
        rf"{storm}\b(?P<tail>.*)$",
        I,
    )
    bound = []
    for i, text in notes:
        if window([text]) != period or v7.FX.search(text):
            continue
        if re.search(
            r"\b(?:additional|other|remaining)\s+(?:events?|storms?|catastrophes?|losses?)\b|"
            r"\b(?:also|partly|partially|in part)\s+(?:included|due|attributed|caused|related|resulted)\b",
            text,
            I,
        ):
            continue
        attributable = False
        conflicted = False
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            # A leading period clause is permissible when it scopes this assertion.
            sentence = re.sub(r"^(?:for|during) the [^.;]+?\b(?:19|20)\d\d,?\s+", "", sentence, flags=I)
            m = attribution.match(sentence)
            if not m:
                if re.match(
                    rf"^(?:our |the |these )?{subject}\s+(?:were|was|included|resulted|arose|also)\b",
                    sentence,
                    I,
                ):
                    conflicted = True
                continue
            if m["quoted"]:
                magnitude = (
                    Decimal(m["quoted"].replace(",", "")) * v7.SCALES[(m["unit"] or "dollar").lower()]
                )
                if abs(amount) != magnitude:
                    conflicted = True
                    continue
            tail = m["tail"].strip(" ,.:;")
            # A description of what the named storm impacted is not another cause.
            if tail and not re.match(
                r"^(?:which|that)\s+(?:(?:primarily|mainly)\s+)?(?:impacted|affected|damaged)\b", tail, I
            ):
                continue
            if re.search(
                r"\b(?:other storms?|other events?|except|excluding|plus|along with|in addition to|also included)\b",
                tail,
                I,
            ):
                continue
            if v7.v6.prior.event_names(text) - {target.casefold()}:
                continue
            attributable = True
        if conflicted:
            return None
        if attributable:
            bound.append(i)
        elif re.search(
            r"(?:^|[.!?]\s+)(?:our |the |these )?" + subject + r"\s+(?:were|was|included|arose|resulted)",
            text,
            I,
        ):
            return None
    return bound[0] if len(bound) == 1 else None


def amount_unit(headers, label, amount, cells, cols, before):
    result = v7.active_units(headers, label, amount, cells, cols, before)
    if not result:
        return None
    scale, unit_cell, unit_idx = result
    unit_text = unit_cell.text if unit_cell else dict(before).get(unit_idx, amount.text)
    if (
        v7.FX.search(unit_text)
        or any(v7.FX.search(c.text) for c in [*headers, *cells])
        or any(v7.FX.search(text) and v7.UNIT.search(text) for _, text in before)
    ):
        return None
    currency_cell = next(
        (
            c
            for c in [unit_cell, amount, *cells, *headers]
            if c and (v7.USD.search(c.text) or UNITS.search(c.text))
        ),
        None,
    )
    currency_idx = next(
        (
            i
            for i, t in reversed(before)
            if (v7.UNIT.search(t) or "table" in t.lower())
            and (v7.USD.search(t) or UNITS.search(t))
            and not v7.FX.search(t)
        ),
        None,
    )
    if not currency_cell and currency_idx is None:
        return None
    return scale, unit_cell, unit_idx, unit_text, currency_cell, currency_idx


def attributed_cells(table, rows, filing, fiscal, period_src):
    populated = [r for r in table.rows if r.passage is not None]
    if not populated:
        return
    target = rows[0]["event"]
    before = v7.governing_rows(rows, populated[0].passage)
    title, title_i = source_title(table, rows, before)
    notes = note_rows(rows, populated[-1].passage)
    if not (
        title
        and any(re.search(r"\b" + re.escape(target) + r"\b", rows[r.passage]["text"], I) for r in populated)
        or any(re.search(r"\b" + re.escape(target) + r"\b", t, I) for _, t in notes)
    ):
        return
    headers = []
    block_year = None
    started = False
    for row in populated:
        cells = visible(row)
        nums = [(c, *v7.printed_amount(c, cells)) for c in cells]
        nums = [(c, s, v, adj) for c, s, v, adj in nums if v is not None]
        if len(cells) == 1 and re.fullmatch(r"(?:19|20)\d\d", cells[0].text) and cells[0].col == 0:
            block_year = cells[0]
            continue
        is_year_header = bool(nums) and all(re.fullmatch(r"(?:19|20)\d\d", s) for _, s, _, _ in nums)
        if not started and (not nums or is_year_header):
            headers.extend(cells)
            continue
        if not nums:
            continue
        started = True
        anchor = next(
            (c for c in cells if v7.named(c.text, target) or geography_alias(c, headers, target)), None
        )
        if anchor and (
            not title or any(v7.v6.prior.event_names(c.text) - {target.casefold()} for c in cells)
        ):
            continue
        if anchor and block_year and fiscal and int(block_year.text) != fiscal:
            continue
        for amount, literal, value, signs in nums:
            cols = [c for c in headers if c.covers(amount.col)]
            if any(DIFFERENCE.search(c.text) for c in cols if not v7.UNIT.search(c.text)) or any(
                c.text == "%" and abs(c.col - amount.col) <= amount.width for c in cells
            ):
                continue
            period_cells = [c for c in cols if v7.period_header(c.text)]
            if block_year:
                period_cells.append(block_year)
            periods = [c.text for c in period_cells]
            date = window(periods)
            period_context = None
            if not date:
                # Restrict caption-wide dates to titles or introductions which
                # explicitly govern this grid; do not borrow a period from nearby prose.
                candidates = [
                    (i, t)
                    for i, t in before
                    if i == title_i
                    or re.search(r"\b(?:following table|table (?:below|that follows))\b", t, I)
                ]
                if table.caption:
                    candidates.append((None, v7.tidy("".join(table.caption))))
                for i, t in reversed(candidates):
                    if not v7.YEAR.search(t) or not DURATION.search(t):
                        continue
                    proposed = window([*periods, t])
                    if proposed:
                        date, period_context = proposed, i
                        if i is not None:
                            phrase = re.search(
                                r"\b(?:three months?|nine months?|six months?|twelve months?|quarter|year)\s+ended\s+[^.]{0,26}?\b(?:19|20)\d\d\b",
                                t,
                                I,
                            )
                            periods.append(phrase[0] if phrase else t)
                        else:
                            periods.append(t)
                        break
            # For an event on a row, an explicit annual year suffices even when
            # the issuer leaves the conventional full-year dates out of the header.
            if not date and anchor:
                year_headers = {y for c in period_cells for y in v7.YEAR.findall(c.text)}
                if (
                    len(year_headers) == 1
                    and "10-K" in rows[row.passage].get("source_kind", "")
                    and not any(DURATION.search(c.text) for c in period_cells)
                ):
                    date = (next(iter(year_headers)), "annual", 0, "year")
            if not date or (fiscal and int(date[0]) != fiscal):
                continue
            date_text = " ".join(dict.fromkeys(periods))
            source_note = None
            owner = None
            owner_cells = []
            if anchor:
                if anchor.col >= amount.col:
                    continue
                owner, owner_cells = segment_for_column(cols)
                if not owner:
                    continue
                label = anchor
                # Keep consolidation/portfolio scope in the owner and the original
                # caption; the loss measure itself applies to each column owner.
                measure = re.sub(
                    r"^consolidated\s+[\w &-]+?\s+(?=catastrophe losses?\b)", "", title, flags=I
                )
                link = "event_row_with_financial_title"
            else:
                candidates = [
                    c
                    for c in cells
                    if c.col < amount.col and v7.metric(c.text) and not DIFFERENCE.search(c.text)
                ]
                if len(candidates) != 1:
                    continue
                label = candidates[0]
                measure = label.text
                link = "event_note_after_table"
            unit = amount_unit(headers, label, amount, cells, cols, before)
            if not unit:
                continue
            scale, unit_cell, unit_i, unit_text, currency_cell, currency_i = unit
            if not anchor:
                source_note = note_for(label.text, notes, date, target, value * scale)
                if source_note is None:
                    continue
            src = rows[row.passage]
            tax_context = " ".join(
                c.text for c in cols if re.search(r"tax|reinsurance|gross|\bnet\b", c.text, I)
            )
            shared_context = " ".join(t for i, t in before if i == title_i)
            status, basis, tax, _ = v7.semantics(
                measure, " ".join([unit_text, tax_context, shared_context])
            )
            signed = value * scale
            signed = int(signed) if signed == int(signed) else float(signed)
            record = v7.v6.prior.v4.base_record(
                src, measure, basis, status, abs(signed), None, src["text"], "html_table"
            )
            segment = owner
            total = owner and owner.lower() in ("total", "consolidated")
            if total:
                match = re.match(r"Consolidated\s+(.+?)\s+(?:catastrophe|storm|weather|losses)", title, I)
                segment = ("Consolidated " + match[1]) if match else None
            entity = src["issuer"] + " — " + segment if segment else src["issuer"]
            source_cells = [label, amount, *period_cells, *owner_cells, *signs]
            if currency_cell:
                source_cells.append(currency_cell)
            if unit_cell:
                source_cells.append(unit_cell)
            indices = [table.rows[c.row].passage for c in source_cells]
            indices.extend(
                i
                for i in (title_i if anchor else None, source_note, unit_i, currency_i, period_context)
                if i is not None
            )
            # Keep the caption's explanatory lead and a matching note's table title.
            if anchor and title_i is not None:
                indices.extend(
                    i for i, t in before if i < title_i and re.search(r"\bfollowing table\b", t, I)
                )
            if source_note is not None:
                indices.extend(
                    i for i, t in before if len(t) < 120 and v7.metric(t) and not v7.USD.search(t)
                )
            item = lambda c: v7.provenance(table, c, rows)
            title_evidence = {
                "table": table.number,
                "caption": title,
                "passage_id": rows[title_i]["passage_id"] if title_i is not None else None,
            }
            event_evidence = (
                item(anchor)
                if anchor
                else {
                    "table": table.number,
                    "passage_id": rows[source_note]["passage_id"],
                    "text": rows[source_note]["text"],
                }
            )
            measure_evidence = title_evidence if anchor else item(label)
            unit_evidence = (
                item(unit_cell)["passage_id"]
                if unit_cell
                else rows[unit_i]["passage_id"]
                if unit_i is not None
                else src["passage_id"]
            )
            period_evidence = [item(c)["passage_id"] for c in period_cells]
            if period_context is not None:
                period_evidence.append(rows[period_context]["passage_id"])
            scope_evidence = [item(c)["passage_id"] for c in owner_cells]
            if title_i is not None and total:
                scope_evidence.append(rows[title_i]["passage_id"])
            record.update(
                issuer=entity,
                affected_entity=entity,
                segment=segment,
                entity_scope="consolidated_business_total"
                if total and segment
                else "named_segment_or_subsidiary"
                if segment
                else "reporting_group",
                recognition_period=date_text,
                reporting_or_recognition_period=date_text,
                reporting_period=filing,
                reporting_period_source=period_src,
                event_evidence=anchor.text if anchor else rows[source_note]["text"],
                signed_usd=signed,
                display_sign="negative" if signed < 0 else "positive" if signed > 0 else "zero",
                amount_text=literal,
                unit_scale=scale,
                currency="USD",
                tax_basis=tax,
                financial_role=measure,
                currency_evidence_passage=item(currency_cell)["passage_id"]
                if currency_cell
                else rows[currency_i]["passage_id"],
                unit_heading_passage=unit_evidence,
                evidence_passage_ids=list(dict.fromkeys(rows[i]["passage_id"] for i in indices)),
                table_orientation=link,
                observed_windows=[date_text],
            )
            record["table_observations"] = [
                dict(
                    amount_cell=item(amount),
                    metric_cell=measure_evidence,
                    event_cell=event_evidence,
                    period_cells=[item(c) for c in period_cells],
                    qualifier_cells=[item(c) for c in owner_cells],
                    sign_cells=[item(c) for c in signs],
                    unit_evidence=unit_text,
                    unit_cell=item(unit_cell) if unit_cell else None,
                    currency_cell=item(currency_cell) if currency_cell else None,
                    window=date_text,
                    field_evidence={
                        "event": event_evidence["passage_id"],
                        "measure_and_status": measure_evidence["passage_id"],
                        "owner": list(dict.fromkeys(scope_evidence)),
                        "period": list(dict.fromkeys(period_evidence)),
                        "unit": unit_evidence,
                        "tax_and_reinsurance_basis": list(
                            dict.fromkeys(
                                pid
                                for pid in [
                                    unit_evidence,
                                    measure_evidence["passage_id"],
                                    *(
                                        item(c)["passage_id"]
                                        for c in cols
                                        if re.search(r"tax|reinsurance|gross|\bnet\b", c.text, I)
                                    ),
                                ]
                                if pid
                            )
                        )
                        if tax or basis
                        else [],
                    },
                )
            ]
            # Equal values in distinct businesses or distinct yearly periods stay separate.
            yield (table.number, row.passage, entity, measure, basis, signed, date[:3]), record


def table_records(rows, body):
    filing, fiscal, period_src = v7.v6.prior.filing_period(rows)
    found = {}
    for table in v7.read_tables(body, rows):
        for identity, r in attributed_cells(table, rows, filing, fiscal, period_src):
            if identity not in found:
                found[identity] = r
                continue
            prior = found[identity]
            prior["table_observations"].extend(r["table_observations"])
            for k in ("observed_windows", "evidence_passage_ids"):
                prior[k] = list(dict.fromkeys(prior[k] + r[k]))
            prior["reporting_or_recognition_period"] = " / ".join(prior["observed_windows"])
    return list(found.values())


def extract_filing(rows, body):
    previous = v7.extract_filing(rows, body)
    for r in previous:
        # The subject can be a catastrophe while the monetary object is explicitly a reinsurance expense.
        if (
            r.get("measure") == "claims_losses"
            and r.get("source_channel") == "single_cause_prose"
            and r.get("amount_text")
        ):
            suffix = r.get("evidence", "").partition(r["amount_text"])[2]
            if (
                re.match(r"\s+(?:of |in )?(?:expenses?|costs?)\b", suffix, I)
                and re.search(r"\b(?:accelerat\w*|reinstatement)\b", suffix, I)
                and re.search(r"\breinsurance\b", suffix, I)
            ):
                r["measure"] = "reinsurance acceleration or reinstatement expense"
                r["financial_role"] = r["measure"]
    existing = {
        (r["doc_id"], o["amount_cell"]["table"], o["amount_cell"]["row"], o["amount_cell"]["column"])
        for r in previous
        for o in r.get("table_observations", [])
    }
    additional = []
    for r in table_records(rows, body):
        a = r["table_observations"][0]["amount_cell"]
        if (r["doc_id"], a["table"], a["row"], a["column"]) not in existing:
            additional.append(r)
    return previous + additional


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("primary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--event")
    args = parser.parse_args()
    groups = defaultdict(list)
    with args.input.open(encoding="utf-8-sig") as source:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            if args.event:
                row["event"] = args.event
            groups[row["doc_id"], row["event"]].append(row)
    records = []
    for (doc, _), rows in groups.items():
        records.extend(extract_filing(rows, (args.primary / (doc + ".htm")).read_bytes()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=args.output.parent, delete=False
    ) as tmp:
        json.dump(records, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
    os.replace(tmp.name, args.output)


if __name__ == "__main__":
    main()
