"""Resolve financial table assertions from their event, metric, owner and accounting window."""

import argparse
from collections import defaultdict
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("disclosure_v8", ROOT / "v8/extract.py")
v8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v8)
v7 = v8.v7
I = re.I
SCALE = re.compile(r"\b(thousands?|millions?|billions?)\b", I)
INTRO = re.compile(
    r"(?:as follows|(?:following|below)\b.{0,70}\b(?:table|losses|analysis|results)|"
    r"\b(?:following table|amounts? (?:are|shown|expressed)|table (?:below|shows|presents)))",
    I,
)
TAX = re.compile(r"\b(?:pre[- ]?tax|after[- ]tax|before tax|net of tax)", I)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
AMOUNT_WORDS = re.compile(
    r"(?:\bin\s+(?:(?:u\.?s\.?\s+)?dollars?\s+in\s+)?|"
    r"\b(?:usd|dollars?)\s+(?:in\s+)?|\$\s*(?:in\s+)?)"
    r"(thousands?|millions?|billions?)\b",
    I,
)
MEASURE = re.compile(
    r"\b(?:premiums?|loss(?:es)?|expenses?|acquisition costs?|income|"
    r"recover(?:y|ies|ables?)|claims?|reserves?|earnings|profits?|commissions?)\b",
    I,
)
DISALLOWED = re.compile(
    r"\b(?:industry|market[- ]wide|economic damages?|number of|per share|"
    r"potential exposure|coverage limit|attachment point|change|variance|ratio|percent)\b|%",
    I,
)
GENERAL = re.compile(
    r"^(?:named|large|significant)?\s*(?:catastrophic loss|catastrophe events?|events?)$", I
)
KNOWN_OWNER = re.compile(
    r"\b(?:insurance|reinsurance|services|products|operations|commercial|personal|"
    r"lines|segment|division|group|consolidated|total|corporate|property|casualty|other)\b",
    I,
)


@dataclass
class Evidence:
    text: str
    index: int | None
    cell: object = None
    caption: bool = False


def source(table, cell):
    return Evidence(cell.text, table.rows[cell.row].passage, cell)


def metric(text):
    return (
        0 < len(text) <= 160
        and MEASURE.search(text)
        and not DISALLOWED.search(text)
        and not GENERAL.fullmatch(text.rstrip(":"))
        and not v7.UNIT.search(text)
        and not re.search(r"^total (?:catastrophes|storms|events)$", text, I)
    )


def unit_scale(text):
    if v7.FX.search(text) or len({m[1].lower().rstrip("s") for m in SCALE.finditer(text)}) > 1:
        return None
    match = AMOUNT_WORDS.search(text)
    if not match and re.fullmatch(
        r"\(?\s*(?:USD|US\$|\$)?\s*(?:thousands?|millions?|billions?)\s*\)?", text, I
    ):
        match = SCALE.search(text)
    return v7.SCALES[match[1].lower().rstrip("s")] if match else None


def neighboring(rows, start, step, count=5):
    out = []
    for idx in range(start + step, start + step * (count + 1), step):
        if not 0 <= idx < len(rows) or rows[idx]["kind"] == "table_row":
            break
        text = rows[idx]["text"]
        if text.isdigit():
            continue
        out.append(Evidence(text, idx))
    return out


def is_intro(text):
    return bool(INTRO.search(text) or re.search(r"include(?:d)? the following\s+\w+\s*:$", text, I))


def is_unit_note(text):
    return bool(
        unit_scale(text)
        and (
            is_intro(text)
            or re.match(
                r"^(?:\(?\s*(?:amounts?|all figures|dollars?|units?|in (?:thousands|millions|billions)|\$))",
                text,
                I,
            )
        )
    )


def units(column, header_rows, pre, post, money_symbols):
    """Prefer column-specific scale; table-wide centered unit rows can span only one year."""
    local = [c for c in column if unit_scale(c.text)]
    band = [items[0] for items in header_rows if len(items) == 1 and unit_scale(items[0].text)]
    notes = [n for n in pre[:1] + post[:1] if is_unit_note(n.text) or (n.caption and unit_scale(n.text))]
    inputs = local or band or notes
    if not inputs or len({unit_scale(n.text) for n in inputs}) != 1:
        return None
    if len({unit_scale(n.text) for n in band + notes}) > 1:
        return None
    fx = [
        h
        for group in header_rows
        for h in group
        if v7.FX.search(h.text) and (SCALE.search(h.text) or h in column)
    ]
    if fx or any(v7.FX.search(n.text) and SCALE.search(n.text) for n in pre[:1] + post[:1]):
        return None
    chosen = inputs[-1]
    currency = next(
        (
            n
            for n in [*inputs, *notes, *money_symbols]
            if v7.USD.search(n.text) or re.search(r"\bdollars? in\b", n.text, I)
        ),
        None,
    )
    if currency is None:
        return None
    return unit_scale(chosen.text), chosen, currency


