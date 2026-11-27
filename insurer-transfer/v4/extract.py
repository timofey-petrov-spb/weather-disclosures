"""Extract evidence-linked financial disclosures for a selected storm and issuer.

Usage: python extract.py INPUTS_JSONL PRIMARY_HTML_DIRECTORY OUTPUT_JSON
The input passages must come from the visible-text reader used for this study.
The output is filing-level. Repetitions of the same financial fact link to evidence.
"""
import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
from xml.etree import ElementTree as ET

from source_reader import TaggedText
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import extractor_v3 as legacy
from xbrl_units import usd_facts

CASE = re.I
MONEY = re.compile(r'\$\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*(billion|million|thousand|bn|mn)?', CASE)
NAMED = re.compile(r'\b(?i:hurricanes?|tropical storms?|typhoons?|cyclones?)\s+([A-Z][a-z][a-zA-Z-]+)')
SENTENCE = re.compile(r'(?<!\bInc)(?<!\bCo)(?<=[.!?])\s+(?=[A-Z“])')
SCALE = {'billion':10**9,'million':10**6,'thousand':1000,'bn':10**9,'mn':10**6}
# Ordered from narrower to broader concepts. Vocabulary applies across taxonomies.
CONCEPTS = [
    (r'incurredbutnotreported|ibnr', 'ibnr_and_development','net','reserve_estimate'),
    (r'cumulativepaidclaims|claimsandbenefitspaid|(?<!un)paidlosses', 'paid_claims_and_allocated_expense','net','paid_cumulative'),
    (r'liabilityforunpaidclaims|unpaidclaims.*liability', 'unpaid_claims_liability','net','balance'),
    (r'incurredclaimsandallocatedclaimadjustment', 'incurred_claims_and_allocated_expense','net','incurred'),
    (r'netincreasetocededpremium|retrospective.*reinsurance.*adjust', 'ceded_premium_adjustment','ceded','recognized_reversal'),
    (r'recoverables.*allowance|allowance.*reinsurance', 'credit_loss_allowance','credit_loss_allowance','recognized'),
    (r'writeoff.*reinsurance|reinsurance.*writeoff', 'reinsurance_premium_writeoff','ceded','written_off'),
    (r'reinstatementpremium', 'reinstatement_premium','reinsurance_premium','reported'),
    (r'claimsandbenefitsincurredamountceded|cededloss|lossesceded', 'ceded_losses','ceded','recognized_reduction'),
    (r'(?:benefitsandclaimsincurred|catastrophe.*loss|claim.*loss).*gross|gross.*(?:claims|loss)', 'claims_losses_and_lae','gross','incurred_estimate'),
    (r'(?:benefitsandclaimsincurred|catastrophe.*loss|claim.*loss).*net|net.*(?:claims|loss)', 'claims_losses_and_lae','net','incurred_estimate'),
    (r'catastrophe.*loss|catastrophe.*claim|hurricane.*loss', 'catastrophe_losses',None,'reported'),
]
def names(text):
    return {m[1].lower() for m in NAMED.finditer(text) if m[1].lower() not in {'losses','loss','claims','season','and','activity','damage','winds','insurance','reinsurance','warning','event','events','exposure','risk','risks','coverage'}}
def single_event(text, event):
    label = re.escape(event)
    match = re.search(r'\b'+label+r'\b', text, CASE)
    if not match:
        return False
    if names(text) - {event.lower()}:
        return False
    # Joint names may share a single prefix, e.g. "Hurricanes Harvey and Irma".
    if re.search(r'\b(?i:hurricanes?|tropical storms?)\s+[A-Z][a-z-]+(?:,\s*|\s+(?:and|&)\s+)(?:Hurricane\s+)?[A-Z][a-z-]+',text):
        return False
    if re.search(r'\b[A-Z][a-z-]+\s+and\s+'+label+r'\b|\b'+label+r'\s+and\s+[A-Z][a-z-]+\b',text):
        return False
    return True
def human(name):
    local = name.split(':')[-1].removesuffix('Member')
    return re.sub(r'(?<=[a-z])(?=[A-Z])',' ',local).replace('Incorporation','Inc.').strip()
