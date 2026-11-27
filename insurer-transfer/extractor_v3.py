"""Evidence-linked extraction of storm-related US-dollar estimates and charges.

Usage: python extractor_v3.py input.jsonl output.json
Input rows carry doc_id, passage_id, text, event, issuer and source_url, in reading
order. Output is at mention level: repeated publications are preserved. Only rows
with review=false are automatic records. Unspecified impact periods remain null.
"""
import argparse
import calendar
import json
import os
import re
import tempfile
from decimal import Decimal
from pathlib import Path

NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
UNIT = r"(?:billion|million|thousand|trillion|bn|mn|mm|[BMK])\b"
MONEY = re.compile(
    rf"(?<![\w$])(?:US\$|\$|USD\s*)\s*(?P<a>{NUMBER})"
    rf"(?:\s*(?P<u>{UNIT}))?(?:\s*(?:to\b|[-–—])\s*(?:US\$|\$|USD\s*)?"
    rf"\s*(?P<b>{NUMBER})(?:\s*(?P<v>{UNIT}))?)?", re.I)
SCALES = {"thousand":1000, "k":1000, "million":10**6, "m":10**6,
          "mn":10**6, "mm":10**6, "billion":10**9, "b":10**9, "bn":10**9, "trillion":10**12}
SENTENCES = re.compile(r"(?<!\bInc)(?<!\bCorp)(?<!\bCo)(?<=[.!?])\s+(?=[A-Z(])")
OTHER_STORM = re.compile(r"\b(?:Hurricane|Tropical Storm|Winter Storm|Typhoon|Cyclone|Superstorm)s?\s+([A-Z][a-z]+)")
QUARTERS = {"first":"1", "second":"2", "third":"3", "fourth":"4"}
MONTHS = {s.lower():i for i,s in enumerate(calendar.month_name) if s}
FORECAST = re.compile(r"\b(?:anticipat(?:e|es|ed)|forecast(?:s|ed)?|project(?:s|ed)?|expect(?:s|ed)?|will|likely to|outlook)\b", re.I)
ESTIMATE = re.compile(r"\b(?:estimat(?:e|es|ed|ing)|preliminary|projected)\b", re.I)
RECOGNIZED = re.compile(r"\b(?:recorded|recognized|recognised|expensed|charged|wrote off|booked|cash received|received|paid|incurred)\b", re.I)
PAST = re.compile(r"\b(?:resulted in|experienced|were impacted|had|were adversely|was adversely|results.{0,35}included|period ended|months ended)\b", re.I)
REFERENCE = re.compile(r"\b(?:the|this|that|the two|both) (?:hurricanes?|storms?|fires?|disasters?|floods?)\b|\b(?:storm[- ]related|hurricane[- ]related|as a result|in connection with|restoration costs?|preliminary estimate for|non-fuel revenue|corresponding regulatory assets)\b", re.I)
DENIAL = re.compile(r"\b(?:unrelated to|not (?:caused by|attributable to|associated with|due to)|excluding|prior to the|susceptible to|if a hurricane|may be exposed|not yet (?:recorded|recognized|received))\b", re.I)
NEGATIVE_ROLE = re.compile(r"\b(?:purchase price|credit facilit(?:y|ies)|available liquidity|revolving credit|(?:restricted |storm )escrow(?:s| accounts?)?|securitiz(?:ation|e)|interim financing|issuance|bond(?:s| issuance)|capital investment plan|share repurchase|dividend|aggregate policy limit|policy limit|borrowing capacity|underwriting capacity|insurance deductible|retention limit|invested|market capitalization|five years of investments?)\b", re.I)
THIRD_PARTY = re.compile(r"\b(?:industry(?:wide|[- ]wide| losses)|nationwide losses|economy[- ]wide|customers?' insurance|competitor(?:’s|'s)|shareholders?.{0,30}(?:committ|donat)|state.{0,15}request|all insurers|reinsurance industry)\b", re.I)
NAMED_ENTITY = r"[A-Z][\w.&'-]*(?:\s+[A-Z][\w.&'-]*){0,4}"
ROLES = [
    ("insurance_recovery",r"(?:business interruption |property )?insurance (?:recover(?:y|ies)|proceeds|payments?|reimbursements?)|(?:recoveries|reimbursements?) from (?:our )?insur(?:ance|ers?)"),
    ("claims_losses",r"(?:net |gross |insured )?(?:catastroph(?:e|ic)|cat |storm|insured|underwriting) losses|(?:loss(?:es)? and loss adjustment expenses?|claims? (?:costs?|losses|payments?)|(?:storm[- ]related|catastrophe|insured) claims|gross ultimate losses?|(?:pre[- ]tax |pretax |economic |insured |after[- ]tax |net |gross )+loss(?:es)?|losses? (?:attributable|related|due) to)"),
    ("restoration_costs",r"restoration (?:and repair )?costs?|costs? (?:of|for|to) (?:the )?(?:restor(?:e|ation|ing)|repair(?:s|ing)?|rebuild(?:ing)?|reconstruct(?:ion)?|remediat(?:e|ion))|repair and (?:replacement|restoration) costs?|property damage and remediation costs?|remediation costs?"),
    ("lost_revenue",r"(?:lost|foregone|forgone|missed|reduced|lower|deferred) (?:non[- ]fuel |operating |net |rental )?(?:revenues?|sales)|loss(?:es)? (?:of|in) (?:non[- ]fuel |operating |net )?(?:revenues?|sales)|(?:revenues?|sales) (?:loss(?:es)?|reduction|decline)|(?:negatively|adversely) (?:affected|impacted) (?:our |its )?(?:revenues?|sales)|(?:revenues?|sales).{0,35}(?:negatively|adversely) (?:affected|impacted)|impact (?:on|to) (?:net |segment )?(?:revenues?|sales)"),
    ("expenses",r"(?:incremental|additional|remediation|repair|response|restoration|storm[- ]related|hurricane[- ]related|catastrophe[- ]related) (?:operating )?(?:expenses?|costs?)|(?:pre[- ]tax |pretax |net |storm[- ]related )+charges?|(?:damage|loss) (?:to|of) (?:property|inventory|equipment)|(?:inventory|asset|property) write[- ]offs?"),
    ("property_damage",r"(?:estimated |total )?(?:physical |property )?damage (?:was|is|of|estimated|totaled|to our)|insured property damage|damage estimates?"),
    ("business_interruption",r"business interruption (?:loss(?:es)?|costs?|expense|impact)"),
    ("earnings_impact",r"(?:reduc(?:ed|tion (?:to|in))|adverse impact (?:on|to)|negative(?:ly)? impact(?:ed)?|impact (?:on|to)) (?:our |its )?(?:adjusted )?(?:operating income|net income|profit|EBITDA|earnings)"),
    ("regulatory_asset",r"regulatory assets?"),
    ("construction_work_in_progress",r"construction work in progress"),
]
ROLES = [(name,re.compile(r"\b(?:"+pattern+r")\b",re.I)) for name,pattern in ROLES]

