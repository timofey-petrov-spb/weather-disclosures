"""Conservative sentence-level rules for dollar amounts in US company disclosures.

Offsets are half-open indexes in the untouched input string. A bare dollar sign
uses the US-dollar convention of this development corpus. Unsupported units or
currency conversions produce null amounts. An unlabeled dollar amount can
still be displayed in the review queue. No knowledge of the issuing company,
storm, dollar values or document IDs enters the rules.
"""
import re
from decimal import Decimal


CURRENCY = r"(?:\b(?:US|CA|C|A|NZ|HK|S)\$|\b(?:USD|CAD|AUD|NZD|HKD|SGD|EUR|GBP|CHF|JPY|CNY|RMB)\b|[$€£¥])"
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
SCALE = r"(?:trillion|billion|million|thousand|bn|mn|mm|[bmk])\b"
VALUE = re.compile(
    rf"(?P<currency>{CURRENCY})\s*(?P<sign>[-−+]?)\s*"
    rf"(?P<number>{NUMBER})(?:\s*(?P<scale>{SCALE}))?", re.I)
RANGE_END = re.compile(
    rf"\s*(?P<join>[-–—]|\bto\b|\band\b)\s*(?P<currency>{CURRENCY})?\s*"
    rf"(?P<number>{NUMBER})(?:\s*(?P<scale>{SCALE}))?", re.I)
FACTORS = {"trillion": 10**12, "billion": 10**9, "bn": 10**9, "b": 10**9,
           "million": 10**6, "mn": 10**6, "mm": 10**6, "m": 10**6,
           "thousand": 10**3, "k": 10**3}
FOREIGN_SUFFIX = re.compile(r"^\s*(?:Canadian|Australian|Hong Kong|New Zealand|Singapore)"
                            r"\s+dollars?\b|^\s*(?:CAD|AUD|HKD|NZD|SGD|EUR|GBP|JPY|CNY|"
                            r"euros?|yen|yuan|pounds?|francs?)\b", re.I)
FOREIGN_PREFIX = re.compile(r"\b(?:CAD|AUD|HKD|NZD|SGD|EUR|GBP|JPY|CNY|Canadian|Australian|"
                            r"Hong Kong|New Zealand|Singapore)\s*$", re.I)
DENOMINATOR = re.compile(r"^\s*(?:/|per\s+|a\s+share\b|each\b|%)", re.I)
PER_SHARE_PREFIX = re.compile(r"\b(?:EPS|per (?:diluted |basic |common )*share)"
                              r"(?:\s+(?:of|was|were|totaled|is|at|approximately|about))*\s*$", re.I)
APPROX = r"(?:(?:approximately|about|around|roughly|an estimated)\s+)?"
NET_CHARGES = r"(?:pre[- ]tax net|net pre[- ]tax) charges?"
COMBINED = r"additional expenses? and (?:experienced )?(?:lost revenues?|loss(?:es)? of revenues?)"

# @ marks only the current amount. Patterns spell out the grammatical link
# between that amount and its financial measure; mere occurrence is insufficient.
ROLE_PATTERNS = {
    "additional expenses and lost revenues combined": (
        rf"\b{COMBINED}(?:\s+(?:were|was|are|is|estimated|reported|totaled|totalled|at|of|approximately|about))*\s+@",
        rf"@\s+(?:in|of)\s+{COMBINED}\b",
    ),
    "adverse sales impact": (
        rf"\bsales(?: in (?:the )?(?:first|second|third|fourth) quarter)?\s+"
        rf"(?:(?:to be|were|was|are|have been|will be)\s+)?(?:negatively|adversely) "
        rf"(?:impacted|affected)\s+by\s+{APPROX}@",
        r"@\s+(?:adverse|negative)\s+impact on (?:net |segment )?sales\b",
        rf"\b(?:adverse|negative)\s+impact (?:on (?:net )?sales\s+of\s+{APPROX}@|of\s+{APPROX}@\s+on (?:net )?sales\b)",
    ),
    "net pre-tax charges": (
        rf"@\s+(?:of|in)\s+{NET_CHARGES}\b",
        rf"\b{NET_CHARGES}\s+(?:of|total(?:l)?ed|amounted to|were)\s+{APPROX}@",
    ),
    "insurance recoveries": (
        r"@\s+(?:in|of|from)\s+insurance recover(?:y|ies)\b",
        r"@\s+benefit (?:from|related to) insurance recover(?:y|ies)\b",
        rf"\binsurance recover(?:y|ies)\s+(?:of|total(?:l)?ed|amounted to|were)\s+{APPROX}@",
    ),
    "asset and inventory write-offs": (
        r"@\s+(?:related to|for|of)\s+(?:the )?write[- ]offs? of "
        r"(?:damaged )?(?:inventory and (?:fixed )?assets|(?:fixed )?assets and inventory)\b",
    ),
    "remediation and other costs": (
        r"@\s+(?:in|of)\s+remediation,?\s+(?:idle facility,?\s+)?"
        r"air freight(?:,?\s+and other costs)\b",
    ),
}
ROLE_PATTERNS = {role: re.compile("|".join(patterns), re.I) for role, patterns in ROLE_PATTERNS.items()}
CLAUSE = re.compile(r";|[•|]|\b(?:but|whereas|while|however)\b|"
                    r",?\s+and\s+(?=(?:we |they |the company |it )?"
                    r"(?:expect|anticipat|forecast|record|incur|report|recogniz|estimat))", re.I)