def period(column, headers, pre, filing):
    dated = [c for c in column if v7.period_header(c.text)]
    # A centered common year can be used when all the periods in the header band agree.
    all_dated = [c for group in headers for c in group if v7.period_header(c.text)]
    if not any(YEAR.search(c.text) for c in dated):
        if len({y for c in all_dated for y in YEAR.findall(c.text)}) == 1:
            dated = all_dated
        elif (
            pre and (pre[0].caption or is_intro(pre[0].text)) and len(set(YEAR.findall(pre[0].text))) == 1
        ):
            dated = [pre[0]]
    years = {y for c in dated for y in YEAR.findall(c.text)}
    if len(years) != 1:
        return None
    y = next(iter(years))
    if filing and y not in filing and re.search(r"\d{4}", filing):
        return None
    # Mixed quarter/year-to-date columns must retain their own precise windows.
    dates = [c.text for c in dated]
    window = " ".join(dict.fromkeys(dates))
    return window, dated, y


def printed_amount(cell, cells):
    literal, value, signs = v7.printed_amount(cell, cells)
    if value is not None:
        return literal, value, signs
    # Some exporters put the opening parenthesis, currency, magnitude and
    # closing parenthesis in four distinct cells. Require exact adjacency.
    currency = next(
        (c for c in cells if c.col + c.width == cell.col and c.text in ("$", "US$", "USD")), None
    )
    if currency and re.fullmatch(r"\d[\d,.]*", cell.text):
        opening = next((c for c in cells if c.col + c.width == currency.col and c.text == "("), None)
        closing = next((c for c in cells if c.col == cell.col + cell.width and c.text == ")"), None)
        if opening and closing:
            literal = "(" + cell.text + ")"
            return literal, v7.money(literal), [opening, currency, closing]
    return literal, value, signs


def owner_path(column):
    members = [
        c
        for c in column
        if len(c.text) < 80
        and not v7.period_header(c.text)
        and not unit_scale(c.text)
        and not metric(c.text)
        and not re.search(r"[%$():]|^[-—–]$", c.text)
    ]
    name = " ".join(c.text for c in members).strip()
    if not name or not KNOWN_OWNER.search(name):
        return None, []
    if re.fullmatch(r"(?:company |group )?(?:total|consolidated|combined)", name, I):
        return "", members
    return re.sub(r"\s+segment$", "", name, flags=I), members


def owner_from_title(title):
    found = re.match(
        r"^(?P<line>[A-Za-z][A-Za-z &/-]{2,55}?)\s+(?:losses|claims|premiums|earnings)\b", title, I
    )
    if (
        found
        and KNOWN_OWNER.search(found["line"])
        and not re.search(r"\b(?:net|gross|total|incurred|catastrophe|consolidated)\b", found["line"], I)
    ):
        return found["line"]
    return None


def field_values(label, pre, post, year, target, shared_title):
    measure = label.text.rstrip(":").strip()
    status, basis, tax, _ = v7.semantics(measure, "")
    evidence = []
    if re.search(r"\brecoverable\b", measure, I):
        basis, status = "recoverable", "recognized recoverable"
    elif re.search(r"\bnet premiums?\b", measure, I):
        basis = "net"
    elif re.search(r"\bnet losses\b", measure, I):
        basis, status = "net", "incurred"
    elif re.search(r"\bnet income\b", measure, I):
        basis = "net income impact"
    if re.search(r"\bgross losses\b", measure, I):
        est = next(
            (
                n
                for n in pre
                if re.search(r"\bestimated losses incurred\b", n.text, I)
                and re.search(r"\b" + re.escape(target) + r"\b", n.text, I)
                and year in n.text
            ),
            None,
        )
        if est:
            status = "estimated losses incurred"
            evidence.append(est)
    if (
        shared_title
        and pre
        and re.search(r"\blosses and loss adjustment expenses\b", pre[0].text, I)
        and "loss" in measure.lower()
    ):
        measure = re.sub(r"\blosses\s*$", "losses and loss adjustment expenses", measure, flags=I)
        evidence.append(pre[0])
        status = "incurred"
    if "loss" in measure.lower():
        for n in post:
            sentences = re.split(r"(?<=[.!?])\s+", n.text)
            if any(
                re.search(
                    r"losses(?: and loss adjustment expenses)?\s+for\s+"
                    + year
                    + r"\s+(?:are|were)\s+(?:stated|reported)\s+(?:after (?:the )?deduct(?:ion|ing)|net of)"
                    r".{0,90}\breinsurance recover(?:y|ies)\b",
                    s,
                    I,
                )
                for s in sentences
            ):
                basis = "net of reinsurance recoveries"
                evidence.append(n)
                break
    return measure, status, basis, tax, evidence


