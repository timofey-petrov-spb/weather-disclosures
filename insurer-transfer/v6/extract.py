"""Extract insured storm losses with source-linked attribution per filing.

Run: python v6/extract.py INPUTS.jsonl PRIMARY_HTML_DIRECTORY OUTPUT.json
All records retain the selected event and filing. Explicit local allocations
can be used in a sentence that also names other events.
"""
import argparse
from collections import defaultdict
from decimal import Decimal
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prior_disclosure_v5", ROOT / "v5" / "extract.py")
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)

PERIL = prior.PERIL
EVENT = rf'(?i:{PERIL})\s+(?P<storm>[A-Z][A-Za-z-]+)\b'
VALUE = (r'(?P<amount>(?:US\$\s*|\$\s*|USD\s+)'
         r'(?P<number>(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*'
         r'(?P<unit>(?i:billions?|millions?|thousands?|bn|mn|mm|[bmk]))?(?![\w\d,.]\d)(?!\w))')
TAX = r'(?:pre[- ]?tax|after[- ]tax|before (?:income )?tax(?:es)?|net of (?:income )?tax(?:es)?)'
SCOPE = r'(?:gross|net(?: of reinsurance)?|retained)'
ADJECTIVE = rf'(?:{TAX}|{SCOPE}|catastrophe|catastrophic|estimated|insured|incurred|reported|paid|booked|recognized|recorded|ultimate|expected|projected|total)'
LOSS = rf'(?:(?:{ADJECTIVE})[- ]+){{0,5}}loss(?:es)?(?: and (?:loss )?adjustment expenses?)?'
QUALIFIER = r'(?:approximately|about|roughly|estimated at|at least|more than|in excess of|up to|less than|at most|no more than)'
CONNECT = r'(?:of|totaled|totalled|were|was|amounted to|reached|at|were estimated at|was estimated at|estimated at|estimated to be)'
LINK = r'(?:attributable to|attributed to|from|for|related to|associated with|due to|arising from|caused by|resulting from|in connection with)'
# An amount must have a local grammatical link to an event. Mere proximity to
# a catastrophe narrative or an annual aggregate is insufficient.
FORWARD = re.compile(
    EVENT + rf"(?:'s|’s)?\s+(?P<label>(?i:(?:(?:generated|caused|resulted in|led to|produced|accounted for)\s+)?"
    rf"{LOSS}))\s*(?:(?i:{CONNECT})\s+)?(?:(?P<qual>(?i:{QUALIFIER}))\s+)?"+VALUE)
REVERSE = re.compile(
    rf'(?P<label>(?i:{LOSS}))\s+(?i:{CONNECT})\s+(?:(?P<qual>(?i:{QUALIFIER}))\s+)?'
    + VALUE + rf'\s+(?i:{LINK})\s+' + EVENT)
AFTER_AMOUNT = re.compile(
    rf'(?:(?P<qual>(?i:{QUALIFIER}))\s+)?'+VALUE+
    rf'\s+(?i:(?:of|in|in the form of)\s+)?(?P<label>(?i:{LOSS}))\s+(?i:{LINK})\s+'+EVENT)
BEFORE_AMOUNT = re.compile(
    rf'(?P<label>(?i:{LOSS}))\s+(?i:{LINK})\s+'+
    EVENT+rf'\s+(?i:{CONNECT})\s+(?:(?P<qual>(?i:{QUALIFIER}))\s+)?'+VALUE)
ACTOR_AMOUNT = re.compile(
    EVENT+rf'\s+(?i:caused|generated|resulted in|accounted for|led to)\s+'
    rf'(?:(?P<qual>(?i:{QUALIFIER}))\s+)?'+VALUE+rf'\s+(?i:(?:of|in)\s+)?(?P<label>(?i:{LOSS}))')
PARENS = re.compile(
    EVENT+rf'\s*\(\s*(?:(?P<qual>(?i:{QUALIFIER}))\s+)?'+VALUE+
    rf'(?:\s+(?P<label>(?i:{LOSS}|{TAX})))?\s*\)')
