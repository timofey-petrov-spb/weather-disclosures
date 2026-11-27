"""Read named storm amounts from SEC prose, inline facts and original HTML tables.

Usage: python v7/extract.py INPUTS_JSONL PRIMARY_HTML_DIRECTORY OUTPUT_JSON
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
spec = importlib.util.spec_from_file_location('disclosure_v6', ROOT / 'v6' / 'extract.py')
v6 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v6)
from tables import read_tables, tidy

I = re.I
FINANCIAL = re.compile(r'\b(?:loss(?:es)?|claims?|costs?|expenses?|premiums?|recover(?:ies|y|ables?)|commissions?|'
                       r'reserves?|impairments?|income|earnings|noncontrolling interest|underwriting|payments?|profits?)\b', I)
BLOCKED = re.compile(r'%|percent|ratios?|per share|per policy|number of|count of|industry|market.wide|economic losses|'
                     r'policy limits?|coverage limits?|attachment points?|exposure in force|basis points?|loss adjustment factors?', I)
UNIT = re.compile(r'\b(?:in\s+|amounts?\s+(?:in\s+)?|expressed in\s+|\$\s*(?:in\s+)?|USD\s+)'
                  r'(?:(?:U\.?S\.? )?dollars?\s+in\s+)?(billions?|millions?|thousands?|dollars?)\b', I)
FX = re.compile(r'€|£|¥|\b(?:EUR|GBP|CAD|AUD|HKD|JPY|CNY|NZD|CHF|SGD)\b|(?:Canadian|Australian|Singapore|Hong Kong) dollars|[CA]\$', I)
USD = re.compile(r'\$|\bUSD\b|\b(?:U\.?S\.?|United States) dollars?\b', I)
NUM = re.compile(r'(?P<open>\()?\s*(?P<minus>[-−])?\s*(?:(?:US)?\$|USD\s+)?\s*(?P<n>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*(?P<close>\))?$', I)
YEAR = re.compile(r'\b(?:19|20)\d{2}\b')
DATE = re.compile(r'January|February|March|April|May|June|July|August|September|October|November|December', I)
WINDOW = re.compile(r'\b(?:months?|weeks?|years?|quarter|as of|ended)\b', I)
AGG = re.compile(r'\b(?:other|aggregate|all events?|all storms?|combined storms?|including|total (?:catastrophe|storm|weather)|various)\b', I)
TAGS = re.compile(r'\(\s*\d{1,2}\s*\)\s*$')
SCALES = {'dollar': 1, 'thousand': 1000, 'million': 10**6, 'billion': 10**9}


def named(text, target):
    """Require a local, single named event; reject coordinated or aggregate headers."""
    clean = TAGS.sub('', text).strip()
    if not re.search(r'\b' + re.escape(target) + r'\b', clean, I) or AGG.search(clean):
        return False
    if re.search(r'\b(?:and|or|plus|including|together with)\b|[&/+]', clean, I):
        return False
    return (clean.casefold() == target.casefold() or
            v6.prior.event_names(clean) == {target.casefold()} or
            bool(re.fullmatch(r'(?:\d+\s*[-–—]\s*)?(?:' + v6.PERIL + r')\s+' + re.escape(target), clean, I)))


def money(text):
    m = NUM.fullmatch(text.strip())
    if not m or bool(m['open']) != bool(m['close']) or (m['open'] and m['minus']):
        return None
    value = Decimal(m['n'].replace(',', ''))
    return -value if m['minus'] or m['open'] else value


def metric(text):
    return bool(FINANCIAL.search(text) and not BLOCKED.search(text) and len(text) < 260)


def period_header(text):
    if re.fullmatch(r'(?:19|20)\d\d', text):
        return True
    return bool((DATE.search(text) or WINDOW.search(text)) and not FINANCIAL.search(text) and len(text) < 100)


def semantics(label, shared):
    text = label.lower()
    tax = v6.tax(label) or v6.tax(shared)
    if 'commission' in text: status = 'reported commission'
    elif 'noncontrolling' in text: status = 'reported allocation'
    elif 'impact' in text: status = 'reported impact'
    elif 'ultimate' in text: status = 'ultimate estimate'
    elif re.search(r'estimat|expected|project|forecast', text): status = 'estimate'
    elif 'incurred' in text: status = 'incurred'
    elif 'earned' in text: status = 'earned'
    elif 'paid' in text: status = 'paid'
    else: status = 'reported'
    segment = re.search(r'(?:\bon\s+|\bfor\s+|\bof\s+)(.+?)\s+segment\b', label, I)
    ownership = ' '.join(segment[1].split()) + ' segment' if segment else None
    if not ownership and re.search(r'common shareholders', text):
        ownership = 'common shareholders'
    if 'ceded' in text: basis = 'ceded'
    elif 'assumed' in text: basis = 'assumed'
    elif re.search(r'\bgross\b',text+' '+shared,I): basis = 'gross'
    elif re.search(r'net (?:claims|loss|of reinsurance)|retained', text+' '+shared, I): basis = 'net of reinsurance'
    elif 'net' in text: basis = 'net result'
    elif re.search(r'\bnet\b',shared,I): basis = 'net'
    else: basis = None
    return status, basis, tax, ownership


def defined_tax(rows):
    """Find explicit bridge definitions naming the taxable result AND its components."""
    definitions = []
    for row in rows:
        for sentence in re.split(r'(?<=[.!?])\s+', row['text']):
            if (re.search(r'\bboth before (?:consideration of )?(?:any )?(?:related )?income tax', sentence, I)
                    and re.search(r'\bis the sum of\b', sentence, I)):
                definitions.append((sentence.casefold(), row['passage_id']))
    return definitions


def financial_role(label, signed, basis):
    """Keep the issuer's component label and sign separate from absolute size."""
    if re.search(r'commissions?', label, I):
        return 'lost profit commission' if signed < 0 else 'earned profit commission'
    if re.search(r'noncontrolling interest', label, I):
        return 'noncontrolling-interest allocation'
    if re.search(r'common shareholders?', label, I):
        return 'effect attributable to common shareholders'
    if re.search(r'underwriting result', label, I):
        return 'segment underwriting result' if re.search(r'\bsegment\b', label, I) else 'consolidated underwriting result'
    if re.search(r'premium', label, I):
        return ' '.join(v for v in (basis, 'premium') if v)
    return label


