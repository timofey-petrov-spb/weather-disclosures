"""Check explicitly tagged monetary figures in well-formed inline XBRL filings (stdlib).

usd_facts(markup: bytes, accession: str) yields source-linked dictionaries.
check_amount(facts, amount_usd, *, accession, concept, entity, start, end, dimensions)
checks an exact context. For instants, use start=None and end=the instant date.
Unsupported transforms or contexts are omitted. Untagged narrative is not an XBRL fact.
"""
from datetime import date
from decimal import Decimal, localcontext
from io import BytesIO
import re
from xml.etree import ElementTree as ET

INSTANCE = "{http://www.xbrl.org/2003/instance}"
DIMENSION = "{http://xbrl.org/2006/xbrldi}"
INLINE = "{http://www.xbrl.org/2013/inlineXBRL}"
NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
ISO = "http://www.xbrl.org/2003/iso4217"
TRANSFORM = re.compile(r"https?://www\.xbrl\.org/inlineXBRL/transformation/\d{4}-\d{2}-\d{2}\Z")


def _context(node):
    entity = node.find(INSTANCE+"entity/"+INSTANCE+"identifier")
    period = node.find(INSTANCE+"period")
    if entity is None or not entity.text or period is None:
        return None
    members = {}
    for member in node.iter():
        if member.tag == DIMENSION+"typedMember":
            return None
        if member.tag == DIMENSION+"explicitMember":
            key = member.get("dimension")
            if not key or not member.text or key in members:
                return None
            members[key] = member.text.strip()
        if member.tag in (INSTANCE+"scenario", INSTANCE+"segment"):
            if any(ch.tag != DIMENSION+"explicitMember" for ch in member):
                return None
    start = period.findtext(INSTANCE+"startDate")
    end = period.findtext(INSTANCE+"endDate")
    instant = period.findtext(INSTANCE+"instant")
    if not ((start and end and not instant) or (instant and not start and not end)):
        return None
    end = end or instant
    try:
        if start and date.fromisoformat(start)>date.fromisoformat(end):
            return None
        date.fromisoformat(end)
    except ValueError:
        return None
    return dict(entity=entity.text.strip(), scheme=entity.get("scheme"), start=start,
                end=end, dimensions=members)


def _amount(text, transform, scale, sign):
    if sign not in (None, "-") or not re.fullmatch(r"[+-]?\d{1,2}",scale):
        return None
    # A transformation registry controls the meaning of punctuation. Unknown ones fail closed.
    if transform in {"zerodash", "numdash", "fixed-zero"}:
        if not re.fullmatch(r"[-–—−]",text):
            return None
        value = Decimal(0)
    else:
        patterns = {
            "numdotdecimal": r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?",
            "num-dot-decimal": r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?",
            "numcommadecimal": r"(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d+)?",
            "num-comma-decimal": r"(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d+)?",
            "": r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)",
        }
        pattern=patterns.get(transform)
        if not pattern or not re.fullmatch(pattern,text) or sign and text.startswith(("-", "+")):
            return None
        if transform in {"numcommadecimal","num-comma-decimal"}:
            text=text.replace(".","").replace(",",".")
        elif transform:
            text=text.replace(",","")
        value=Decimal(text)
    with localcontext() as ctx:
        ctx.prec=max(32,len(value.as_tuple().digits)+2)
        value=value.scaleb(int(scale))
        if sign=="-":
            value=-value
        out=format(value,"f")
    return out.rstrip("0").rstrip(".") if "." in out else out


def usd_facts(markup, accession):
    """Yield simple USD facts. Rebound prefixes, ratio units and ambiguous IDs are rejected."""
    markup=markup.strip()
    # SEC full-submission text may wrap valid XHTML in an SGML XBRL marker.
    if markup.startswith(b"<XBRL>") and markup.endswith(b"</XBRL>"):
        markup=markup[len(b"<XBRL>"):-len(b"</XBRL>")].strip()
    parser=ET.iterparse(BytesIO(markup),events=("start-ns","end"))
    namespaces={}
    for event, obj in parser:
        if event=="start-ns":
            prefix,uri=obj
            if prefix in namespaces and namespaces[prefix]!=uri:
                raise ValueError("Namespace prefix rebound; unsupported filing")
            namespaces[prefix]=uri
    root=parser.root
    def resolve(qname):
        prefix,sep,local=qname.partition(":")
        return (namespaces.get(prefix),local) if sep else (namespaces.get(""),prefix)
    def indexed(tag,converter):
        values={}
        for n in root.iter(tag):
            key=n.get("id")
            if key:
                values[key]=None if key in values else converter(n)
        return values
    def usd_unit(n):
        if len(n)!=1 or n[0].tag!=INSTANCE+"measure": return False
        return resolve((n[0].text or "").strip())==(ISO,"USD")
    units=indexed(INSTANCE+"unit",usd_unit)
    contexts=indexed(INSTANCE+"context",_context)
    for fact in root.iter(INLINE+"nonFraction"):
        attrs=fact.attrib
        if not units.get(attrs.get("unitRef")) or attrs.get(NIL) in ("true","1"):
            continue
        if attrs.get("continuedAt") or any(sub.tag in {INLINE+"nonFraction",INLINE+"exclude"} for sub in fact.iter() if sub is not fact):
            continue
        ctx=contexts.get(attrs.get("contextRef"))
        name=attrs.get("name","")
        if not ctx or not name or not resolve(name)[0]:
            continue
        fmt=""
        if attrs.get("format"):
            uri,fmt=resolve(attrs["format"])
            if not TRANSFORM.fullmatch(uri or ""):
                continue
        printed="".join(fact.itertext()).strip()
        scale=attrs.get("scale","0")
        amount=_amount(printed,fmt,scale,attrs.get("sign"))
        if amount is not None:
            yield dict(accession=accession, fact_id=attrs.get("id"),concept=name,
                       context=attrs["contextRef"],unit_ref=attrs["unitRef"],printed=printed,scale=int(scale),
                       sign=attrs.get("sign"),format=attrs.get("format"),normalized_usd=amount,**ctx)


def check_amount(facts, amount_usd, *, accession, concept, entity, start, end, dimensions):
    """One monetary value per fully specified entity, concept, period and exact dimensions.

    A mismatch reports the sole value actually found. Never choose among conflicting values.
    """
    selected=[f for f in facts if (f["accession"],f["concept"],f["entity"],f["start"],f["end"],f["dimensions"]) ==
              (accession,concept,entity,start,end,dimensions)]
    values={Decimal(f["normalized_usd"]) for f in selected}
    identities={f["scheme"] for f in selected}
    if not selected:
        verdict="missing"
    elif len(values)!=1 or len(identities)!=1:
        verdict="ambiguous"
    else:
        verdict="confirmed" if Decimal(str(amount_usd)) in values else "contradicted"
    return {"verdict":verdict,"proposed_usd":str(amount_usd),"evidence":selected}