MONEY_LINK = re.compile(
    rf'(?:(?P<qual>(?i:{QUALIFIER}))\s+)?' + VALUE +
    rf'\s+(?:(?P<label>(?i:{TAX}|{SCOPE}))\s+)?(?i:(?:was |were )?{LINK})\s+' + EVENT)
EVENT_LINK = re.compile(
    EVENT+rf'\s+(?i:accounted for|contributed|totaled)\s+(?:(?P<qual>(?i:{QUALIFIER}))\s+)?'+
    VALUE+rf'(?:\s+(?P<label>(?i:{TAX}|{SCOPE})))?')
MONEY_RE = re.compile(VALUE)
OUTSIDER = re.compile(r'\b(?:industr(?:y|ies)|market[- ]wide|total economic|across (?:all )?insurers|'
                      r'policy limits?|attachment point|deductible|annual aggregate limit|'
                      r'hypothetical|worst[- ]case|may incur|could (?:incur|exceed|reach)|'
                      r'assets under management|insured values?|loss ratio|per (?:common |diluted )?share)\b',re.I)
DIFFERENT_STATUS = {'estimate','forecast','paid'}
UNIT_SCALE = {**prior.v4.SCALE,'b':10**9,'m':10**6,'mm':10**6,'k':1000}
COORDINATE_NAME = rf'\s*(?:,?\s*(?:and|or|plus|together with|along with|as well as)\s+(?:(?i:{PERIL})\s+)?[A-Z][a-zA-Z-]+)'
JOINT_TAIL = re.compile(COORDINATE_NAME)
JOINT_HEAD = re.compile(rf'(?i:{PERIL})\s+[A-Z][a-zA-Z-]+(?:\s*,\s*[A-Z][a-zA-Z-]+)*'
                       rf'\s*(?:,?\s*(?:and|or|plus|together with|along with|as well as)\s*|,\s*)$')
FOOT_CURRENCY = re.compile(r'(?i)(?:CAD|AUD|NZD|HKD|SGD|Canadian|Australian|Hong Kong|Singapore|C|A)\s*$')
OTHER_CURRENCY = re.compile(r'(?i)^\s*(?:Canadian|Australian|Hong Kong|Singapore) dollars')
RANGE_TAIL = re.compile(r'^\s*(?:[-–—]|to\b|and\b)\s*(?:US\$|USD|\$)?\s*\d',re.I)
LOCAL_TAX = re.compile(r'^\s*[,;(]?\s*('+TAX+r')\b', re.I)
TAX_WORD = re.compile(TAX,re.I)
REPORTING_QUARTER = re.compile(r'\b(?:this|the current|the reporting) quarter\b',re.I)


def scale_value(match):
    unit=(match['unit'] or '').lower().rstrip('s')
    if not unit and ',' not in match['number']:
        return None
    return prior.v4.money_value(Decimal(match['number'].replace(',',''))*UNIT_SCALE.get(unit,1))


def tax(text):
    result={prior.flags(m[0]) for m in TAX_WORD.finditer(text)}
    return result.pop() if len(result)==1 else None


def local_scope(sentence, hit, opening):
    """Return the tax and insurance bases for this allocation only."""
    label=hit['label'] or ''
    suffix=sentence[hit.end():]
    trailing=LOCAL_TAX.match(suffix)
    local=label+(' '+trailing[1] if trailing else '')
    common=opening if not MONEY_RE.search(opening) and not prior.event_names(opening) else ''
    # A common basis can qualify an entire event list. A qualifier attached to
    # one event cannot be borrowed by a later event.
    base=tax(local) or tax(common)
    basis_text=local if prior.GROSS.search(local) or prior.NET.search(local) else common
    gross=bool(prior.GROSS.search(basis_text))
    net=bool(re.search(r'\bretained\b|\bnet\b(?! of (?:income )?tax)',basis_text,re.I))
    basis=('gross' if gross else 'net') if gross != net else None
    return base,basis