def cover_end(rows):
    for i, row in enumerate(rows[:100]):
        m = v6.prior.COVER.search(' '.join(r['text'] for r in rows[i:i+2]))
        if m:
            return (m[2].casefold(), int(m[3]))
    return None


def reporting_window(text):
    m = re.search(r'('+DATE.pattern+r')\s+(\d{1,2})\b',text,I)
    return (m[1].casefold(), int(m[2])) if m else None


def printed_amount(amount, cells):
    """Rendering cells occasionally put an accounting sign in the adjacent cell."""
    text = amount.text
    before = next((c for c in cells if c.col+c.width==amount.col and c.text in {'(', '-', '−', '$(', '($'}),None)
    after = next((c for c in cells if c.col==amount.col+amount.width and c.text==')'),None)
    if before: text = before.text.replace('$(', '($') + text
    if after: text += ')'
    return text, money(text), [c for c in (before,after) if c]


def provenance(table, cell, rows):
    idx = table.rows[cell.row].passage
    return {'table': table.number, 'row': cell.row+1, 'column': cell.col+1,
            'rowspan': cell.height, 'colspan': cell.width, 'text': cell.text,
            'passage_id': rows[idx]['passage_id'] if idx is not None else None}


def active_units(above, label, body, row_cells, columns, before):
    # Cell and column units take precedence over a shared stub or caption.
    # Reject a column expressed as a percentage even if other columns are dollars.
    if any(BLOCKED.search(c.text) for c in columns if c in above and not UNIT.search(c.text)):
        return None
    local = [c for c in [label, *columns] if UNIT.search(c.text) and not ('except' in c.text.lower() and '%' in label.text)]
    global_units = [c for c in above if UNIT.search(c.text) and (c.col < body.col or c.covers(body.col))]
    for candidates in (local, global_units):
        if candidates:
            found = candidates[-1]
            return SCALES[UNIT.search(found.text)[1].lower().rstrip('s')], found, None
    for index, text in reversed(before):
        found = UNIT.search(text)
        if found and (re.search(r'\b(?:table|amounts?|figures|data)\b',text,I) or len(text)<85):
            return SCALES[found[1].lower().rstrip('s')], None, index
    if USD.search(body.text) or any(c.text in {'$', 'USD', 'US$'} and c.col+ c.width == body.col for c in row_cells):
        return 1, None, None
    return None