def numeric(raw, unit):
    value=Decimal(raw.replace(",",""))*SCALES.get((unit or "").lower(),1)
    return int(value) if value==value.to_integral_value() else float(value)

def money_mentions(text):
    for m in MONEY.finditer(text):
        if re.match(r"\s*(?:per |/|each\b|[%])",text[m.end():],re.I):
            continue
        if re.search(r"(?:\b(?:CAD|AUD|HKD|NZD)|\bper share of|[-−])\s*$",text[:m.start()],re.I):
            continue
        if m["b"] and m["u"] and not m["v"]:
            continue
        lo=numeric(m["a"],m["u"] or m["v"]); hi=numeric(m["b"],m["v"]) if m["b"] else lo
        if m["b"] and re.search(r"(?<!range )\bfrom\s*$",text[:m.start()],re.I):
            continue
        if lo<=hi:
            yield m,lo,hi

def reporting_period(sentence):
    periods=set()
    for q,year in re.findall(r"\bQ([1-4])\s+(?:of )?(20\d\d)\b",sentence,re.I):
        periods.add(f"{year}-Q{q}")
    for q,year in re.findall(r"\b(first|second|third|fourth)[- ]quarter(?:\s+(?:results\s+)?(?:of |for )?)(20\d\d)\b",sentence,re.I):
        periods.add(f"{year}-Q{QUARTERS[q.lower()]}")
    for month,year in re.findall(r"three months ended\s+([a-z]+)\s+\d{1,2},?\s+(20\d\d)",sentence,re.I):
        if month.lower() in MONTHS:
            periods.add(f"{year}-Q{(MONTHS[month.lower()]-1)//3+1}")
    for y in re.findall(r"(?:full[- ]year|fiscal year|year ended [A-Za-z]+ \d{1,2},?)\s+(20\d\d)",sentence,re.I):
        periods.add(y)
    if not periods:
        periods.update(re.findall(r"(?:revenues?|sales|income|expenses?|costs?) (?:in|for) (20\d\d)\b",sentence,re.I))
    return next(iter(periods)) if len(periods)==1 else None