def record(row, context, sentence, hit, opening, owner, owner_id, pattern):
    if hit['storm'].casefold()!=row['event'].casefold():
        return None
    before=sentence[:hit.start()]
    after=sentence[hit.end():]
    # When the matched name is the last member of a compound subject its amount
    # belongs to all participants. The symmetric check handles money-first prose.
    if (pattern in (FORWARD,PARENS,EVENT_LINK,ACTOR_AMOUNT) and JOINT_HEAD.search(before)) or (
        hit.end('storm')==hit.end() and JOINT_TAIL.match(after)):
        return None
    if re.search(r'\b(?:between|from)\s*$',sentence[:hit.start('amount')],re.I) or RANGE_TAIL.match(sentence[hit.end('amount'):]):
        return None
    if FOOT_CURRENCY.search(sentence[:hit.start('amount')]) or OTHER_CURRENCY.match(sentence[hit.end('amount'):]):
        return None
    if re.search(r'\b(?:combined|aggregate)\s*(?:with|for)\b|\b(?:loss|damage) estimates? for the (?:market|industry)\b',hit[0],re.I):
        return None
    # Retain the role of an explicit market/industry subject even when a list
    # contains commas. A subsequent issuer clause can start afresh at a semicolon.
    clause=sentence[sentence.rfind(';',0,hit.start())+1:hit.end()]
    if OUTSIDER.search(clause) or prior.EXCLUDED.search(clause) or re.search(
        r'allowance for credit losses|write[- ]off|previously accrued|investment losses|loss on sale',clause,re.I):
        return None
    if pattern in {PARENS,MONEY_LINK,EVENT_LINK} and not re.search(LOSS,hit['label'] or '',re.I):
        if not re.search(LOSS,opening,re.I) or re.search(r'\b(?:premiums?|sales|revenues?|assets?|investments?|limits?|recoveries|benefits|policy count)\b',opening,re.I):
            return None
    value=scale_value(hit)
    if value is None or value<=0:
        return None
    economic_quarter,period,period_source=context
    local=hit[0]
    tax_basis,basis=local_scope(sentence,hit,opening)
    scope=opening+' '+local
    if re.search(r'\b(?:paid|disbursed)\b',local,re.I):status='paid'
    elif re.search(r'\b(?:estimated?|expects?|project(?:ed|ing)?|forecasts?|anticipates?)\b',scope,re.I):status='estimate'
    elif re.search(r'\b(?:booked|incurred|recorded|recognized)\b',scope,re.I):status='incurred'
    else:status='reported'
    reporting_quarter=period if period and '-Q' in period and REPORTING_QUARTER.search(sentence) else None
    explicit_accounting_quarter=prior.explicit_period(local)
    # Only an explicit storm occurrence dates the weather event. A current-
    # quarter claim dates the disclosed loss, not the meteorological occurrence.
    r=prior.v4.base_record(row,'catastrophe_losses',basis,status,value,economic_quarter,sentence,'event_amount_allocation')
    r.update(tax_basis=tax_basis,amount_text=hit['amount'].strip(),event_evidence=local,
             issuer=owner,entity_scope='named_segment_or_subsidiary' if owner_id else 'reporting_group',
             owner_evidence_passage=owner_id,reporting_period=period,reporting_period_source=period_source,
             recognition_period=explicit_accounting_quarter or reporting_quarter,evidence_passage_ids=[row['passage_id']],
             allocation_evidence=local,allocation_span=[hit.start(),hit.end()])
    qualifier=(hit['qual'] or '').lower()
    r['approximate_amount']=qualifier in {'approximately','about','roughly'}
    if qualifier in {'at least','more than','in excess of'}:
        r.update(bound_type='lower_bound',high_usd=None)
    if qualifier in {'up to','less than','at most','no more than'}:
        r.update(bound_type='upper_bound',low_usd=None)
    return r


