import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_validation import evaluate


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.passage = dict(doc_id="example-001", accession="example", passage_id="example-P1",
                            text="In Q3 2024 we recorded $7 million in net pre-tax charges related to Hurricane Helene.",
                            url="https://example.org/filing", source_sha256="example-digest")
        self.claim = dict(id="claim", accession="example", doc_id="example-001", source_url=self.passage["url"],
                          raw="$7 million", anchor="$7 million in net pre-tax charges", value_usd=7000000,
                          status="recorded", metric="net pre-tax charges", events=["Helene"], period="2024-Q3")

    def measure(self, passage, claim):
        audit = dict(filings=[dict(accession="example")], claims=[claim])
        return evaluate([passage], audit, audit["filings"])["cases"][0]

    def test_aliases_preserve_source_identity(self):
        case = self.measure(self.passage, self.claim)
        self.assertTrue(case["strict_match"])
        self.assertEqual(case["matched_passages"], ["example-P1"])

    def test_identical_value_elsewhere_does_not_satisfy_the_anchor(self):
        row = dict(self.passage, text=self.passage["text"] + " A separate $7 million reserve was disclosed.")
        other = dict(self.claim, anchor="$7 million reserve", metric="reserve")
        case = self.measure(row, other)
        self.assertTrue(case["retrieved"])
        self.assertFalse(case["linked_amount"])


if __name__ == "__main__":
    unittest.main()