def money_value(value):
    d=Decimal(str(value))
    return int(d) if d==d.to_integral() else float(d)
def sentence_pieces(text):
    return [s for s in SENTENCE.split(text) if s]
def sentence_for(text, pos):
    last=0
    for m in SENTENCE.finditer(text):
        if pos<m.start(): return text[last:m.start()]
        last=m.end()
    return text[last:]
def filing_context(rows):
    event=rows[0]['event']
    sentences=[s for row in rows if event.lower() in row['text'].lower() for s in sentence_pieces(row['text'])]
    quarter, date_literal, timing_evidence=legacy.storm_timing(sentences,event)
    return quarter,date_literal,timing_evidence
def base_record(row, metric, basis, status, value, quarter, evidence, channel):
    return dict(doc_id=row['doc_id'],passage_id=row['passage_id'],source_url=row['source_url'],accession=row.get('accession'),
                issuer=row['issuer'],reporting_issuer=row['issuer'],entity_scope='reporting_group',event=row['event'],
                measure=metric,basis=basis,status=status,period=quarter,event_quarter=quarter,recognition_period=None,
                low_usd=value,high_usd=value,bound_type='point',evidence=evidence,event_evidence=row['text'],
                amount_text=None,tax_basis=None,review=False,review_reasons=[],source_channel=channel)
def concept_terms(f):
    key=f['concept'].split(':')[-1].lower()
    return next(((metric,basis,status) for pattern,metric,basis,status in CONCEPTS if re.search(pattern,key)),None)
def tag_records(row, tags, positions, quarter):
    text=row['text']
    event=row['event']
    simple=re.sub('[^a-z0-9]','',event.lower())
    whole_event=single_event(text,event)
    records=[]
    for f,pos in zip(tags,positions):
        terms=concept_terms(f)
        if not terms: continue
        dim=f['dimensions']
        peril=[v.split(':')[-1].lower() for k,v in dim.items() if re.search(r'catastroph|hurricane|tropicalstorm|namedstorm|peril',k,CASE)]
        # Compare full member labels to avoid matching e.g. the target "Ian" in a longer name.
        specific={simple+'member', 'hurricane'+simple+'member','tropicalstorm'+simple+'member','typhoon'+simple+'member','cyclone'+simple+'member'}
        tagged=any(v in specific for v in peril)
        generic=all(v in {'hurricanemember','catastrophemember','floodmember','stormmember','tropicalstormmember','windmember'} for v in peril)
        sentence=sentence_for(text,pos)
        if not tagged and not (generic and whole_event): continue
        metric,basis,status=terms
        # An unqualified tag in a mixed paragraph needs a local causal statement.
        local=single_event(sentence,event)
        if not tagged and not peril and not local:
            if not (metric in {'reinstatement_premium','reinsurance_premium_writeoff'} and re.search(r'reinsurance|coverage',sentence,CASE) and whole_event):
                continue
        if not tagged and not local and peril and not re.search(r'(?:loss|incur|reinsur|retained|allowance)',sentence,CASE): continue
        if not tagged and not peril and re.search(r'polici(?:es|y) in force|number of policies|prior.period development',sentence,CASE): continue
        if not tagged and not peril and len(list(MONEY.finditer(sentence)))>1:
            continue
        value=money_value(f['normalized_usd'])
        if value==0: continue  # comparative dashes are outside single-event money scope
        affected=[human(v) for k,v in dim.items() if re.search(r'legalentity|businesssegment|reportablesegment|operatingsegment',k,CASE)]
        if len(affected)>1: continue
        if 'floodmember' in peril and 'retained' in sentence.lower(): metric='retained_flood_losses'; status='reported'
        if metric=='reinstatement_premium' and re.search(r'elected to pay',sentence,CASE): status='elected_to_pay'
        if basis=='gross' and re.search(r'estimat',sentence,CASE): status='estimate'
        rec=base_record(row,metric,basis,status,value,quarter,sentence,'inline_xbrl')
        if affected:
            rec['issuer']=affected[0]; rec['entity_scope']='named_segment_or_subsidiary'
        rec.update(amount_text=f['printed'],source_fact_id=f['fact_id'],concept=f['concept'],context_id=f['context'],
                   reporting_period_start=f['start'],reporting_period_end=f['end'],dimensions=dim,scale=f['scale'],currency='USD',
                   tax_basis='pretax' if re.search(r'pre[- ]?tax',sentence,CASE) or (re.search(r'on a pre[- ]?tax consolidated basis',text,CASE) and not affected and basis in {'net','gross'}) else None,
                   approximate_amount=bool(re.search(r'approximat',sentence,CASE)))
        records.append(rec)
    return records