def role_for(left,right):
    hits=[]
    # Stop before the subject switches to a different monetary assertion.
    for role,pattern in ROLES:
        for m in pattern.finditer(left):
            hits.append((len(left)-m.end(),role))
        for m in pattern.finditer(right):
            if m.start()<60 and re.match(r"^\s*(?:of|in|for|from|related to|in the form of|attributable to|was|were|is|are)\b",right,re.I):
                hits.append((m.start()+3,role))
    roles={name for _,name in hits}
    if "lost_revenue" in roles and "expenses" in roles and re.search(r"\b(?:together with|additional expenses and|expenses and (?:experienced )?los[st]|loss of revenues and)\b",left+" "+right,re.I):
        return "lost_revenue_and_response_expenses"
    if "restoration_costs" in roles and roles <= {"expenses","restoration_costs"}: return "restoration_costs"
    if "insurance_recovery" in roles and roles <= {"expenses","insurance_recovery"}: return "insurance_recovery"
    if not hits: return None
    return min(hits)[1]

def event_flags(text,event):
    key=event.casefold().strip()
    explicit=bool(re.search(r"(?<!\w)"+re.escape(key)+r"(?!\w)",text,re.I))
    head=re.sub(r"^(?:hurricane|tropical storm|winter storm|typhoon|cyclone|superstorm)\s+","", key)
    others={n.casefold() for n in OTHER_STORM.findall(text) if n.casefold()!=head}
    for pair in re.finditer(r"\b(?:Hurricanes?|Tropical Storms?|Winter Storms?|Typhoons?|Cyclones?)\s+([A-Z][a-z]+)\s+(?:and|&)\s+([A-Z][a-z]+)\b",text):
        others.update(n.casefold() for n in pair.groups() if n.casefold()!=head and n not in {'Hurricane','Tropical','Storm','Winter','Typhoon','Cyclone'})
    return explicit,others

def status_for(left,right,ctx):
    scope=left+" "+right
    # The status of an estimate concerns this measure. A past landfall date is not recognition.
    if ESTIMATE.search(scope):
        if FORECAST.search(scope) and not PAST.search(scope): return "forecast"
        if PAST.search(scope): return "past_estimate"
        return "estimate"
    if FORECAST.search(scope): return "forecast"
    if re.search(r"\b(?:had |has |have |already )?received\b",scope,re.I) and re.search(r"\b(?:insurance|insurer|proceeds|recover)",scope,re.I): return "received"
    if re.search(r"\bpaid\b",scope,re.I) and re.search(r"\b(?:claims?|losses|expenses|cash)\b",scope,re.I): return "paid"
    if RECOGNIZED.search(scope): return "booked"
    if ctx and (ESTIMATE.search(ctx) or FORECAST.search(ctx)):
        return "forecast" if FORECAST.search(ctx) else "estimate"
    return "unknown"

def entity_for(left, issuer, preceding):
    # Examples: 'the estimate for Utility Louisiana is $x'; use the displayed name verbatim.
    m=re.search(r"\b(?:estimate for|estimated costs? for|losses for)\s+("+NAMED_ENTITY+r")\s+(?:is|was|are|were|of|at)\s*$",left)
    if m: return m[1]
    group_word=re.search(r"[A-Za-z]{3,}",issuer)
    if group_word and re.search(r"\b(?:total |estimated |preliminary )?(?:restoration costs?|insurance recoveries|lost .{0,15}revenues?)",left,re.I):
        stem=re.escape(group_word.group().title())
        owners=re.findall(r"\b("+stem+r"(?: [A-Z][A-Za-z-]*){1,3})(?:[’']s|[’'])\s+(?:distribution|transmission|service|retail|revenues?|electri|facilit|operations?)", preceding)
        if len(set(owners))==1: return owners[-1]
    return issuer