def build_record(
    table,
    rows,
    row,
    amount,
    signed,
    text,
    sign_cells,
    anchor,
    metric_label,
    owner,
    owner_cells,
    window,
    duration,
    year,
    unit,
    pre,
    post,
    shared_title,
    filing,
    period_src,
):
    scale, unit_evidence, currency = unit
    value = signed * scale
    usd = int(value) if value == int(value) else float(value)
    measure, status, basis, tax, extra = field_values(
        metric_label, pre, post, year, rows[0]["event"], shared_title
    )
    src = rows[row.passage]
    record = v7.v6.prior.v4.base_record(
        src, measure, basis, status, abs(usd), None, src["text"], "html_table"
    )
    entity = src["issuer"] + " — " + owner if owner else src["issuer"]
    sign_evidence = [source(table, s) for s in sign_cells]
    evidence = [
        anchor,
        metric_label,
        *owner_cells,
        *duration,
        unit_evidence,
        currency,
        source(table, amount),
        *sign_evidence,
        *extra,
    ]

    def location(n):
        if n.cell is not None:
            return v7.provenance(table, n.cell, rows)
        result = dict(
            table=table.number,
            passage_id=rows[n.index]["passage_id"] if n.index is not None else None,
            text=n.text,
        )
        if n.caption:
            result["element"] = "caption"
        return result

    observation = dict(
        amount_cell=v7.provenance(table, amount, rows),
        event_cell=location(anchor),
        metric_cell=location(metric_label),
        qualifier_cells=[location(c) for c in owner_cells],
        period_cells=[location(c) for c in duration],
        sign_cells=[location(c) for c in sign_evidence],
        unit_evidence=unit_evidence.text,
        unit_cell=location(unit_evidence),
        currency_cell=location(currency),
        accounting_context=[location(c) for c in extra],
        window=window,
    )
    record.update(
        issuer=entity,
        reporting_issuer=src["issuer"],
        affected_entity=entity,
        segment=owner or None,
        entity_scope="named_segment_or_subsidiary" if owner else "reporting_group",
        currency="USD",
        unit_scale=scale,
        signed_usd=usd,
        amount_text=text,
        display_sign="negative" if signed < 0 else "positive" if signed > 0 else "zero",
        event_evidence=anchor.text,
        tax_basis=tax,
        financial_role=measure,
        reporting_period=filing,
        reporting_period_source=period_src,
        recognition_period=window,
        reporting_or_recognition_period=window,
        unit_heading_passage=location(unit_evidence)["passage_id"],
        currency_evidence_passage=location(currency)["passage_id"],
        observed_windows=[window],
        table_orientation="named_event_table",
        evidence_passage_ids=list(
            dict.fromkeys(rows[e.index]["passage_id"] for e in evidence if e.index is not None)
        ),
        table_observations=[observation],
    )
    return record