EVENT_PAIR = re.compile(rf'\b(?i:{PERIL})\s+(?P<first>[A-Z][A-Za-z-]+)\s*(?:,?\s*(?:and|&)\s+)(?:(?i:{PERIL})\s+)?(?P<second>[A-Z][A-Za-z-]+)\b')
PERIOD_PAIR = re.compile(r'\b(?:years?|quarters?|months?) ended\b|\b(?:20\d{2}\s+and\s+20\d{2})\b',re.I)

def ordinal_pair(row,context,sentence,owner,owner_id):
    """Two names and two amounts mapped by the issuer's explicit 'respectively'."""
    if not re.search(r'\brespectively\b',sentence,re.I) or not re.search(LOSS,sentence,re.I):
        return []
    if (OUTSIDER.search(sentence) or prior.EXCLUDED.search(sentence) or PERIOD_PAIR.search(sentence)
        or re.search(r'loss ratios?|per share|premiums?|credit losses|recoveries|combined|collectively|jointly',sentence,re.I)):
        return []
    pairs=list(EVENT_PAIR.finditer(sentence))
    amounts=list(MONEY_RE.finditer(sentence))
    if len(pairs)!=1 or len(amounts)!=2:return []
    pair=pairs[0]
    names=[pair['first'].casefold(),pair['second'].casefold()]
    if (len(set(names))!=2 or row['event'].casefold() not in names or
        set(names)&prior.BANNED or prior.event_names(sentence)-set(names)):return []
    if not (pair.end()<=amounts[0].start() or amounts[1].end()<=pair.start()):return []
    if not re.fullmatch(r'\s*(?:,?\s*(?:and|&))\s*',sentence[amounts[0].end():amounts[1].start()],re.I):return []
    if any(not m['unit'] and ',' not in m['number'] for m in amounts):return []
    if re.search(r'\b(?:at least|no more than|less than|from|between)\s*\$',sentence,re.I):return []
    if any(FOOT_CURRENCY.search(sentence[:m.start()]) or OTHER_CURRENCY.match(sentence[m.end():]) for m in amounts):return []
    # Avoid a second, rival ordinal interpretation (different accounting or tax bases).
    if prior.GROSS.search(sentence) and prior.NET.search(sentence):return []
    if len({prior.flags(m[0]) for m in TAX_WORD.finditer(sentence)})>1:return []
    idx=names.index(row['event'].casefold())
    amount=amounts[idx];value=scale_value(amount)
    if value is None or value<=0:return []
    quarter,report,source=context
    role='gross' if prior.GROSS.search(sentence) else 'net' if prior.NET.search(sentence) else 'unknown'
    rec=prior.prepare(row,{'period_id':source},role,value,sentence,amount[0],report,quarter,owner,owner_id)
    if re.search(r'estimat|project|expect',sentence,re.I):rec['status']='estimate'
    rec.update(source_channel='ordered_event_allocation',allocation_evidence=sentence,
               ordered_event_names=[pair['first'],pair['second']],allocation_index=idx,
               allocation_span=[amount.start(),amount.end()])
    return [rec]

def allocated_rows(row,context,owner,owner_id):
    target=re.compile(r'\b'+re.escape(row['event'])+r'\b',re.I)
    if not target.search(row['text']) or row['kind']=='table_row':
        return []
    found=[]
    for sentence in prior.v4.sentence_pieces(row['text']):
        if not target.search(sentence):
            continue
        ordinal=ordinal_pair(row,context,sentence,owner,owner_id)
        if ordinal:
            found.extend(ordinal)
            continue
        events=[m for m in prior.NAMED.finditer(sentence) if m[1].lower() not in prior.BANNED]
        if not events:continue
        opening=sentence[:events[0].start()]
        used=set()
        for pattern in (FORWARD,REVERSE,AFTER_AMOUNT,BEFORE_AMOUNT,ACTOR_AMOUNT,PARENS,MONEY_LINK,EVENT_LINK):
            for hit in pattern.finditer(sentence):
                key=(hit.span('storm'),hit.span('amount'))
                if key in used:continue
                row_out=record(row,context,sentence,hit,opening,owner,owner_id,pattern)
                if row_out:
                    used.add(key)
                    found.append(row_out)
    return found