def extract_general(rows):
    outputs=[]
    previous_key=None
    prior=""
    for row in rows:
        key=(row["doc_id"],row["event"],row["issuer"])
        if not str(row["event"]).strip():
            raise ValueError("Missing target event")
        if key!=previous_key:
            prior=""
        previous_key=key
        text=row["text"]
        local_context=prior
        last_sentence=""
        last_role=None
        last_status=None
        for sentence in SENTENCES.split(text):
            explicit,other=event_flags(sentence,row["event"])
            prev_explicit,prev_other=event_flags(local_context,row["event"])
            is_continuation=REFERENCE.search(sentence) or re.search(r"\b(?:initial estimate|restoration|recovery efforts|damage assessment|associated expenses)\b",sentence,re.I)
            heading=prev_explicit and len(local_context.split())<=5
            active=explicit or (prev_explicit and not prev_other and (is_continuation or heading))
            mentions=list(money_mentions(sentence))
            metric_context=role_for(sentence,"") if active else None
            if active and not other and not DENIAL.search(sentence):
                carried=last_role or role_for(local_context,"") if prev_explicit else last_role
                matches=[]
                for i,(m,lo,hi) in enumerate(mentions):
                    start=mentions[i-1][0].end() if i else 0
                    end=mentions[i+1][0].start() if i+1<len(mentions) else len(sentence)
                    left=re.split(r";|\b(?:whereas|whereupon|however)\b",sentence[start:m.start()],flags=re.I)[-1]
                    right=re.split(r";|\b(?:whereas|whereupon|however)\b",sentence[m.end():end],flags=re.I)[0]
                    # '..., of which ...' and joint amounts often lose entity or scope without table structure.
                    unsafe=re.search(r"\b(?:of which|respectively|including)\b",left,re.I) or re.search(r"\brespectively\b",right,re.I)
                    if NEGATIVE_ROLE.search(left) or re.match(r"\s*(?:of |in )?(?:shorter[- ]term )?(?:bonds?|(?:restricted |storm )escrow|credit facilit)",right,re.I) or THIRD_PARTY.search(sentence): continue
                    role=role_for(left,right)
                    entity=entity_for(left,row["issuer"],text[:text.find(sentence)])
                    if not role and re.search(r"\b(?:preliminary estimate for|initial estimate for|estimate for)\b",left,re.I):
                        role=carried or (matches[-1]["measure"] if matches else None)
                    if not role and matches and re.search(r"\brespectively\b",sentence,re.I):
                        role=matches[0]["measure"]
                        unsafe=True
                        entity=None
                    if not role:
                        continue
                    status=status_for(left,right,last_sentence if not explicit else "")
                    if status=="estimate" and not explicit and FORECAST.search(last_sentence) and role=="lost_revenue": status="forecast"
                    if status=="unknown" and last_status and re.search(r"initial estimate for|preliminary estimate for",left,re.I): status=last_status
                    reasons=[]
                    if unsafe: reasons.append("allocation needs review")
                    if status=="unknown": reasons.append("status not explicit")
                    if re.search(r"\b(?:if|may|might|could|pending approval|potential)\b",left,re.I): reasons.append("conditional")
                    if re.search(r"\b(?:up to|at least|over|more than|less than)\s*$",left,re.I): reasons.append("one-sided amount")
                    basis=sentence if explicit else local_context
                    hit=dict(doc_id=row["doc_id"],passage_id=row["passage_id"],source_url=row["source_url"],
                             event=row["event"],issuer=entity,reporting_issuer=row["issuer"],measure=role,
                             status=status,period=reporting_period(sentence) or (reporting_period(last_sentence) if not explicit and role=="lost_revenue" else None),low_usd=lo,high_usd=hi,
                             evidence=sentence,event_evidence=basis,amount_text=m.group(),review=bool(reasons),review_reasons=reasons)
                    outputs.append(hit)
                    matches.append(hit)
                if matches:
                    last_role=matches[-1]["measure"]
                    last_status=matches[-1]["status"]
            # Treat only tightly linked adjacent sentences as event context. Do not carry across headings or companies.
            if explicit and not other: local_context=sentence
            elif not (active and not other and (metric_context or is_continuation)):
                local_context=sentence
            last_sentence=sentence
        prior=text if len(text)<2200 else SENTENCES.split(text)[-1]
    return outputs

# Insurance disclosures use similar-looking numbers for liabilities, payouts and contract terms.
# Each insurance assertion below must supply a local financial role and a defensible event link.
INSURANCE_ROLE = re.compile(
    r"\b(?:gross (?:ultimate |insured |catastrophe )?loss(?:es)?|"
    r"net (?:pre[- ]?tax |ultimate |catastrophe |retained |insured )*(?:loss(?:es)?|exposure|retention)|"
    r"loss(?:es)? and (?:loss adjustment expenses?|LAE)|"
    r"(?:catastrophe|cat|insured|underwriting|retained) losses|"
    r"(?:insurance |reinsurance )?(?:retentions?|recoveries|recovery)|"
    r"(?:re)?insurance (?:proceeds|reimbursements?)|in claims\b|claims? (?:paid|incurred|losses|payments?)|losses (?:from|related to|resulting from|attributable to))\b", re.I)
