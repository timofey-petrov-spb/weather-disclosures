"""Bind insurer disclosures to named weather events, monetary roles and reporting windows.

Usage: python v5/extract.py INPUTS_JSONL PRIMARY_HTML_DIRECTORY OUTPUT_JSON
"""
import argparse
from collections import defaultdict
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import re
import sys

V4_DIR=Path(__file__).resolve().parents[1]/'v4'
sys.path.insert(0,str(V4_DIR))
spec=importlib.util.spec_from_file_location('disclosure_v4',V4_DIR/'extract.py')
v4=importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4)
I=re.I
PERIL=r'(?:hurricanes?|tropical storms?|winter storms?|tornado(?:es)?|wildfires?|typhoons?|cyclones?|earthquakes?|hailstorms?)'
NAMED=re.compile(r'\b(?i:'+PERIL+r')\s+([A-Z][a-zA-Z-]+)\b')
BANNED={'and','the','category','losses','claims','insurance','season','reinsurance','catastrophe','events','coverage','relief','loss','exposure','members','warning','watch','program'}
GROSS=re.compile(r'\bgross\b|\bbefore (?:ceded |anticipated |expected )?reinsurance|\bprior to reinsurance',I)
RECOVERY=re.compile(r'(?:reinsurance |ceded )?recover(?:ies|y|able[s]?)\b|ceded losses',I)
NET=re.compile(r'\bnet(?:ted)?\b|\bretained\b|\bretention\b|\bafter (?:anticipated |expected )?reinsurance',I)
ACCOUNTING=re.compile(r'loss(?:es)?|claims?|reinsurance|retained|retention|damages?|expen[sd]|charges?',I)
EXCLUDED=re.compile(r'industry(?:wide|[- ]wide)?|market.wide|market loss|policy limits?|aggregate limit|attachment point|hypothetical|could (?:incur|exceed|reach)|return period|might (?:result|reach)|would have|total economic (?:loss|damage)|coverage (?:limit|in force)|assets under|market share|catastrophe bond issued|policyholders? can|income from continuing operations',I)
COMPARE=re.compile(r'(?:increase|decrease|grew|rose|fell|decline)[ds]?\b.{0,45}\b(?:compared|year-over-year|from [12]\d{3}|in the .{0,22} of 20\d\d)|compared (?:with|to)|year.over.year',I)
COVER=re.compile(r'\b(?:for the )?(quarterly period|fiscal year|year) ended\s+([A-Z][a-z]+)\s+(\d{1,2}),?\s*(20\d\d)',I)
QUARTER={'first':1,'second':2,'third':3,'fourth':4}
MONEY=re.compile(r'(?<![\w$])(?:US\$|\$|USD\s*)\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(billion|million|thousand|bn|mn)?\b',I)

def event_names(text):
    return {m[1].lower() for m in NAMED.finditer(text) if m[1].lower() not in BANNED}
def only_event(text,event):
    return v4.single_event(text,event) and not(event_names(text)-{event.lower()})
def filing_period(rows):
    for idx,r in enumerate(rows[:100]):
        # Cover captions sometimes break at the fiscal-year/quarter date.
        text=' '.join(a['text'] for a in rows[idx:idx+2])
        m=COVER.search(text)
        if m and m[2].lower() in v4.legacy.MONTHS:
            yr=int(m[4]);month=v4.legacy.MONTHS[m[2].lower()]
            return (f'FY{yr}' if rows[0].get('source_kind')=='10-K' else f'{yr}-Q{(month-1)//3+1}'),yr,r['passage_id']
    return None,None,None
def explicit_period(text):
    m=re.search(r'\b(first|second|third|fourth) quarter (?:of |ended in )?(20\d\d)\b',text,I)
    if m:return f'{m[2]}-Q{QUARTER[m[1].lower()]}'
    m=re.search(r'(?:three(?: and (?:six|nine|twelve))? months|quarter) ended ([A-Z][a-z]+)\s+\d{1,2},?\s*(20\d\d)',text,I)
    if m and m[1].lower() in v4.legacy.MONTHS:return f'{m[2]}-Q{(v4.legacy.MONTHS[m[1].lower()]-1)//3+1}'
    return None