def row_scale(rows,index):
    """Only carry narrative-wide currency headings, never an unrelated table's scale."""
    for k in range(index,max(-1,index-140),-1):
        t=rows[k]['text']
        if len(t)>280 or rows[k]['kind']=='table_row': continue
        m=re.search(r'\b(?:dollars?|amounts?|figures?|values?)\s+(?:presented |shown |expressed )?(?:are |stated )?in (thousands|millions|billions)\b',t,CASE)
        if m and not re.search(r'following|below|table|reconcil|summari[sz]|sets? forth|presents?|schedule',t,CASE): return SCALE[m[1].lower().rstrip('s')],rows[k]['passage_id']
        if k<index and re.search(r'management.s discussion and analysis|consolidated statements of (?:income|cash flows)',t,CASE): break
    return 1,None
def owner_in(previous):
    patterns=[r'(?:losses and loss adjustment expenses|losses and LAE)\s+(?:of|for)\s+([A-Z][A-Za-z&.-]+)(?:\s+Insurance Operations)?',
              r'\b([A-Z][A-Za-z&.-]+)\s+(?:insurance operations\s+)?losses and (?:loss adjustment expenses|LAE)']
    for k,pattern in enumerate(patterns):
        match=re.search(pattern,previous,CASE)
        if match:
            candidate=match[1].strip('.,')
            if candidate.lower() not in {'our','the','consolidated','net','gross','incurred','for','from','total','all','the','claim','insurance','were'}: return candidate
    return None
def claim_narrative(row,index,rows,quarter):
    event=row['event']; text=row['text']; out=[]
    prev=''
    for sentence in sentence_pieces(text):
        if not single_event(sentence,event):
            prev=sentence;continue
        owner=owner_in(prev)
        for m in MONEY.finditer(sentence):
            after=sentence[m.end():]
            # Direct attribution to the amount, before any competing amount or comma-separated cause.
            directed=re.match(r'\s*(?:of |in )?(?:pre[- ]?tax |net |gross |catastrophe |insured |estimated )*(?:(?:net )?loss(?:es)?(?: and (?:loss adjustment expenses|LAE))?|claims?|damages?|costs?)\s+(?:primarily\s+)?(?:directly\s+)?(?:attributable to|due to|related to|from|caused by|resulting from|associated with)\s+(?:the\s+effects? of\s+)?(?:Hurricane |Tropical Storm |Typhoon |Cyclone )?'+re.escape(event)+r'\b',after,CASE)
            if not directed: continue
            unit=SCALE.get((m[2] or '').lower())
            scope=None
            if unit is None:
                if ',' not in m[1] and not owner: continue
                unit,scope=row_scale(rows,index)
            value=money_value(Decimal(m[1].replace(',',''))*unit)
            rec=base_record(row,'segment_claims_expense' if owner else 'claims_losses', 'segment_expense' if owner else None,'recognized_expense' if owner else 'reported',value,quarter,sentence,'attributed_clause')
            rec.update(amount_text=m[0].strip(), unit_heading_passage=scope, bound_type='point', approximate_amount=bool(re.search(r'approximately\s*$',sentence[:m.start()],CASE)))
            if owner: rec.update(issuer=owner,entity_scope='named_segment_or_subsidiary',entity_evidence=prev)
            out.append(rec)
        prev=sentence
    return out