OUT_OF_SCOPE = re.compile(
    r"\b(?:insurance industry|industry[- ]?(?:wide|losses|estimate)|the market|"
    r"combined (?:impact|effect)|combined (?:catastrophe )?losses from|aggregate reinsurance|"
    r"reinsurance (?:coverage|tower|program limit|layer)|credit (?:facility|agreement)|dividend|"
    r"total assets|net income|earnings per share|basic earnings|investment income|investment losses|"
    r"changes? in (?:fair value|reserve estimates) of prior|unrealized|acquisition (?:cost|price)|"
    r"equity securities|retention per occurrence|per[- ]occurrence retention|prior accident years|"
    r"would have been|if the storm|hypothetical|not attributable|unrelated to)\b", re.I)
CONDITION = re.compile(r"\b(?:if|could|might|may|subject to|depending on|to the extent)\b", re.I)
GENERIC = re.compile(r"\b(?:the|this|that|such) (?:named )?(?:hurricane|storm|catastrophe|event|flood|wildfire)\b", re.I)
INS_FUTURE = re.compile(r"\b(?:expect(?:s|ed|ing)?|anticipat(?:e|es|ed|ing)|forecast(?:s|ing)?|project(?:s|ed|ing)?|will)\b", re.I)
INS_EST = re.compile(r"\b(?:estimat(?:e|es|ed)|preliminary|ultimate|approximately|approximately|about)\b", re.I)
INS_CLAUSE = re.compile(r";|,\s*(?:resulting in|of which|with an? (?:anticipated|expected)|however|while|whereas)|"
                        r"\band\b(?=\s+(?:expect(?:s)?|anticipate(?:s)?|project(?:s)?)\s+(?:to |that |this |an? |the |our ))|"
                        r"\band\b(?=\s+(?:the (?:company|group)['’]s |our |its )?(?:net |gross |after[- ]tax |pre[- ]tax )(?:loss|retention|amount))", re.I)
MONTH = "|".join(calendar.month_name[1:])
AS_OF = re.compile(r"\bas (?:at|of)\s+("+MONTH+r")\s+(\d{1,2}),?\s+(20\d\d)\b", re.I)

def monetary_bounds(clause, m, lo, hi):
    prefix = clause[:m.start()]
    suffix = clause[m.end():]
    lower = re.search(r"\b(at least|no less than|not less than|in excess of|more than|over|exceed(?:s|ed)?|minimum of|minimum)\s*(?:approximately\s*)?$", prefix, re.I)
    upper = re.search(r"\b(up to|no more than|not more than|not (?:to |expected to )?exceed|less than|under|at most|limited to|maximum of)\s*(?:approximately\s*)?$", prefix, re.I)
    if lower and upper and lower.start()<upper.start():
        upper=None
    if upper or re.match(r"\s+or (?:less|lower|below)\b", suffix, re.I):
        return None, hi, "upper_exclusive" if upper and upper[1].lower() in {"less than","under"} else "upper_inclusive"
    if lower or re.match(r"\s+or (?:more|higher|greater|above)\b", suffix, re.I):
        strict = lower and lower[1].lower() in {"in excess of","more than","over","exceed","exceeds","exceeded"}
        return lo, None, "lower_exclusive" if strict else "lower_inclusive"
    return lo, hi, "range" if m["b"] else "point"

def insurance_period(text):
    period = reporting_period(text)
    if period:
        return period
    # Here the preposition explicitly attributes a measure to an accounting period.
    candidates = set(re.findall(r"\b(?:recorded|recognised|recognized|incurred|paid) (?:during|in|for) (20\d\d)\b", text, re.I))
    return next(iter(candidates)) if len(candidates)==1 else None

EVENT_DATE = re.compile(r"\b("+MONTH+r")\s+(?:(\d{1,2}),?\s+|(?:of\s+)?)(20\d\d)\b",re.I)
LANDFALL = re.compile(r"\b(?:made landfall|struck|hit|came ashore|landed|passed (?:through|over)|occurred)\b",re.I)
CONTRACT_ALLOCATION = re.compile(r"\b(?:retain(?:s|ed)? (?:the )?first|(?:the )?next .{0,30} of (?:covered |insured )?losses|deductible|"
    r"attachment point|attach(?:es|ing)? at|per[- ]occurrence|reinsurance layer|in excess of its retention|policy limit|"
    r"co[- ]?participation|co[- ]?insurance|annual aggregate limit|coverage limit)\b|\b\d+(?:\.\d+)?\s*%\s*(?:of|above|share|participation)",re.I)