def section_owner(rows,i):
    for row in reversed(rows[max(0,i-80):i+1]):
        t=row['text'].strip()
        m=re.fullmatch(r'([A-Z][\w &/.,-]{1,75}?)\s+[Ss]egment\s+(?:[Rr]esults|[Oo]perations|[Ff]inancial [Rr]esults|[Oo]verview)',t)
        if m:
            return m[1]+' segment',row['passage_id']
        if re.fullmatch(r'(?:Consolidated Results|Corporate and Other|Consolidated Overview)',t,I):break
    return rows[i]['issuer'],None
def value_of(m):
    unit=(m[2] or '').lower()
    if not unit and ',' not in m[1]:return None
    return v4.money_value(Decimal(m[1].replace(',',''))*v4.SCALE.get(unit,1))
def excluded_program(sentence):
    m=re.search(r'\b(?:excluding|exclusive of)\s+(.{2,110}?)(?=,|(?:\s+(?:were |was |are |totaled |totalled |amounted |of \$|\$)))',sentence,I)
    return m[1].strip() if m else None
def flags(sentence):
    return ('pretax' if re.search(r'\bpre[- ]?tax|\bbefore (?:income )?tax(?:es)?\b',sentence,I) else
            'after_tax' if re.search(r'\bafter[- ]tax|\bnet of (?:income )?tax(?:es)?',sentence,I) else None)
def prepare(row,ctx,role,value,quote,amount,reported,event_q,owner,scope_id):
    metric,basis,status={'gross':('catastrophe_losses','gross','estimate'),
                         'net':('catastrophe_losses','net','estimate'),
                         'expected_recovery':('reinsurance_recoveries','ceded','anticipated'),
                         'paid_recovery':('reinsurance_recoveries','ceded','received'),
                         'reported_recovery':('reinsurance_recoveries','ceded','reported'),
                         'unknown':('catastrophe_losses',None,'reported')}[role]
    if role in ('gross','net') and not re.search(r'estimat|forecast|expect|anticipat|project',quote,I):
        status='incurred' if re.search(r'\bincurred|recognized|recorded|booked\b',quote,I) else 'reported'
    rec=v4.base_record(row,metric,basis,status,value,event_q,quote,'bound_event_clause')
    rec.update(amount_text=amount,issuer=owner,entity_scope='named_segment_or_subsidiary' if scope_id else 'reporting_group',
        reporting_period=reported,reporting_period_source=ctx['period_id'],event_evidence=quote,
        tax_basis=flags(quote) if role in ('gross','net','unknown') else None,
        evidence_passage_ids=[row['passage_id']],owner_evidence_passage=scope_id,
        approximate_amount=bool(re.search(r'approximat(?:ely|e)\s*'+re.escape(amount.strip()),quote,I)))
    return rec

def named_bundle(row,ctx,sentence,owner,scope_id):
    """A disclosed gross / recovery / net bridge, with each role bound locally."""
    if not only_event(sentence,row['event']) or EXCLUDED.search(sentence):return []
    amounts=list(MONEY.finditer(sentence))
    if len(amounts)!=3:return []
    v=[value_of(m) for m in amounts]
    if any(x is None or x<=0 for x in v):return []
    pieces=[sentence[:amounts[0].start()],sentence[amounts[0].end():amounts[1].start()],
            sentence[amounts[1].end():amounts[2].start()],sentence[amounts[2].end():]]
    # The three finance roles must all appear. Match role descriptions on either
    # side of the figures and independently corroborate the assignment arithmetically.
    if not (GROSS.search(sentence) and RECOVERY.search(sentence) and NET.search(sentence)):return []
    if not re.search(r'estimat|incurred|expect|recover|recorded',sentence,I):return []
    from itertools import permutations
    candidates=[]
    for g,c,n in permutations(range(3)):
        if abs(v[g]-v[c]-v[n])>max(1.0,0.001*max(v)):continue
        patterns={g:GROSS,c:RECOVERY,n:NET}
        score=0
        for k,pat in patterns.items():
            before=list(pat.finditer(pieces[k]))
            after=pat.search(pieces[k+1])
            distances=([len(pieces[k])-before[-1].end()] if before else [])+([after.start()] if after else [])
            if not distances:break
            score+=min(distances)
        else:candidates.append((score,g,c,n))
    candidates.sort()
    if not candidates or len(candidates)>1 and candidates[0][0]==candidates[1][0]:return []
    _,g,c,n=candidates[0]
    recrole='expected_recovery' if re.search(r'anticipat|expect|will be|estimated recover',sentence,I) else ('paid_recovery' if re.search(r'received|collected',sentence,I) else 'reported_recovery')
    scope=excluded_program(sentence)
    out=[]
    for idx,role in ((g,'gross'),(c,recrole),(n,'net')):
        r=prepare(row,ctx,role,v[idx],sentence,amounts[idx][0],ctx['period'],ctx['event_quarter'],owner,scope_id)
        r.update(source_channel='explicit_financial_bridge',reconciliation='all_three_values_printed',excludes=scope if role in ('gross','net') else None)
        out.append(r)
    return out