def prose_loss(row,index,rows,quarter):
    """Single-cause, explicitly quantified prose, including named storms in a list."""
    event=row['event']; out=[]; text=row['text']
    for sentence in sentence_pieces(text):
        # Split only where a clause explicitly starts another named storm. A shared
        # sum for "Hurricanes A and B" remains one ambiguous clause.
        clauses=re.split(r';\s*|,\s*(?:and\s+)?(?=Hurricane\s+[A-Z][a-z-]+\s+(?:accounted|resulted|caused|generated))',sentence)
        for clause in clauses:
            if not single_event(clause,event): continue
            hits=list(MONEY.finditer(clause))
            if len(hits)!=1: continue
            m=hits[0]
            if not re.search(r'\b(?:claims|loss(?:es)?|loss adjustment expenses|retention|retained)\b',clause,CASE): continue
            if re.search(r'industry|policy limit|coverage of up to|net income|income tax expense|market[- ]wide|reinsurance limit|aggregate limit|previously accrued benefits|coverage was exhausted|allowance for credit losses|number of policies|annual aggregate deductible',clause,CASE): continue
            if not re.search(r'(?:loss|claim|retention|retained|incurr|impact|accounted|caused|attributable|attributed|resulted|estimated).{0,90}\$\s*\d|\$\s*[\d,.]+\s*(?:million|billion|thousand)?\s+(?:of |in )?(?:catastrophe |net |gross |pre[- ]?tax )*(?:claims|loss|retained|from)',clause,CASE): continue
            if re.search(r'(?:and|including|primarily from|combined|total for)\s+(?:other|both|the two|multiple)\b',clause,CASE): continue
            unit=SCALE.get((m[2] or '').lower()); scope=None
            if unit is None:
                unit,scope=row_scale(rows,index)
                if not scope and ',' not in m[1]: continue
            raw=money_value(Decimal(m[1].replace(',',''))*unit)
            before=clause[:m.start()]
            after=clause[m.end():]
            if re.search(r'(?:between|from|to)\s*$',after[:20],CASE) or re.match(r'\s*(?:-|–|to\b)\s*\d',after,CASE): continue
            if re.search(r'\b(?:including|excluding|in addition to)\s*$',before,CASE): continue
            if re.search(r'\b(?:future|coverage|maximum)\b',clause,CASE) and not re.search(r'\b(?:retention|incur|expect)',clause,CASE):continue
            basis='net' if re.search(r'\bnet\b|retention|retained|after reinsurance',clause,CASE) else ('gross' if re.search(r'\bgross\b|before reinsurance',clause,CASE) else None)
            metric='retention' if re.search(r'\bretention\b',clause,CASE) else 'claims_losses_and_lae' if re.search(r'LAE|adjustment expenses',clause,CASE) else 'claims_losses'
            status='forecast' if re.search(r'\bexpect|project|anticipat',clause,CASE) else 'estimate' if re.search(r'estimat',clause,CASE) else 'incurred' if re.search(r'incur|recogniz|recorded',clause,CASE) else 'reported'
            rec=base_record(row,metric,basis,status,raw,quarter,clause,'single_cause_prose')
            lo,hi,bound=raw,raw,'point'
            if re.search(r'(?:at least|more than|over|in excess of|no less than)\s*$',before,CASE):
                hi,bound=None,'lower_bound'
            elif re.search(r'(?:at most|up to|less than|no more than)\s*$',before,CASE):
                lo,bound=None,'upper_bound'
            rec.update(low_usd=lo,high_usd=hi,bound_type=bound,amount_text=m[0].strip(),unit_heading_passage=scope,tax_basis='pretax' if re.search(r'pre[- ]?tax',clause,CASE) else None)
            out.append(rec)
    return out