def governing_rows(rows, start):
    result = []
    for i in range(start-1, max(-1,start-5), -1):
        if rows[i]['kind']=='table_row':
            break
        result.append((i, rows[i]['text']))
    return list(reversed(result))


def values_for_table(table, rows, filing, fiscal, quarter, period_src, end, definitions):
    target = rows[0]['event']
    visible = [(r,r.passage) for r in table.rows if r.passage is not None]
    if not visible:
        return
    pre = governing_rows(rows, visible[0][1])
    caption = tidy(''.join(table.caption))
    caption_scope = named(caption, target)
    if not caption_scope and pre:
        i, intro = pre[-1]
        # Bind only an actual title or an explicit introduction to this table.
        if (len(intro) <= 220 and named(intro,target) and
                (re.fullmatch(v6.PERIL+r'\s+'+re.escape(target),intro,I) or
                 re.search(r'\b(?:following table|table below)\b',intro,I))):
            caption, caption_scope, table.caption_passage = intro, True, i
    if not caption_scope and not any(re.search(r'\b'+re.escape(target)+r'\b',rows[p]['text'],I) for _,p in visible):
        return
    if caption_scope and not table.caption_passage:
        table.caption_passage = next((i for i,t in pre if caption in t), None)
    if FX.search(caption):
        return
    if any(FX.search(t) and (UNIT.search(t) or re.search(r'\b(?:shown|presented|expressed|reported)\b',t,I)) for _,t in pre):
        return
    table_currency = next((c for row,_ in visible for c in row.cells if USD.search(c.text) and not FX.search(c.text)),None)
    all_header = []
    for row,p in visible:
        cells = [c for c in row.cells if c.text]
        if not cells:
            continue
        event_row = next((c for c in cells if named(c.text,target)),None)
        numbers = [(c,*printed_amount(c,cells)) for c in cells]
        # A monetary 2,022 (or 2022) is legitimate, even though a year heading is not money.
        data = [(c,literal,n,signs) for c,literal,n,signs in numbers if n is not None]
        has_label = any(metric(c.text) and money(c.text) is None and not UNIT.search(c.text) for c in cells)
        years_only = bool(data) and all(re.fullmatch(r'(?:19|20)\d\d',literal) for _,literal,_,_ in data)
        year_heading = years_only and not ((event_row and not any(named(c.text,target) for c in all_header)
                                            and any(metric(c.text) and not UNIT.search(c.text) for c in all_header))
                                           or (has_label and any(named(c.text,target) for c in all_header)))
        if (not event_row and not year_heading and any(FINANCIAL.search(c.text) for c in cells)
                and (not has_label and data or not data and any(re.fullmatch(r'[-−(]?\d[\d,.]*\s*%[)]?|[—–-]|n/a',c.text,I) for c in cells))):
            # A rejected observation is never a governing header for subsequent rows.
            continue
        if not data or year_heading or (not event_row and not has_label):
            # A different catastrophe header can replace an earlier one mid-table.
            if any(v6.prior.event_names(c.text) or named(c.text,target) for c in cells):
                all_header = [c for c in all_header if not v6.prior.event_names(c.text) and not named(c.text,target)]
            all_header.extend(cells)
            continue
        if event_row and any(c.text != event_row.text and v6.prior.event_names(c.text) for c in cells):
            continue
        for amount, literal, val, signs in data:
            columns = [c for c in all_header if c.covers(amount.col)]
            row_left = [c for c in cells if c.col < amount.col and metric(c.text) and money(c.text) is None]
            if event_row:
                if event_row.col >= amount.col: continue
                anchor = event_row
                labels = [c for c in columns if metric(c.text) and not UNIT.search(c.text) and not named(c.text,target)]
                if not labels: continue
                label = labels[-1]
                orientation = 'event_row'
                paths = columns
            else:
                possible = [c for c in columns if named(c.text,target)]
                if not possible and not caption_scope: continue
                if not row_left: continue
                anchor = possible[-1] if possible else None
                if not anchor and any(v6.prior.event_names(c.text) or AGG.search(c.text) for c in columns):
                    continue
                label = row_left[-1]
                if any(BLOCKED.search(c.text) for c in cells if c.col <= label.col): continue
                orientation = 'event_column' if anchor else 'event_caption'
                paths = columns + ([c for c in all_header if anchor and c.row == anchor.row and c.col <= label.col] if anchor else [])
            if any(BLOCKED.search(c.text) or FX.search(c.text) for c in [label, *columns] if not UNIT.search(c.text)):
                continue
            periods = [c for c in paths if period_header(c.text)]
            years = {int(y) for c in periods for y in YEAR.findall(c.text)}
            if fiscal and years and years != {fiscal}: continue
            dated = {d for c in periods if (d:=reporting_window(c.text))}
            if end and dated and dated != {end}: continue
            if any(c.text.strip()=='%' and abs(c.col-amount.col)<=amount.width for c in cells): continue
            unit = active_units(all_header, label, amount, cells, columns, pre)
            if not unit: continue
            scale, unit_cell, unit_idx = unit
            unit_text = unit_cell.text if unit_cell else rows[unit_idx]['text'] if unit_idx is not None else amount.text
            if FX.search(unit_text) or any(FX.search(c.text) for c in cells):
                continue
            # A bare '(in thousands)' is a scale, not proof of currency.
            currency_idx = next((i for i,t in reversed(pre) if USD.search(t) and not FX.search(t)),None)
            if not table_currency and currency_idx is None and not USD.search(unit_text+' '+caption):
                continue
            # A qualifier spanning this exact column is evidence for the selected amount.
            relevant = [c for c in columns if re.search(r'\bgross\b|\bnet\b|tax|reinsurance|segment',c.text,I)
                        and c not in (label,anchor) and not period_header(c.text) and not AGG.search(c.text)]
            shared = ' '.join([unit_text] + [c.text for c in relevant])
            status, basis, tax, owner = semantics(label.text,shared)
            if not owner:
                owner = next((c.text for c in reversed(relevant) if re.fullmatch(r'[A-Za-z][\w &-]{0,75} segment', c.text, I)),None)
            tax_pid = next((pid for sentence,pid in definitions if label.text.casefold() in sentence),None)
            if tax_pid and not tax: tax = 'pretax'
            full = val * scale
            value = int(full) if int(full)==full else float(full)
            row_info = rows[p]
            record = v6.prior.v4.base_record(row_info,label.text,basis,status,abs(value),quarter,row_info['text'],'html_table')
            named_owner = row_info['issuer'] + ' — ' + owner if owner else row_info['issuer']
            src_cells = [*([anchor] if anchor else []),label,*periods,*relevant,*([unit_cell] if unit_cell else []),amount,*signs]
            chain = list(dict.fromkeys(rows[table.rows[c.row].passage]['passage_id'] for c in src_cells))
            if table_currency:
                currency_pid = rows[table.rows[table_currency.row].passage]['passage_id']
            else:
                currency_pid = rows[currency_idx]['passage_id'] if currency_idx is not None else rows[p]['passage_id']
            if unit_idx is not None: chain.append(rows[unit_idx]['passage_id'])
            if caption_scope and table.caption_passage is not None: chain.append(rows[table.caption_passage]['passage_id'])
            if tax_pid: chain.append(tax_pid)
            windows = list(dict.fromkeys(c.text for c in periods))
            embedded = re.search(r'(?:for the (?:year|quarter) ended|at|as of)\s+('+DATE.pattern+r')\s+\d{1,2},?',label.text,I)
            if embedded: windows.insert(0, embedded[0])
            window = ' '.join(windows) or filing
            record.update(issuer=named_owner, affected_entity=named_owner, segment=owner,
                          entity_scope=('common_shareholders' if owner=='common shareholders' else 'named_segment_or_subsidiary') if owner else 'reporting_group',
                          tax_basis=tax,signed_usd=value,display_sign='negative' if val.is_signed() else 'positive' if val else 'zero',
                          financial_role=financial_role(label.text,value,basis), amount_text=literal,unit_scale=scale,currency='USD',currency_evidence_passage=currency_pid,
                          unit_heading_passage=rows[table.rows[unit_cell.row].passage]['passage_id'] if unit_cell else rows[unit_idx]['passage_id'] if unit_idx is not None else rows[p]['passage_id'],
                          event_evidence=anchor.text if anchor else caption,reporting_period=filing,reporting_period_source=period_src,
                          recognition_period=window,reporting_or_recognition_period=window,table_orientation=orientation,
                          evidence_passage_ids=list(dict.fromkeys(chain+[currency_pid])), observed_windows=[window] if window else [])
            record['table_observations']=[{'amount_cell':provenance(table,amount,rows), 'metric_cell':provenance(table,label,rows),
                'event_cell':provenance(table,anchor,rows) if anchor else {'caption':caption,'table':table.number},
                'period_cells':[provenance(table,c,rows) for c in periods], 'qualifier_cells':[provenance(table,c,rows) for c in relevant],
                'sign_cells':[provenance(table,c,rows) for c in signs], 'unit_evidence':unit_text,
                'currency_cell':provenance(table,table_currency,rows) if table_currency else None,
                'unit_cell':provenance(table,unit_cell,rows) if unit_cell else None,'window':window}]
            yield record