def single_clause(row,ctx,sentence,previous,owner,scope_id):
    event=row['event']
    local=only_event(sentence,event)
    joined=False
    if not local:
        if not only_event(previous,event) or event_names(sentence) or not re.match(r'^(?:For (?:this|that) (?:event|storm)|(?:This|The|That) (?:event|hurricane|storm)|(?:We|The Company) (?:currently )?estimat(?:e|es|ed) (?:that )?(?:our |its |the )?(?:gross |net |pre[- ]tax )?(?:losses? (?:from |for )?(?:this|the) (?:event|storm)|impact (?:of|from) (?:this|the) (?:event|storm)))',sentence,I): return []
        joined=True
    if EXCLUDED.search(sentence) or COMPARE.search(sentence) or re.search(r'and (?:other|several|additional) (?:catastrophes|storms|events)|\bcombined\b|principally due to|primarily related to (?:several|multiple)',sentence,I):return []
    out=[]
    for m in MONEY.finditer(sentence):
        val=value_of(m)
        if val is None or val<=0:continue
        # Do not cut decimals or split comma-separated digits.
        other=[x for x in MONEY.finditer(sentence) if x.start()!=m.start()]
        left_edge=max((x.end() for x in other if x.end()<=m.start()),default=0)
        right_edge=min((x.start() for x in other if x.start()>=m.end()),default=len(sentence))
        before=sentence[left_edge:m.start()];after=sentence[m.end():right_edge]
        local_text=(before+' '+after).strip()
        if other and not only_event(local_text,event):continue
        if other and not re.match(r'^\s*(?:of |in |for )?(?:(?:expected|anticipated|estimated) )?(?:reinsurance recoveries|net losses?|gross losses?|catastrophe losses?)',after,I):continue
        if not ACCOUNTING.search(local_text) or re.search(r'allowance for credit|write[- ]off|written off|loss ratio|renewal premiums|per (?:common |diluted )?share',local_text,I):continue
        if re.search(r'\b(?:coverage|limits?|assets|premium growth|deductible)\b',local_text,I) and not RECOVERY.search(local_text):continue
        if re.search(r'\b(?:at least|approximately between|between|up to|could|may|ranged? from)\b',before,I) or re.match(r'\s*(?:to|-|–)\s*\$?\d',after): continue
        if re.search(r'pre[- ]tax.{0,32}after[- ]tax|after[- ]tax.{0,32}pre[- ]tax',local_text,I):continue
        if RECOVERY.search(local_text) and not (NET.search(local_text) or GROSS.search(local_text)):
            role='expected_recovery' if re.search(r'expect|anticipat|project|estim',local_text,I) else 'paid_recovery' if re.search(r'received|collected',local_text,I) else 'reported_recovery'
        elif GROSS.search(local_text) and not NET.search(local_text):role='gross'
        elif NET.search(local_text) and not GROSS.search(local_text):role='net'
        else:role='unknown'
        if role=='unknown' and (other or not re.search(r'(?:catastrophe|storm|hurricane)[ -]?(?:related )?loss(?:es)?|loss(?:es)? (?:attributable to|from|caused by|arising from)',local_text,I)):continue
        # Require a grammatical link, not a bare amount next to an event and unrelated balances.
        if not (re.search(r'(?:loss(?:es)?|recover(?:ies|y)|charge|claims?)(?:\s+(?:were|was|of|totaled|totalled|at|approximately|for|from|estimated|attributable to|before tax|after tax|in|recorded|by|on|related to|net|gross|pre[- ]?tax|hurricane|tropical storm)|[\s,:()\-]|\b[A-Z][a-z]+\b){0,15}$',before,I) or re.match(r'\s*(?:of |in |for )?(?:pre[- ]?tax |after[- ]?tax |reported |estimated |anticipated |expected |reinsurance |net |gross |catastrophe )*(?:loss|recover|claim|charge)',after,I)):continue
        rec=prepare(row,ctx,role,val,sentence,m[0],ctx['period'],ctx['event_quarter'],owner,scope_id)
        if joined:rec['event_evidence']=previous+' '+sentence
        program=re.search(r'\b(?:related to|under|from) (?:the )?([A-Z][A-Za-z -]{4,80}?(?:Program|Treaty|Agreement))\b',local_text)
        if program:rec['program']=program[1].strip()
        rec['excludes']=excluded_program(sentence)
        out.append(rec)
    return out