def table_columns(values, cells, previous, caption, row, quarter, unit, unit_id):
    """Resolve dollars only for aligned, labelled columns, leaving counts and dates out."""
    result=[]
    for col, literal, val in values:
        labels=[]
        for hist in previous:
            if hist['kind']!='table_row': continue
            hcells=[c.strip() for c in hist['text'].split('|')]
            if len(hcells)!=len(cells) or col>=len(hcells): continue
            candidate=hcells[col]
            if not 1<=len(candidate)<=130: continue
            if re.search(r'gross|net\b|paid|incurred|tax|ceded|adjustment expense|recoveries|claims count|number of claims', candidate, CASE):
                # A row containing figures is data, not a column header.
                if not any(re.fullmatch(r'\$?\s*[\d,.]+',v) and ',' in v for v in hcells):
                    labels.append((candidate,hist['passage_id']))
        if not labels: continue
        label,pid=labels[-1]
        if re.search(r'number|count|ratio|percent|per share|industry',label,CASE): continue
        basis='gross' if re.search(r'gross|before reinsurance',label,CASE) else 'net' if re.search(r'\bnet\b|after reinsurance|retained',label,CASE) else 'ceded' if re.search(r'ceded|recover',label,CASE) else None
        if basis is None and not re.search(r'paid|incurred',label,CASE):continue
        metric='paid_claims' if re.search(r'\bpaid\b',label,CASE) else 'ceded_losses' if basis=='ceded' else 'catastrophe_losses'
        status='paid' if metric=='paid_claims' else 'incurred' if re.search(r'incurred',label+' '+caption['text'],CASE) else 'reported'
        rec=base_record(row,metric,basis,status,money_value(val*unit),quarter,row['text'],'labelled_table_column')
        rec.update(amount_text=literal,metric_heading_passage=pid,unit_heading_passage=unit_id,column_evidence=label,
                   tax_basis='after_tax' if re.search(r'after[- ]tax',label,CASE) else 'pretax' if re.search(r'(?:pre|before)[- ]tax',label,CASE) else None)
        result.append(rec)
    return result


def plain_table(row,index,rows,quarter):
    event=row['event']; text=row['text']
    if row['kind']!='table_row' or not single_event(text,event):return []
    cells=[c.strip() for c in text.split('|')]
    if not any(single_event(c,event) and len(c)<100 for c in cells):return []
    previous=[r for r in rows[max(0,index-18):index] if len(r['text'])<650]
    captions=[r for r in previous if re.search(r'\b(?:catastrophe|catastrophic|storm|hurricane).{0,55}(?:losses|claims)|(?:losses|claims).{0,55}(?:catastroph|storm|hurricane)',r['text'],CASE) and not MONEY.search(r['text'])]
    if not captions:return []
    caption=captions[-1]
    if re.search(r'industr[yia]|market.wide|all insurers|economic damage|return period',caption['text'],CASE):return []
    unit=unit_id=None
    for near in reversed(previous+[row]):
        m=re.search(r'\b(?:in |amounts? in |dollars? in |US\$ )?(millions|thousands|billions)\b',near['text'],CASE)
        if m and len(near['text'])<450:
            unit=SCALE[m[1].lower().rstrip('s')];unit_id=near['passage_id'];break
    if not unit:return []
    # Multiple numbers with uncovered column headers (years, ranges, counts) are
    # unsafe to attribute. A tagged statement may still supply those records.
    values=[]
    for col,cell in enumerate(cells):
        m=re.fullmatch(r'\$?\s*(\(?)([\d,.]+)(\)?)',cell)
        if m and bool(m[1])==bool(m[3]) and not re.fullmatch(r'(?:19|20)\d{2}',m[2]):
            value=Decimal(m[2].replace(',',''))*(-1 if m[1] else 1)
            if value: values.append((col,cell,value))
    if not values:return []
    labelled=table_columns(values,cells,previous,caption,row,quarter,unit,unit_id)
    if labelled:return labelled
    if len(values)!=1:return []
    val=money_value(values[0][2]*unit)
    if not val:return []
    label=caption['text']+' '+text
    basis='net' if re.search(r'\bnet\b|after reinsurance|retained',label,CASE) else 'gross' if re.search(r'\bgross\b|before reinsurance',label,CASE) else None
    if basis is None: return []
    rec=base_record(row,'catastrophe_losses',basis,'incurred' if re.search(r'incurred',label,CASE) else 'reported',val,quarter,text,'single_value_table')
    rec.update(amount_text=values[0][1],unit_heading_passage=unit_id,metric_heading_passage=caption['passage_id'])
    return [rec]