def window_end(record):
    # Equivalent QTD/YTD reports ending on one date retain each window in the audit.
    s = record.get('recognition_period') or ''
    return reporting_window(s) or s


def table_records(rows, body):
    filing,fiscal,period_src = v6.prior.filing_period(rows)
    quarter,_,_ = v6.prior.v4.filing_context(rows)
    if not any(rows[0]['event'].casefold() in r['text'].casefold() for r in rows): return []
    end,definitions = cover_end(rows),defined_tax(rows)
    found = {}
    for table in read_tables(body,rows):
        for r in values_for_table(table,rows,filing,fiscal,quarter,period_src,end,definitions):
            identity = (r['measure'].casefold(),r['affected_entity'],r['basis'],r['status'],r['signed_usd'],r['tax_basis'],window_end(r))
            previous = found.get(identity)
            if not previous:
                found[identity] = r
                continue
            previous['table_observations'].extend(r['table_observations'])
            for attr in ('evidence_passage_ids','observed_windows'):
                previous[attr] = list(dict.fromkeys(previous[attr]+r[attr]))
            previous['reporting_or_recognition_period'] = ' / '.join(previous['observed_windows'])
    return list(found.values())


def extract_filing(rows, body):
    old = v6.extract_filing(rows,body)
    tables = table_records(rows,body)
    retained = []
    for r in old:
        # The same tagged printed cell and its reconstructed HTML are one observation.
        # Equal numbers in different cells (e.g. incurred and ultimate) remain distinct.
        matches = [t for t in tables if not r.get('review') and r['passage_id']==t['passage_id']
                   and r['issuer']==t['issuer'] and r['low_usd']==t['low_usd'] and r['high_usd']==t['high_usd']
                   and r['measure'].replace('_',' ').casefold()==t['measure'].casefold() and r['status']==t['status']]
        if len(matches)==1:
            matches[0]['corroborating_source_channel']=r['source_channel']
        else:
            retained.append(r)
    return retained + tables


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('primary',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--event')
    args = parser.parse_args()
    groups = defaultdict(list)
    for line in args.input.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            r = json.loads(line)
            if args.event: r['event'] = args.event
            groups[r['doc_id'],r['event']].append(r)
    result = []
    for (doc,_), rows in groups.items():
        result.extend(extract_filing(rows,(args.primary/(doc+'.htm')).read_bytes()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=args.output.parent,delete=False) as output:
        json.dump(result,output,indent=2,ensure_ascii=False)
        output.write('\n')
    os.replace(output.name,args.output)


if __name__ == '__main__':
    main()