def category_bridge(rows,i,ctx,record_set):
    """Unique named event, count=1, dated money column, linked footnote, exact bridge."""
    row=rows[i];text=row['text']
    if not re.match(r'^(?:Hurricanes?|Tropical storms?|Typhoons?|Cyclones?)(?:\s*[/&]\s*(?:Tropical storms?|Hurricanes?))?\s*(?:\(\d+\))?\s*\|',text,I):return []
    if not ctx['year']:return []
    title=next((x for x in reversed(rows[max(0,i-12):i]) if re.search(r'(?:catastrophe|catastrophic|storm) losses by (?:the )?(?:type|peril|category|event)',x['text'],I)),None)
    if not title:return []
    headers=[x for x in rows[max(0,i-6):i] if 'number of events' in x['text'].lower() or 'event count' in x['text'].lower()]
    if not headers:return []
    hdr=headers[-1]
    labels=[s.strip() for s in hdr['text'].split('|') if s.strip()]
    unit_match=re.search(r'\b(?:dollars?\s+|\$\s*)?(?:in )?(millions|thousands|billions)\b',hdr['text'],I)
    if not unit_match:return []
    unit=v4.SCALE[unit_match[1].lower().rstrip('s')]
    years=[];pending=False
    for col in labels:
        if re.search(r'number of events|event count',col,I):pending=True
        else:
            yy=re.fullmatch(r'(20\d{2})(?:\(\d+\))?',col)
            if yy:
                if not pending:return []
                years.append(int(yy[1]));pending=False
    if not years or pending:return []
    cells=[s.strip().replace('$','').strip() for s in text.split('|')[1:] if s.strip() and s.strip()!='$']
    if len(cells)!=2*len(years):return []
    observed=[]
    for j,yr in enumerate(years):
        if yr!=ctx['year']:continue
        count_s,amount=cells[2*j:2*j+2]
        if count_s!='1' or not re.fullmatch(r'[\d,]+(?:\.\d+)?',amount):return []
        observed.append(int(Decimal(amount.replace(',',''))*unit))
    if not observed or len(set(observed))!=1:return []
    amount=observed[0]
    quoted=[x for x in record_set if x.get('source_channel')=='explicit_financial_bridge' and x['basis']=='net' and x.get('excludes') and i-30<=ctx['order'][x['passage_id']]<i]
    if len(quoted)!=1:return []
    net=quoted[0]
    near=' '.join(x['text'] for x in rows[ctx['order'][net['passage_id']]:i])
    if event_names(near)-{row['event'].lower()}:return []
    marker=re.search(r'\((\d+)\)\s*(?:\||$)',text)
    if not marker:return []
    footnotes=[x for x in rows[i+1:i+26] if re.match(r'^\s*\('+marker[1]+r'\)',x['text'])]
    if len(footnotes)!=1:return []
    foot=footnotes[0];note=foot['text']
    if str(ctx['year']) not in note or not re.search(r'includ|contain',note,I):return []
    money=list(MONEY.finditer(note))
    if len(money)!=1:return []
    extra=value_of(money[0])
    if extra is None or amount!=net['low_usd']+extra:return []
    # A printed component and net estimate from the same program must explain the
    # category total. Punctuation and optional abbreviations can vary.
    words=lambda s:set(re.findall(r'[a-z]{3,}',s.lower()))-{'the','for','and','claims','claim','expenses','expense','related','insurance','program'}
    if not (words(net['excludes'])&words(note)):return []
    quarter_col=next((x for x in rows[max(0,i-5):i] if re.search(r'three months ended|quarter ended',x['text'],I)),None)
    eq=net.get('event_quarter') or (ctx['period'] if quarter_col and ctx['period'] and '-Q' in ctx['period'] else None)
    proof=[net['passage_id'],title['passage_id']]+([quarter_col['passage_id']] if quarter_col else [])+[hdr['passage_id'],row['passage_id'],foot['passage_id']]
    result=[]
    for src,val,metric,basis,status in ((row,amount,'catastrophe_losses_including_program_expenses','net_including_expenses','reported_estimate'),
                                 (foot,extra,'program_claim_expense','program_expense_component','included_expense')):
        r=prepare(src,ctx,'net',val,src['text'],str(val),ctx['period'],eq,net['issuer'],net.get('owner_evidence_passage'))
        r.update(measure=metric,basis=basis,status=status,source_channel='unique_event_count_footnote',evidence_passage_ids=[src['passage_id']],
                 supporting_passage_ids=proof,event_evidence=net['evidence'],includes=net['excludes'],event_count=1,reported_year=ctx['year'],
                 tax_basis=None,amount_text=money[0][0] if src is foot else cells[2*years.index(ctx['year'])+1])
        result.append(r)
    return result