def prefer_records(items):
    # Same metric and same amount within one filing may be repeated. Keep all evidence
    # for audit; do not collapse different measures that share a dollar value.
    unique={}
    for r in items:
        label=(r['doc_id'],r['issuer'],r['measure'],r.get('basis'),r['low_usd'],r['high_usd'],r['status'],r.get('period'),r['review'])
        definite_tax=r.get('tax_basis')
        if label in unique and definite_tax and unique[label].get('tax_basis') not in {None,definite_tax}: label=label+(definite_tax,)
        if label not in unique:
            unique[label]=r
            r['evidence_passage_ids']=[r['passage_id']]
        else:
            old=unique[label]
            if definite_tax and not old.get('tax_basis'):old['tax_basis']=definite_tax
            if r['passage_id'] not in old['evidence_passage_ids']:old['evidence_passage_ids'].append(r['passage_id'])
    return list(unique.values())

def load_marks(rows, raw):
    if rows[0].get('source_sha256') and hashlib.sha256(raw).hexdigest()!=rows[0]['source_sha256']:
        raise ValueError('Primary filing digest mismatch: '+rows[0]['doc_id'])
    parser=TaggedText()
    try: text=raw.decode('utf8')
    except UnicodeDecodeError:text=raw.decode('cp1252')
    parser.feed(text);parser.close();parser.flush()
    if len(parser.rows)!=len(rows) or any(group[2]!=r['text'] for group,r in zip(parser.rows,rows)):
        raise ValueError('Primary HTML and passage manifest disagree: '+rows[0]['doc_id'])
    try:
        fact_index={f['fact_id']:f for f in usd_facts(raw,rows[0].get('accession')) if f['fact_id']}
    except (ET.ParseError,ValueError):
        fact_index={}  # untagged legacy HTML; no units are guessed from broken tags
    return [[(fact_index[key],pos) for key,pos in marks if key in fact_index] for marks in parser.row_facts]

def normalized_evidence(text):
    words=set(re.findall(r'[a-z]+',text.lower()))
    return words-{'a','the','an','and','of','were','was','we','company','in','to','by','on','million','thousand','usd'}

def repeats_tag(candidate, tagged, same_passage=False):
    """Require source wording or accounting identity in addition to a matching amount."""
    words=normalized_evidence(candidate['evidence'])
    for fact in tagged:
        other=normalized_evidence(fact['evidence'])
        common=len(words & other)/max(1,len(words | other))
        printed=fact.get('amount_text','').replace(',','').strip()
        candidate_print=re.sub(r'[^0-9.]','',candidate.get('amount_text') or '')
        same_value=(candidate['low_usd'],candidate['high_usd'])==(fact['low_usd'],fact['high_usd'])
        if not (same_value or (same_passage and printed and candidate_print==printed)):continue
        if candidate.get('basis') and fact.get('basis') and candidate['basis']!=fact['basis']:continue
        if candidate.get('entity_scope')=='named_segment_or_subsidiary' and candidate['issuer'].replace(' ','').lower()!=fact['issuer'].replace(' ','').lower():continue
        if common>0.68: return True
    return False

