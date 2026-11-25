"""Regressions for publication timing, revisions and monetary scope."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_development import evaluate
from review import AMOUNT, instant, review
from timeline import timeline


def evidence(doc, accepted, eligible):
    return dict(doc_id=doc, passage_id=doc + "-P00001", accepted_at_utc=accepted,
                replay_eligible=eligible, url="https://example.org/", text="Hurricane Helene caused losses of $20 million.")


class ResearchChecks(unittest.TestCase):
    def test_filter_uses_publication_time_and_source_identity(self):
        rows = [dict(doc_id="NHC-1", issued_at_utc="2024-09-27T03:20:00Z", replay_eligible=True),
                evidence("SEC-1", "2024-12-01T15:00:00Z", True),
                evidence("SEC-2", "2024-12-01T15:00:01Z", True),
                evidence("SEC-3", "2024-11-01T00:00:00Z", False)]
        hits = review(rows, "Helene", 1, as_of=instant("2024-12-01T10:00:00-05:00"))
        self.assertEqual([hit["doc_id"] for hit in hits], ["SEC-1"])
        self.assertEqual(len(review(rows, "Helene", 1)), 3)
        with self.assertRaises(ValueError):
            instant("2024-12-01")

    def test_monitor_requires_a_published_bulletin_and_new_filings(self):
        bulletin = dict(doc_id="NHC-1", issued_at_utc="2024-09-27T03:20:00Z", replay_eligible=True)
        early = evidence("SEC-1", "2024-09-27T03:10:00Z", True)
        later = evidence("SEC-2", "2024-09-27T10:00:00Z", True)
        end = instant("2024-09-28T00:00:00Z")
        self.assertEqual(review([later], "Helene", 1, end), [])
        self.assertEqual(review([bulletin, early], "Helene", 1, instant("2024-09-27T03:19:59Z")), [])
        hits = review([bulletin, early, later], "Helene", 1, end)
        self.assertEqual([(h["doc_id"], h["trigger_id"]) for h in hits], [("SEC-2", "NHC-1")])

    def test_dollar_ranges_are_not_added_together(self):
        text = "From $200 million to $300 million, or $0.60 to $0.90 per diluted share."
        self.assertEqual([x.group() for x in AMOUNT.finditer(text)],
                         ["$200 million to $300 million", "$0.60 to $0.90 per diluted share"])
        self.assertIsNone(AMOUNT.search("C$50 million"))

    def test_missing_document_is_not_counted_as_a_matching_case(self):
        claim = dict(id="example", doc_id="SEC-9", events=["Helene"], find_in_passage=["losses"])
        summary = evaluate([], [claim], 3)
        self.assertEqual((summary["located"], summary["readable_cases"], summary["unavailable"]), (0, 0, 1))

    def test_later_revision_keeps_its_period_and_joint_events(self):
        claims = json.loads((ROOT / "data/worked_claims.json").read_text(encoding="utf-8"))
        sources = json.loads((ROOT / "data/sources.json").read_text(encoding="utf-8"))
        before = timeline(claims, sources, instant("2025-01-24T12:40:44Z"), "HCA")
        after = timeline(claims, sources, instant("2025-01-24T12:40:45Z"), "HCA")
        self.assertEqual([c["id"] for c in before], ["HCA-Q3", "HCA-Q4-FORECAST"])
        self.assertEqual({c["id"] for c in after} - {c["id"] for c in before}, {"HCA-Q4-ESTIMATE", "HCA-FY"})
        q4 = next(c for c in after if c["id"] == "HCA-Q4-ESTIMATE")
        self.assertEqual(q4["events"], ["Helene", "Milton"])
        self.assertEqual(q4["relations"], [dict(type="updates", target="HCA-Q4-FORECAST")])


if __name__ == "__main__":
    unittest.main()