def tax_pair(row,ctx,sentence,owner,owner_id):
    """Some issuers report the same loss before and after income taxes."""
    if not only_event(sentence,row['event']) or EXCLUDED.search(sentence) or COMPARE.search(sentence):return []
    if not ACCOUNTING.search(sentence) or re.search(r'\b(?:industry|combined|including other|multiple storms)\b',sentence,I):return []
    amounts=list(MONEY.finditer(sentence))
    if len(amounts)!=2:return []
    val=[value_of(m) for m in amounts]
    if not all(x and x>0 for x in val):return []
    taxpat=re.compile(r'\bpre[- ]?tax|\bbefore (?:income )?tax(?:es)?\b|\bafter[- ]tax|\bnet of (?:income )?tax(?:es)?\b',I)
    labels=[(m,flags(m[0])) for m in taxpat.finditer(sentence)]
    if len(labels)!=2 or {lab for m,lab in labels}!={'pretax','after_tax'}:return []
    choices=[]
    for li in ((0,1),(1,0)):
        scores=[]
        for a,idx in zip(amounts,li):
            tax=labels[idx][0]
            distance=max(0,a.start()-tax.end(),tax.start()-a.end())
            scores.append(distance)
        if max(scores)<=50:choices.append((sum(scores),li))
    choices.sort()
    if not choices or len(choices)>1 and choices[0][0]==choices[1][0]:return []
    labels_for=[labels[idx][1] for idx in choices[0][1]]
    if val[labels_for.index('after_tax')]>val[labels_for.index('pretax')]:return []
    basis='net' if re.search(r'net of reinsurance|after reinsurance',sentence,I) else 'gross' if GROSS.search(sentence) else None
    result=[]
    for m,num,label in zip(amounts,val,labels_for):
        r=prepare(row,ctx,basis or 'unknown',num,sentence,m[0],ctx['period'],ctx['event_quarter'],owner,owner_id)
        r.update(source_channel='explicit_tax_pair',tax_basis=label,basis=basis,excludes=excluded_program(sentence))
        result.append(r)
    return result

def metric_family(r):
    label=r['measure'].lower()
    if label in {'claims_losses','claims_losses_and_lae','catastrophe_losses'}:return 'loss'
    if label in {'reinsurance_recoveries','insurance_recovery'}:return 'recovery'
    return label


def aliases_equal(a,b): return re.sub(r'[^a-z0-9]','',a.lower())==re.sub(r'[^a-z0-9]','',b.lower())
def compatible(a,b):
    if (a['doc_id'],a['event'],a['low_usd'],a['high_usd'])!=(b['doc_id'],b['event'],b['low_usd'],b['high_usd']):return False
    if a.get('tax_basis') and b.get('tax_basis') and a['tax_basis']!=b['tax_basis']:return False
    if a.get('basis') and b.get('basis') and a['basis']!=b['basis']:return False
    if metric_family(a)!=metric_family(b):return False
    if a.get('program') and b.get('program') and not aliases_equal(a['program'],b['program']):return False
    if a.get('excludes') and b.get('excludes') and not aliases_equal(a['excludes'],b['excludes']):return False
    if {a['status'],b['status']} & {'received','paid'} and a['status']!=b['status']:return False
    if aliases_equal(a['issuer'],b['issuer']):return True
    return a.get('entity_scope')=='reporting_group' or b.get('entity_scope')=='reporting_group'