AT_CAP = re.compile(r"\b(?:expect(?:s|ed)?|project(?:s|ed)?|anticipat(?:e|es|ed))\s+to (?:book|record|incur|retain)\b.{0,60}\bmaximum (?:potential )?retention\b",re.I)
CAP_ONLY = re.compile(r"\b(?:maximum (?:possible |potential |contractual )?(?:retention|exposure|loss)|cap(?:ped)? at|limited to)\b",re.I)
JOINT_SCOPE = re.compile(r"\b(?:both (?:storms|hurricanes)|the (?:two|three) (?:storms|hurricanes)|"
    r"(?:storms|hurricanes) combined|(?:and|together with|along with) (?:the )?other (?:storm|hurricane|catastrophe|wildfire|event)s?|"
    r"combined losses (?:from|of)|combined (?:effect|impact) of)\b",re.I)
APPROX = re.compile(r"\b(?:approximately|roughly|about|around|nearly)\s*$",re.I)
HOLDER = re.compile(r"\b(?:affecting|affected|impacting|impacted)\s+policyholders of\s+([A-Z][\w&'’.-]*(?:\s+(?:&\s+)?[A-Z][\w&'’.-]*){0,5})")

def storm_timing(sentences,event):
    """An explicit landfall date is evidence of event timing only."""
    hits = {}
    for s in sentences:
        if not (event_flags(s,event)[0] and LANDFALL.search(s)) or competing_events(s,event):
            continue
        # Multiple distinct dates in a sentence may describe notice, valuation or landfalls.
        dates = list(EVENT_DATE.finditer(s))
        if len(dates)!=1 or AS_OF.search(s):
            continue
        m=dates[0]
        month=MONTHS[m[1].lower()]
        year=int(m[3])
        if m[2] and not 1<=int(m[2])<=calendar.monthrange(year,month)[1]:
            continue
        hits[f"{year}-Q{(month-1)//3+1}"]=(m[0],s)
    if len(hits)==1:
        quarter,(literal,source)=next(iter(hits.items()))
        return quarter,literal,source
    return None,None,None

def insurance_status(clause, before, after):
    if INS_FUTURE.search(before) and re.search(r"\b(?:to (?:have )?(?:book|pay|incur|receive|paid|received)|will (?:be )?(?:pay|paid|receive))\b",before,re.I):
        return "forecast"
    if re.search(r"\b(?:have |had |has )?received\b",before,re.I) and re.search(r"\b(?:proceeds|recoveries|reimbursements?)\b",clause,re.I):
        return "received"
    if re.search(r"\bpaid\b",before,re.I) and re.search(r"\bclaims?\b",clause,re.I):
        return "paid"
    if re.search(r"\b(?:claims? (?:was |were )?paid|paid (?:out |claims? |losses? )?|cash payments?|payments made)\b",before,re.I):
        return "paid"
    if re.search(r"\b(?:record(?:ed|ing)|recogn(?:ised|ized)|booked|incurred)\b",before,re.I):
        return "booked"
    if INS_FUTURE.search(clause): return "forecast"
    if re.search(r"\b(?:estimated|estimates?|preliminary|ultimate|gross loss estimate)\b",clause,re.I): return "estimate"
    if re.search(r"\b(?:total(?:l)?ed|amounted to|sustained|resulted in|had incurred|was|were)\b",before,re.I):
        return "reported"
    return "unknown"

def insurance_detail(local):
    if re.search(r"\b(?:recoveries|(?:re)?insurance (?:recovery|proceeds|reimbursements?))\b",local,re.I):
        return "insurance_recovery"
    if re.search(r"\bretentions?\b",local,re.I):
        return "retention"
    if re.search(r"\bexposure\b",local,re.I):
        return "loss_exposure"
    if re.search(r"\b(?:paid|payment)\b",local,re.I):
        return "claims_payment"
    return "claims_losses_and_lae" if re.search(r"\b(?:LAE|adjustment expenses?)\b",local,re.I) else "claims_losses"

def insurance_basis(local):
    terms = []
    if re.search(r"\bgross\b|\b(?:before|prior to) reinsurance\b",local,re.I): terms.append("gross")
    if re.search(r"\bnet\b|\bafter reinsurance\b|\bretained\b",local,re.I): terms.append("net")
    if not terms and re.search(r"\bretention\b",local,re.I): terms.append("net")
    if len(set(terms))>1: return None
    return terms[0] if terms else None

def full_date(text):
    match=AS_OF.search(text)
    if not match: return None
    month=MONTHS[match[1].lower()]
    day=int(match[2])
    year=int(match[3])
    if not 1<=day<=calendar.monthrange(year,month)[1]: return None
    return f"{year:04}-{month:02}-{day:02}"