def extract_filing(rows,raw):
    quarter,_,_=filing_context(rows)
    marked=load_marks(rows,raw)
    initial=defaultdict(list)
    for rec in legacy.extract(rows):
        initial[rec['passage_id']].append(rec)
    outputs=[]; rich=[]
    for idx,row in enumerate(rows):
        marks=marked[idx]
        tagged=tag_records(row,[x[0] for x in marks],[x[1] for x in marks],quarter)
        directed=claim_narrative(row,idx,rows,quarter)
        clause=prose_loss(row,idx,rows,quarter)
        table=plain_table(row,idx,rows,quarter)
        rich.append((tagged,directed,clause,table))
    all_tagged=[r for tagged,_,_,_ in rich for r in tagged]
    for idx,row in enumerate(rows):
        tagged,directed,clause,table=rich[idx]
        if tagged:
            outputs.extend(tagged)
            # A paragraph may combine tagged information with independent untagged
            # disclosures. Preserve these; weak mixed-cause proposals go to review.
        directed=[r for r in directed if not repeats_tag(r,tagged,True)]
        if directed and any(r['entity_scope']=='named_segment_or_subsidiary' for r in directed):
            outputs.extend(directed)
            continue
        clause=[r for r in clause if not repeats_tag(r,tagged,True) and not repeats_tag(r,all_tagged)]
        prior=[r for r in initial[row['passage_id']] if not repeats_tag(r,tagged,True) and not repeats_tag(r,all_tagged)]
        if tagged:
            for r in prior:
                r['review']=True
                r['review_reasons']=list(dict.fromkeys(r.get('review_reasons',[])+['unreconciled prose beside tagged values']))
            table=[r for r in table if not repeats_tag(r,tagged,True)]
        if table:outputs.extend(table);continue
        # Disjoint established insurer facts: preserve the older open-range and retention rules.
        auto=[r for r in prior if not r['review']]
        if auto:
            # Preserve forecasts and explicitly typed insurance amounts. Cross-sentence
            # attribution with multiple alternative causes is not an automatic record.
            for r in prior:
                if re.search(r'greater number of|policies in force|prior period loss',r['evidence'],CASE) and len(list(MONEY.finditer(r['evidence'])))>1:continue
                r.update(source_channel='legacy_evidence',accession=row.get('accession'))
                outputs.append(r)
            continue
        if clause:outputs.extend(clause);continue
        for r in prior:
            r.update(source_channel='legacy_evidence',accession=row.get('accession'))
            outputs.append(r)
    policy=next((a for a in rows if re.search(r'ceded losses.{0,200}reductions in losses and (?:loss adjustment expenses|LAE)',a['text'],CASE)),None)
    for r in outputs:
        if r['measure']=='segment_claims_expense' and policy:
            r.update(basis='segment_expense_after_cessions',basis_evidence_passage=policy['passage_id'],basis_source='inferred_from_filing_policy')
        if r.get('entity_scope')=='named_segment_or_subsidiary':
            plain=r['issuer'].replace(' ','')
            printed=re.search(r'\b'+re.escape(plain)+r'\b',r['evidence'],CASE)
            if printed:r['issuer']=printed[0]
        if r['measure'] in {'ibnr_and_development','paid_claims_and_allocated_expense','unpaid_claims_liability','incurred_claims_and_allocated_expense'}:
            r['as_of_date']=r.get('reporting_period_end')
        r['reporting_period']=None
        r['reporting_period_source']=None
        # Filing cover date is a reporting label only. It never dates the landfall
        # or turns an expected charge into a current-period payment.
        title=next((x for x in rows[:80] if re.search(r'(?:quarterly period|fiscal year|year) ended',x['text'],CASE) and legacy.EVENT_DATE.search(x['text'])),None)
        if title:
            md=legacy.EVENT_DATE.search(title['text'])
            yr=int(md[3]);mo=legacy.MONTHS[md[1].lower()]
            r['reporting_period']='FY'+str(yr) if rows[0].get('source_kind')=='10-K' else f'{yr}-Q{(mo-1)//3+1}'
            r['reporting_period_source']=title['passage_id']
        ordinals={'first':1,'second':2,'third':3,'fourth':4}
        match=re.search(r'(?:during|in|for) the (first|second|third|fourth) quarter (?:of )?(20\d\d)',r['evidence'],CASE)
        if match and r['source_channel']!='legacy_evidence':
            r['recognition_period']=f'{match[2]}-Q{ordinals[match[1].lower()]}'
    return prefer_records(outputs)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('primary',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    docs=defaultdict(list)
    for line in args.input.read_text(encoding='utf-8-sig').splitlines():
        if line.strip():
            row=json.loads(line)
            docs[row['doc_id']].append(row)
    result=[]
    for key, rows in docs.items():
        result.extend(extract_filing(rows,(args.primary/(key+'.htm')).read_bytes()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    display=json.dumps(result,indent=2,ensure_ascii=False)+'\n'
    args.output.write_text(display,encoding='utf-8')

if __name__=='__main__':main()