def records_for_table(table, rows, filing, period_src):
    data_rows = [r for r in table.rows if r.passage is not None]
    if not data_rows:
        return
    target = rows[0]["event"]
    pre = neighboring(rows, data_rows[0].passage, -1)
    if table.caption:
        caption_text = v7.tidy("".join(table.caption))
        prior = next((n.index for n in pre if n.text == caption_text), None)
        pre.insert(0, Evidence(caption_text, prior, caption=True))
    post = neighboring(rows, data_rows[-1].passage, 1, 2)
    if (
        pre
        and (is_intro(pre[0].text) or len(pre[0].text) < 120)
        and re.search(
            r"\b(?:industry[- ]wide|market[- ]wide|(?:insurance |insured )?industry (?:catastrophe |insured )?loss(?:es)?|"
            r"loss(?:es)? (?:for|of|across) the (?:insurance )?industry)\b",
            pre[0].text,
            I,
        )
    ):
        return
    event_pattern = re.compile(r"\b" + re.escape(target) + r"\b", I)
    near_caption = next(
        (
            n
            for n in pre[:1]
            if (n.caption or is_intro(n.text))
            and event_pattern.search(n.text)
            and v7.v6.prior.event_names(n.text) == {target.casefold()}
            and not re.search(
                r"\b(?:including|industry|other storms|together with|and other|primarily)\b", n.text, I
            )
            and not re.search(
                r"\b" + re.escape(target) + r"\s*(?:,\s*(?=[A-Z])|\s+(?:and|or|plus)\s+(?=[A-Z]))", n.text
            )
        ),
        None,
    )
    if not near_caption and not any(event_pattern.search(rows[r.passage]["text"]) for r in data_rows):
        return
    headers = []
    section = None
    started = False
    money_symbols = [
        source(table, c) for r in data_rows for c in r.cells if c.text in ("$", "US$", "USD")
    ]
    for row in data_rows:
        cells = [c for c in row.cells if c.text]
        parsed = [(c, *printed_amount(c, cells)) for c in cells]
        amounts = [(c, literal, n, sc) for c, literal, n, sc in parsed if n is not None]
        anchor_cell = next((c for c in cells if v7.named(c.text, target)), None)
        years_only = bool(amounts) and all(YEAR.fullmatch(literal) for c, literal, _, _ in amounts)
        header = [source(table, c) for c in cells]
        event_column_known = any(v7.named(h.text, target) for group in headers for h in group)
        years_as_amounts = event_column_known and any(metric(c.text) for c in cells)
        if not amounts or (years_only and not anchor_cell and not years_as_amounts):
            # A date heading after data starts a new accounting block.
            if (
                started
                and len(cells) == 1
                and v7.period_header(cells[0].text)
                and YEAR.search(cells[0].text)
            ):
                headers = []
                section = None
                started = False
            if (
                len(cells) == 1
                and cells[0].col == 0
                and metric(cells[0].text)
                and not v7.period_header(cells[0].text)
            ):
                section = header[0]
            elif (
                len(cells) == 1
                and cells[0].col == 0
                and not anchor_cell
                and not v7.period_header(cells[0].text)
                and not unit_scale(cells[0].text)
            ):
                section = None
            if not started:
                headers.append(header)
            continue
        started = True
        flattened = [c for group in headers for c in group]
        dated_groups = [
            group
            for group in headers
            if sum(bool(YEAR.search(c.text) and v7.period_header(c.text)) for c in group) >= 2
        ]
        bands = dated_groups[-1] if dated_groups else []
        shared = next(
            (
                group[0]
                for group in headers
                if len(group) == 1
                and metric(group[0].text)
                and not v7.period_header(group[0].text)
                and bands
                and group[0].cell.row < bands[0].cell.row
            ),
            None,
        )
        for amount, literal, n, signs in amounts:
            column = [h for h in flattened if h.cell.covers(amount.col)]
            if any(
                len(group) == 1
                and re.search(r"\b(?:industry|market.wide|economic damage)\b", group[0].text, I)
                for group in headers
            ):
                continue
            if any(DISALLOWED.search(h.text) for h in column if not unit_scale(h.text)):
                continue
            if any(c.text == "%" and abs(c.col - amount.col) <= amount.width for c in cells):
                continue
            dated = period(column, headers, pre, filing)
            if not dated:
                continue
            window, date_evidence, year = dated
            owner = None
            owner_cells = []
            shared_title = False
            if anchor_cell:
                if anchor_cell.col >= amount.col:
                    continue
                if bands:
                    band = next((h for h in bands if h.cell.covers(amount.col)), None)
                    if band and not band.cell.covers(anchor_cell.col):
                        continue
                if any(
                    c.col > anchor_cell.col
                    and c.col < amount.col
                    and re.search(r"[A-Za-z]{2}", c.text)
                    and not v7.USD.fullmatch(c.text)
                    for c in cells
                ):
                    continue
                if not bands and any(
                    v7.v6.prior.event_names(c.text) - {target.casefold()} for c in cells
                ):
                    continue
                anchored = source(table, anchor_cell)
                labels = [h for h in column if metric(h.text) and h.cell.col > anchor_cell.col]
                if labels:
                    label = labels[-1]
                    if shared is label:
                        shared_title = True
                        owner = owner_from_title(label.text)
                        if owner:
                            owner_cells = [label]
                elif section and section.cell.col <= anchor_cell.col:
                    owner, owner_cells = owner_path(column)
                    if owner is None:
                        continue
                    label = section
                elif shared:
                    label = shared
                    owner = owner_from_title(shared.text)
                    if owner:
                        owner_cells = [shared]
                    shared_title = True
                else:
                    continue
            else:
                anchored = next((h for h in column if v7.named(h.text, target)), near_caption)
                labels = [c for c in cells if c.col < amount.col and metric(c.text)]
                if not anchored or not labels:
                    continue
                if any(
                    v7.v6.prior.event_names(h.text) - {target.casefold()} or v7.AGG.search(h.text)
                    for h in column
                    if h is not anchored and not unit_scale(h.text)
                ):
                    continue
                label = source(table, labels[-1])
            unit = units(column, headers, pre, post, money_symbols + [source(table, amount)])
            if not unit:
                continue
            yield build_record(
                table,
                rows,
                row,
                amount,
                n,
                literal,
                signs,
                anchored,
                label,
                owner,
                owner_cells,
                window,
                date_evidence,
                year,
                unit,
                pre,
                post,
                shared_title,
                filing,
                period_src,
            )