def refine(rows,old):
    period,year,period_id=filing_period(rows)
    q,_,_=v4.filing_context(rows)
    event=rows[0]['event']
    if q is None:
        periods={explicit_period(s) for r in rows for s in v4.sentence_pieces(r['text'])
                 if only_event(s,event) and ACCOUNTING.search(s) and not COMPARE.search(s)}
        periods.discard(None)
        if len(periods)==1:q=periods.pop()
    ctx={'period':period,'year':year,'period_id':period_id,'event_quarter':q,'order':{r['passage_id']:i for i,r in enumerate(rows)}}
    new=[]
    for i,row in enumerate(rows):
        text=row['text']
        carry=''
        if i and row['kind']=='paragraph' and rows[i-1]['kind']=='paragraph':
            last=v4.sentence_pieces(rows[i-1]['text'])[-1]
            if only_event(last,event) and len(last)<650:carry=last
        if event.lower() not in text.lower() and not carry:continue
        owner,owner_id=section_owner(rows,i)
        previous=carry
        for sentence in v4.sentence_pieces(text):
            if EXCLUDED.search(sentence):previous=sentence;continue
            if period and period.startswith('FY') and re.search(r'and (?:Winter Storm|Tropical Storm|Hurricane|Wildfire|Typhoon) [A-Z]',sentence) and not only_event(sentence,event):
                previous=sentence;continue
            records=named_bundle(row,ctx,sentence,owner,owner_id)
            if not records:
                records=tax_pair(row,ctx,sentence,owner,owner_id)
            if not records:
                # Earnings-per-share equivalents are floating rates, not a second loss.
                no_eps=re.sub(r'[,;(]\s*(?:or\s+)?\$[\d,.]+\s*(?:per|a)\s+(?:(?:diluted|common)\s+)?share\)?', '',sentence,flags=I)
                records=single_clause(row,ctx,no_eps,previous,owner,owner_id)
                for rec in records:
                    rec['evidence']=sentence
                    if previous and rec['event_evidence']!=no_eps:
                        rec['supporting_passage_ids']=[rows[i-1]['passage_id'],row['passage_id']] if previous==carry and i else [row['passage_id']]
            new.extend(records);previous=sentence
    for i,row in enumerate(rows):
        if row['kind']=='table_row':new.extend(category_bridge(rows,i,ctx,new))
    # The scoped bridge has stronger subject attribution than an unscoped repeated
    # footnote. Preserve different program or accounting bases for equal figures.
    new.sort(key=lambda r:({'explicit_financial_bridge':0,'unique_event_count_footnote':1}.get(r['source_channel'],2)))
    merged=list(old)
    for r in new:
        if r['source_channel']=='bound_event_clause' and any(
            a['source_channel']=='attributed_clause' and r['passage_id'] in a.get('evidence_passage_ids',[a['passage_id']])
            and a['low_usd']==r['low_usd'] and a['high_usd']==r['high_usd']
            and (a['evidence']==r['evidence'] or a['amount_text']==r['amount_text'])
            for a in old):
            continue
        same=[a for a in merged if compatible(r,a)]
        if same:
            is_legacy=any(a in old for a in same)
            # A gross/net figure in the notes may also appear unscaled in prose.
            # Existing inline-XBRL rows remain financially authoritative here.
            if is_legacy and not r['source_channel']=='explicit_financial_bridge':continue
            if len(same)==1:
                a=same[0]
                if r.get('program'):a['program']=r['program']
                if r.get('excludes'):a['excludes']=r['excludes']
                if r['passage_id'] not in a['evidence_passage_ids']:a['evidence_passage_ids'].append(r['passage_id'])
                continue
        if any(a.get('source_channel')=='inline_xbrl' and r['passage_id'] in a.get('evidence_passage_ids',[a['passage_id']])
                   and re.sub(r'\D','',a.get('amount_text') or '')==re.sub(r'\D','',r['amount_text']) for a in old): continue
        merged.append(r)
    return merged
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('primary',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args();groups=defaultdict(list)
    for line in args.input.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            row=json.loads(line);groups[row['doc_id']].append(row)
    output=[]
    for key,rows in groups.items():
        old=v4.extract_filing(rows,(args.primary/(key+'.htm')).read_bytes())
        output+=refine(rows,old)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()


