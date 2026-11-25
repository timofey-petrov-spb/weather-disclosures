"""Extract provisional monetary claims from the development documents."""
import argparse
import json
import re
import sys

from money_roles import classify_sentence
from review import PASSAGES, STORMS, instant, load_passages, review


BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")
ABBREVIATION = re.compile(r"(?:\b[A-Z]|\b(?:Inc|Corp|Mr|Dr|No|Sept|Dec))\.$")
NAMED_STORM = re.compile(r"\b(?P<kind>(?i:hurricanes?|tropical storm))\s+(?P<name>[A-Z][a-z]+)")
NEXT_STORM = re.compile(r"(?:,\s*(?:and\s+)?|\s+(?:and|&)\s+)([A-Z][a-z]+)")
DIVIDE = re.compile(r";|\b(?:whereas|but|while|unrelated to|separately|however)\b", re.I)
OTHER_PARTY = re.compile(r"\b(?:a|the|our|its)\s+(?:supplier|competitor|customer|landlord)(?:['’]s|s?\s+(?:reported|recorded|incurred|lost|estimated))", re.I)
MIXED_CAUSES = re.compile(r"\b(?:pandemic|labor strike|earthquake|wildfires?|other unrelated (?:causes|events))\b", re.I)
DENIAL = re.compile(r"\b(?:not (?:caused by|attributable to|related to|received?|incur(?:red)?|record(?:ed)?)|"
                    r"unrelated to|excluding (?:the )?(?:effects?|impacts?) of)\b", re.I)
HYPOTHETICAL = re.compile(r"\b(?:if|in the event of|in case of|hypothetical|scenario)\b", re.I)
TEMPORAL_ONLY = re.compile(r"\b(?:before|ahead of|prior to)\s+(?:the arrival of\s+)?(?:hurricanes?|tropical storm)\b", re.I)
EVENT_REFERENCE = re.compile(r"\b(?:the|this|that) (?:hurricane|storm)\b|\b(?:the two|these|both) hurricanes\b", re.I)
BREAKDOWN = re.compile(r"^(?:This (?:amount )?(?:consisted of|included)|These (?:amounts|costs|charges) (?:included|comprised))\b", re.I)
ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4}
QUARTER = re.compile(r"\b(first|second|third|fourth)[- ]quarter\b"
                     r"(?:\s+(?:results?\s+)?(?:of|for|in)\s+(?:fiscal\s+)?(20\d{2}))?", re.I)
Q_CODE = re.compile(r"\bQ([1-4])\s+(?:of\s+)?(20\d{2})\b", re.I)
YEAR = re.compile(r"\b(?:year ended\s+[A-Za-z]+\s+\d{1,2},?\s+|(?:full|fiscal)[- ]year\s+)(20\d{2})\b", re.I)


def sentences(text):
    start = 0
    for boundary in BOUNDARY.finditer(text):
        if not ABBREVIATION.search(text[start:boundary.start()]):
            yield start, text[start:boundary.start()]
            start = boundary.end()
    if start < len(text):
        yield start, text[start:]


def named_events(text):
    names = []
    for match in NAMED_STORM.finditer(text):
        names.append(match["name"])
        if match["kind"].lower() == "hurricanes":
            end = match.end()
            while extra := NEXT_STORM.match(text, end):
                if extra[1] == "Hurricane":
                    break
                names.append(extra[1])
                end = extra.end()
    return list(dict.fromkeys(names))


def periods(text):
    named_quarters = QUARTER.findall(text)
    quarters = {f"{year} Q{q}" for q, year in Q_CODE.findall(text)}
    quarters.update(f"{year} Q{ORDINAL[word.lower()]}" for word, year in named_quarters if year)
    years = {f"{year} FY" for year in YEAR.findall(text)}
    if years and any(not year for _, year in named_quarters):
        return set()
    return quarters | years