def narrative_records(previous, rows):
    """Check the role and attribution of earlier prose candidates against their own passage."""
    originals = {r["passage_id"]: r["text"] for r in rows}
    target = rows[0]["event"]
    potential = set()
    for r in previous:
        if r.get("review") or r.get("table_observations"):
            yield r
            continue
        evidence = r.get("evidence", "")
        literal = r.get("amount_text", "")
        if not literal or literal not in evidence:
            yield r
            continue
        before, _, after = evidence.partition(literal)
        full = originals.get(r["passage_id"], evidence)
        # A quoted external insurance market estimate is not the issuer's incurred loss.
        if re.search(r"estimate of the insured loss.{0,100}published by\b", before, I) and re.search(
            r"industry|market|threshold", full, I
        ):
            continue
        # Reject a jointly allocated sum; do not penalize a sentence merely for
        # naming other storms with their own separate monetary assertions.
        clustered = re.search(
            r"(?i:\bfrom (?:hurricanes?|storms?)\s+)([A-Z][a-z]+(?:,\s*[A-Z][a-z]+)*(?:,?\s+and\s+[A-Z][a-z]+))",
            after[:160],
        )
        if (
            clustered
            and target.casefold() in [x.casefold() for x in re.findall(r"[A-Z][a-z]+", clustered[1])]
        ) or re.search(r"\bincurred a combined\s*$", before, I):
            continue
        if re.search(r"potential recovery of\s*$", before, I) and re.search(
            r"not accounted for as a reinsurance contract but as a derivative contract", full, I
        ):
            key = (r["passage_id"], r["low_usd"], r["high_usd"])
            if key in potential:
                continue
            potential.add(key)
            r.update(
                measure="potential derivative recovery",
                financial_role="potential derivative recovery",
                basis=None,
                status="potential recovery recognized",
                evidence=full,
            )
        elif r["measure"] == "insurance_recovery" and re.search(
            r"estimated losses incurred,?\s+net of (?:reinsurance )?recoveries,?\s+of\s*$", before, I
        ):
            first = re.search(r"(?i:\b(?:hurricanes?|storms?))\s+([A-Z][a-z]+)\b", before)
            if first and first[1].casefold() == target.casefold() and "respectively" in after.lower():
                r.update(
                    measure="estimated losses incurred",
                    financial_role="estimated losses incurred net of reinsurance",
                    basis="net of reinsurance recoveries",
                    status="estimated losses incurred",
                )
            else:
                r.update(
                    review=True,
                    review_reasons=[
                        "Confirm assignment of the loss net of recoveries to the named event."
                    ],
                )
        yield r


def extract_filing(rows, body):
    previous = list(narrative_records(v8.extract_filing(rows, body), rows))
    filing, _, period_src = v7.v6.prior.filing_period(rows)
    existing = {
        (o["amount_cell"]["table"], o["amount_cell"]["row"], o["amount_cell"]["column"])
        for r in previous
        for o in r.get("table_observations", [])
    }
    added = []
    for table in v7.read_tables(body, rows):
        for record in records_for_table(table, rows, filing, period_src):
            a = record["table_observations"][0]["amount_cell"]
            if (a["table"], a["row"], a["column"]) not in existing:
                added.append(record)
    # Legacy row-level heuristics may label a premium or other adjustment as a loss.
    # Replace their record only when its numeric anchor is resolved in the very same row.
    resolved = {(r["passage_id"], r["low_usd"], r["high_usd"]) for r in added}
    kept = [
        r
        for r in previous
        if not (
            r.get("source_channel") == "single_value_table"
            and (r["passage_id"], r["low_usd"], r["high_usd"]) in resolved
        )
    ]
    return kept + added


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
            groups[row["doc_id"], row["event"]].append(row)
    records = []
    for (doc, _), rows in groups.items():
        records.extend(extract_filing(rows, (args.primary / (doc + ".htm")).read_bytes()))
    args.output.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as out:
        json.dump(records, out, indent=2, ensure_ascii=False)
        out.write("\n")
    os.replace(out.name, args.output)


if __name__ == "__main__":
    main()