def competing_events(text,event):
    # Distinct named storms in a jointly attributed amount cannot be split.
    if JOINT_SCOPE.search(text):
        return True
    name = re.sub(r"^(?:hurricane|tropical storm|winter storm|typhoon|cyclone|superstorm)\s+","",event.casefold())
    for m in re.finditer(r"\b(?:hurricanes?|tropical storms?|winter storms?|typhoons?|cyclones?)\s+([a-z][a-z-]+)(?:[\s,]+(?:and|&)\s+(?:hurricane\s+)?([a-z][a-z-]+))?",text,re.I):
        for n in m.groups():
            if n and n.casefold() not in {name,"season","loss","losses","related","event","was","is","and","reserve","approach","claims","catastrophe","affected","caused","hit","damage","made","expenses","costs","restoration","occurred","resulted","in","to","had","became","has","on","as","that","for","from","during","response"}:
                # Context words ('hurricane coverage') are not another proper name.
                if n[:1].isupper() or (m[2] is not None):
                    return True
    return False

def insurer_claims(rows):
    outputs=[]
    previous_key=None
    previous=""
    for row in rows:
        key=(row["doc_id"],row["event"],row["issuer"])
        if key!=previous_key: previous=""
        previous_key=key
        text=row["text"]
        passages=re.split(r"(?<=[.!?])\s+(?=[A-Z(])",text)
        event_quarter,event_date,dated_evidence=storm_timing(passages,row["event"])
        prev=previous
        for sentence in passages:
            explicit=event_flags(sentence,row["event"])[0]
            named_in_prior=event_flags(prev,row["event"])[0] and not competing_events(prev,row["event"])
            continuation=GENERIC.search(sentence) or re.match(r"^\s*(?:(?:The |Our |Its )(?:estimated |ultimate |total |projected |consolidated )*(?:gross |net |retained )?(?:loss(?:es)?|retention|claims?)\b)",sentence,re.I) or re.match(r"^\s*(?:We|The Company|The Group|Our|Its|It)\s+(?:(?:currently|presently|initially)\s+)?(?:estimate|expect|anticipate|project|incurred|recorded|sustained|received)",sentence,re.I)
            active=explicit or (named_in_prior and continuation)
            if active and not competing_events(sentence,row["event"]) and not DENIAL.search(sentence):
                for clause in INS_CLAUSE.split(sentence):
                    if not INSURANCE_ROLE.search(clause) or OUT_OF_SCOPE.search(clause) or THIRD_PARTY.search(clause) or CONTRACT_ALLOCATION.search(clause): continue
                    if re.search(r"\b(?:retain(?:s)? the first|the next .{0,26} of covered losses|damages affecting|industrywide)\b",clause,re.I): continue
                    matches=list(money_mentions(clause))
                    for i,(m,lo,hi) in enumerate(matches):
                        start=matches[i-1][0].end() if i else 0
                        end=matches[i+1][0].start() if i+1<len(matches) else len(clause)
                        before=clause[start:m.start()]
                        after=clause[m.end():end]
                        # Literal amount must have its own financial subject. A side sum in parentheses
                        # can describe a different basis; no inheritance from a previous amount here.
                        local=before+" "+after
                        if (not INSURANCE_ROLE.search(before) and not re.match(r"\s*(?:of|in|for)?\s*(?:(?:million|billion)\s+)?(?:net|gross|retention|(?:catastrophe |insured |underwriting )?loss(?:es)?|claims?|(?:re)?insurance (?:recoveries|proceeds|reimbursements?))\b",after,re.I)):
                            continue
                        if OUT_OF_SCOPE.search(local) or re.search(r"\b(?:paid[- ]in capital|net investment|previously projected|would have|hedge)\b",local,re.I):
                            continue
                        # A conditional recovery provision can repeat a retention without reporting
                        # another hurricane loss, as can a general description of treaty policy.
                        if CONDITION.search(clause) or re.search(r"\b(?:treaty limit|contract limit|coverage for each|reinsurance tower|per occurrence|per event|probable maximum|insurance[- ]linked securities)\b",clause,re.I):
                            continue
                        detail=insurance_detail(local)
                        basis=insurance_basis(local)
                        status=insurance_status(clause,before,after)
                        if status=="unknown" and INS_FUTURE.search(sentence) and re.search(r"\b(?:net|retention)\b",clause,re.I): status="forecast"
                        lo2,hi2,bound=monetary_bounds(clause,m,lo,hi)
                        at_cap=bool(AT_CAP.search(clause))
                        approximate=bool(APPROX.search(before))
                        if bound=="point" and CAP_ONLY.search(before) and not at_cap:
                            lo2,hi2,bound=None,hi2,"upper_inclusive"
                        reasons=[]
                        if status=="unknown": reasons.append("status not explicit")
                        if re.search(r"\b(?:its)? contractual|first [\$]|\bpercent of the next\b",local,re.I): reasons.append("contract mechanics")
                        if not basis and re.search(r"\bgross\b",local,re.I) and re.search(r"\bnet\b",local,re.I): reasons.append("contradictory basis")
                        if re.search(r"\b(?:respectively|including|of which)\b",local,re.I) and len(matches)>1: reasons.append("allocation needs review")
                        # As-of date describes an estimate vintage, never the impact period.
                        period=insurance_period(sentence)
                        if not period:
                            quarter=re.search(r"\b(first|second|third|fourth)[- ]quarter\b",sentence,re.I)
                            years=set(re.findall(r"\b20\d\d\b",text))
                            if quarter and len(years)==1: period=f"{next(iter(years))}-Q{QUARTERS[quarter[1].lower()]}"
                        recognition_period=period
                        period=event_quarter or recognition_period
                        scope="reporting_company"
                        affected=row["issuer"]
                        ownership=HOLDER.search(prev) if named_in_prior else None
                        if basis=="gross" and ownership:
                            affected=ownership[1].rstrip(".,")
                            scope="policyholders_of_named_entity"
                        if basis=="net" and re.search(r"\bconsolidated\b",local,re.I):
                            scope="consolidated"
                        tax="pretax" if re.search(r"\bpre[- ]?tax\b",local,re.I) else (
                            "after_tax" if re.search(r"\bafter[- ]tax\b",local,re.I) else None)
                        outputs.append(dict(doc_id=row["doc_id"],passage_id=row["passage_id"],source_url=row["source_url"],
                               issuer=affected,reporting_issuer=row["issuer"],entity_scope=scope,event=row["event"],measure=detail,basis=basis,
                               gross_ultimate=bool(basis=="gross" and re.search(r"\bultimate\b",local,re.I)),
                               at_contractual_cap=at_cap,approximate_amount=approximate,
                               status_detail="expected_to_book" if re.search(r"\bexpect(?:s|ed)? to book\b",before,re.I) else status,
                               event_quarter=event_quarter,event_date_text=event_date,event_date_evidence=dated_evidence,
                               recognition_period=recognition_period,
                               tax_basis=tax,status=status,period=period,estimate_as_of=full_date(clause),
                               low_usd=lo2,high_usd=hi2,bound_type=bound,evidence=sentence,event_evidence=sentence if explicit else prev,
                               amount_text=m.group(),review=bool(reasons),review_reasons=reasons))
            prev=sentence
        previous=passages[-1] if passages else ""
    return outputs