FORECAST = re.compile(r"\b(?:expect(?:s|ed)?|anticipat(?:e|es|ed)|forecast(?:s|ed)?|"
                      r"project(?:s|ed)|guidance|will)\b", re.I)
ESTIMATE = re.compile(r"\bestimat(?:e|es|ed)\b", re.I)
PAST = re.compile(r"\b(?:incurred|experienced|had|caused|causing|was|were|ended|"
                  r"results.{0,65}?\binclud(?:e|ed))\b", re.I)
RECORDED = re.compile(r"\b(?:recorded|recognized|recognised|incurred|received|"
                      r"results.{0,65}?\bincluded)\b", re.I)
HYPOTHETICAL = re.compile(r"\b(?:if|may|might|could|would|unless)\b", re.I)
NEGATED = re.compile(r"\b(?:not|never|no longer)\s+(?:(?:yet|previously|already|have|been)\s+)*"
                     r"(?:record|recogniz|recognis|incur|receiv|expect|anticipat|estimat|experienc|suffer)\w*", re.I)


def _usd(currency):
    return currency.upper() in {"$", "USD", "US$"}


def _quantity(number, scale):
    amount = Decimal(number.replace(",", "")) * FACTORS.get((scale or "").lower(), 1)
    return int(amount) if amount == amount.to_integral_value() else float(amount)


def _mentions(sentence):
    end = 0
    while match := VALUE.search(sentence, end):
        end = match.end()
        left = sentence[:match.start()]
        between = bool(re.search(r"\bbetween\s*$", left, re.I))
        upper = RANGE_END.match(sentence, end)
        if upper and (upper["join"].lower() != "and" or between):
            end = upper.end()
        else:
            upper = None
        low = high = None
        tail = sentence[end:]
        signed = match["sign"] or re.search(r"[-−]\s*$", left)
        parenthesized = left.rstrip().endswith("(") and tail.lstrip().startswith(")")
        transition = upper and re.search(r"\bfrom\s*$", left, re.I) and not re.search(
            r"\brang(?:e|es|ed|ing)\s+from\s*$", left, re.I)
        bound = re.search(r"\b(?:at least|at most|up to|more than|less than|in excess of)\s*$", left, re.I)
        invalid = (signed or parenthesized or transition or bound or DENOMINATOR.match(tail)
                   or PER_SHARE_PREFIX.search(left) or FOREIGN_SUFFIX.match(tail)
                   or (match["currency"] == "$" and (FOREIGN_PREFIX.search(left) or left[-1:].isalpha()))
                   or re.match(r"^(?:[,.]\d|[A-Za-z])", tail))
        if upper is None and not match["scale"]:
            # The unit of the first amount in "$3 and $5 million" (or the last
            # one in "$3 million and $5") is ambiguous outside a stated range.
            neighbor = (re.match(rf"^\s*(?:,|and|or)\s*({CURRENCY})\s*{NUMBER}\s*{SCALE}", tail, re.I)
                        or re.search(rf"({CURRENCY})\s*{NUMBER}\s*{SCALE}\s*(?:,|and|or)\s*$", left, re.I))
            invalid = invalid or (neighbor and _usd(neighbor[1]))
        if _usd(match["currency"]) and not invalid and (not upper or not upper["currency"] or _usd(upper["currency"])):
            first_scale = match["scale"]
            if upper:
                second_scale = upper["scale"]
                # A trailing unit can apply to both ends ("$40 to $50 million").
                # A missing trailing unit after a scaled first endpoint is ambiguous.
                if second_scale or not first_scale:
                    low = _quantity(match["number"], first_scale or second_scale)
                    high = _quantity(upper["number"], second_scale)
                    if low > high:
                        low = high = None
            else:
                low = high = _quantity(match["number"], first_scale)
        yield {"start": match.start(), "end": end, "raw": sentence[match.start():end],
               "low_usd": low, "high_usd": high, "metric": None, "status": "unknown"}


def classify_sentence(sentence):
    """Return all explicit currency candidates with local role and measurement status."""
    mentions = list(_mentions(sentence))
    for i, mention in enumerate(mentions):
        if mention["low_usd"] is None:
            continue
        prev = mentions[i - 1]["end"] if i else 0
        following = mentions[i + 1]["start"] if i + 1 < len(mentions) else len(sentence)
        left = CLAUSE.split(sentence[prev:mention["start"]])[-1][-320:]
        right = CLAUSE.split(sentence[mention["end"]:following])[0][:165]
        nearby = " ".join((left + "@" + right).split())
        roles = [role for role, pattern in ROLE_PATTERNS.items() if pattern.search(nearby)]
        if len(roles) != 1 or HYPOTHETICAL.search(left) or NEGATED.search(left):
            continue
        # Keep a confidently named metric even when no temporal statement is
        # local enough to distinguish recognition from a prospective estimate.
        mention["metric"] = roles[0]
        if FORECAST.search(left) and RECORDED.search(left):
            continue
        if FORECAST.search(left):
            mention["status"] = "forecast"
        elif ESTIMATE.search(nearby) and PAST.search(left):
            mention["status"] = "past_period_estimate"
        elif RECORDED.search(left):
            mention["status"] = "recorded"
    return mentions