def monetary_period(clause, prior):
    explicit = periods(clause)
    if len(explicit) == 1:
        return next(iter(explicit)), clause
    if explicit or not re.search(r"\b(?:during|for) (?:the|that) year\b", clause, re.I):
        return None, None
    for sentence in reversed(prior):
        candidates = periods(sentence)
        if candidates:
            period = next(iter(candidates)) if len(candidates) == 1 else None
            return (period, sentence) if period and period.endswith(" FY") else (None, None)
    return None, None


def local_clause(sentence, position):
    start, end = 0, len(sentence)
    for cut in DIVIDE.finditer(sentence):
        if cut.end() <= position:
            start = cut.end()
        elif cut.start() > position:
            end = cut.start()
            break
    return sentence[start:end]


def event_evidence(clause, sentence, prior, event):
    if (OTHER_PARTY.search(clause) or MIXED_CAUSES.search(clause) or DENIAL.search(sentence)
            or HYPOTHETICAL.search(clause) or TEMPORAL_ONLY.search(clause)):
        return [], None
    names = named_events(clause)
    evidence = clause
    if not names and prior and (EVENT_REFERENCE.search(clause) or BREAKDOWN.search(clause.strip())):
        previous = prior[-1]
        if not (OTHER_PARTY.search(previous) or DENIAL.search(previous) or MIXED_CAUSES.search(previous)):
            names = named_events(previous)
            # A singular back-reference cannot disambiguate two previous storms.
            if len(names) > 1 and not re.search(r"\b(?:both|two|these) hurricanes\b", clause, re.I):
                names = []
            evidence = previous
    if event.casefold() not in {name.casefold() for name in names}:
        return [], None
    return names, evidence


def extract_passage(row, event):
    """Return each monetary occurrence once, with offsets into the unmodified passage."""
    output = []
    prior = []
    for offset, sentence in sentences(row["text"]):
        for mention in classify_sentence(sentence):
            clause = local_clause(sentence, mention["start"])
            events, proof = event_evidence(clause, sentence, prior, event)
            period, period_evidence = monetary_period(clause, prior)
            result = {k: row.get(k) for k in ("doc_id", "passage_id", "issuer", "source_sha256", "page",
                                                "url", "canonical_url", "source_edition", "accepted_at_utc")}
            result.update(mention)
            result.update(start=offset + mention["start"], end=offset + mention["end"], quote=sentence,
                          events=events, linked=bool(proof and mention["metric"]), event_evidence=proof,
                          period=period, period_evidence=period_evidence)
            output.append(result)
        prior.append(sentence)
    return output


def extract(passages, event="helene", top=3, as_of=None, doc_id=None):
    windows = review(passages, event, top, as_of, doc_id)
    evidence_ids = {p["passage_id"] for window in windows for p in window["evidence"]}
    return [item for passage in passages if passage["passage_id"] in evidence_ids
            for item in extract_passage(passage, event)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, type=str.lower, choices=sorted(STORMS))
    parser.add_argument("--doc")
    parser.add_argument("--as-of", type=instant)
    parser.add_argument("--top", type=int, default=3, help="Evidence windows per filing")
    parser.add_argument("--all", action="store_true", help="Include unresolved and unrelated monetary mentions")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be greater than zero")
    if not PASSAGES.exists():
        parser.exit(1, "Run scripts/collect.py to build the local development corpus.\n")
    rows = extract(load_passages(PASSAGES), args.event, args.top, args.as_of, args.doc)
    visible = rows if args.all else [r for r in rows if r["linked"]]
    if args.json:
        print(json.dumps(visible, indent=2, ensure_ascii=True))
        return
    sys.stdout.reconfigure(errors="backslashreplace")
    print(f"{len(visible)} monetary mentions shown from {len(rows)} candidates. Each needs source review.")
    for row in visible:
        print(f"{row['passage_id']}  {row['raw']}  |  {row['metric'] or 'unresolved'}  |  "
              f"{row['status']}  |  {row['period'] or 'period unclear'}  |  {', '.join(row['events']) or 'storm unclear'}")


if __name__ == "__main__":
    main()