def extract(rows):
    rows=list(rows)
    insurance=insurer_claims(rows)
    insurance_keys={(x["doc_id"],x["passage_id"],x["evidence"],x["amount_text"]) for x in insurance}
    combined=list(insurance)
    for item in extract_general(rows):
        event=item["event"]
        evidence=item["evidence"]
        if competing_events(evidence,event) or competing_events(item["event_evidence"],event): continue
        if item["measure"] in {"claims_losses","insurance_recovery"} and INSURANCE_ROLE.search(evidence):
            # Insurer-specific logic handles joint events, contract limits and net/gross figures.
            continue
        key=(item["doc_id"],item["passage_id"],evidence,item["amount_text"])
        if key in insurance_keys: continue
        # General recovery costs use the same explicit open-end convention.
        m=next((match for match in MONEY.finditer(evidence) if match.group()==item["amount_text"]),None)
        if m:
            lo,hi,bound=monetary_bounds(evidence,m,item["low_usd"],item["high_usd"])
            item.update(low_usd=lo,high_usd=hi,bound_type=bound)
        item.update(basis=None,tax_basis=None,estimate_as_of=full_date(evidence))
        combined.append(item)
    # Preserve filing order when both general and insurer-specific clauses exist.
    order={(row["doc_id"],row["passage_id"]):i for i,row in enumerate(rows)}
    return sorted(combined,key=lambda x:order[(x["doc_id"],x["passage_id"])])

def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("input",type=Path);cli.add_argument("output",type=Path)
    args=cli.parse_args()
    with args.input.open(encoding="utf-8-sig") as stream:
        results=extract(json.loads(s) for s in stream if s.strip())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=args.output.parent,delete=False) as tmp:
        json.dump(results,tmp,ensure_ascii=False,indent=2)
        tmp.write("\n")
    os.replace(tmp.name,args.output)

if __name__=="__main__":
    main()