def same_record(a,b):
    if (a['issuer'],a['event'],a['low_usd'],a['high_usd'])!=(b['issuer'],b['event'],b['low_usd'],b['high_usd']):
        return False
    if prior.metric_family(a)!='loss' or prior.metric_family(b)!='loss':
        return False
    for name in ('basis','tax_basis','recognition_period','period'):
        if a.get(name) and b.get(name) and a[name]!=b[name]:
            return False
    if a['status']!=b['status'] and {a['status'],b['status']}&DIFFERENT_STATUS:
        return False
    return True


def refine(rows,old):
    report,_,source=prior.filing_period(rows)
    quarter,_,_=prior.v4.filing_context(rows)
    merged=list(old)
    for index,row in enumerate(rows):
        if row['event'].lower() not in row['text'].lower():continue
        owner,owner_id=prior.section_owner(rows,index)
        for r in allocated_rows(row,(quarter,report,source),owner,owner_id):
            # Tagged-note and segment methods can resolve the very same printed
            # mention more precisely. In financial notes a bare "$65,000" can
            # mean 65 million. The local reading must never override that scale.
            if not re.search(r'[a-z]',r['amount_text'],re.I):
                unit,unit_source=prior.v4.row_scale(rows,index)
                if unit_source:
                    for endpoint in ('low_usd','high_usd'):
                        if r[endpoint] is not None:
                            r[endpoint]=prior.v4.money_value(Decimal(str(r[endpoint]))*unit)
                    r['unit_heading_passage']=unit_source
            stronger=[]
            for a in old:
                if row['passage_id'] not in a.get('evidence_passage_ids',[a['passage_id']]) or a.get('review'):continue
                if ((a['low_usd'],a['high_usd'])==(r['low_usd'],r['high_usd'])
                    and row['passage_id']!=a['passage_id']
                    and (prior.metric_family(a)=='loss' or a['measure']=='segment_claims_expense')
                    and (not r.get('basis') or a.get('basis')==r['basis'])):
                    # The earlier method already verified this secondary passage
                    # as a repeated source of the more precise financial record.
                    stronger.append(a)
                    continue
                if a.get('source_channel') not in {'inline_xbrl','attributed_clause','explicit_financial_bridge'}:continue
                if a.get('evidence')==r['evidence'] and (
                    (a['low_usd'],a['high_usd'])==(r['low_usd'],r['high_usd']) or
                    a.get('source_channel')=='inline_xbrl' and re.sub(r'[^0-9.]','',a.get('amount_text') or '')==re.sub(r'[^0-9.]','',r['amount_text'])
                ):
                    stronger.append(a)
            if stronger:continue
            matches=[candidate for candidate in merged if not candidate['review'] and same_record(candidate,r)]
            if len(matches)==1:
                match=matches[0]
                evidence=match.setdefault('evidence_passage_ids',[match['passage_id']])
                if row['passage_id'] not in evidence:evidence.append(row['passage_id'])
                for field in ('tax_basis','basis','recognition_period','allocation_evidence'):
                    if match.get(field) is None and r.get(field) is not None:
                        match[field]=r[field]
            elif not matches:
                merged.append(r)
    return merged


def extract_filing(rows,body):
    previous=prior.refine(rows,prior.v4.extract_filing(rows,body))
    return refine(rows,previous)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('primary',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--event',help='Read the same source documents for a different named storm.')
    args=parser.parse_args()
    groups=defaultdict(list)
    for line in args.input.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            row=json.loads(line)
            if args.event:
                row['event']=args.event
            groups[(row['doc_id'],row['event'])].append(row)
    results=[]
    for (key,_),rows in groups.items():
        results.extend(extract_filing(rows,(args.primary/(key+'.htm')).read_bytes()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=args.output.parent,delete=False) as stream:
        json.dump(results,stream,ensure_ascii=False,indent=2)
        stream.write('\n')
    os.replace(stream.name,args.output)


if __name__=='__main__':
    main()

