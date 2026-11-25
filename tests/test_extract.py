import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from extract import extract_passage, monetary_period, named_events, sentences


def passage(text):
    return dict(doc_id="EXAMPLE", passage_id="EX-01", text=text, source_sha256="example")


class ExtractionChecks(unittest.TestCase):
    def test_joint_names_and_normal_company_name(self):
        self.assertEqual(named_events("Hurricanes Ida, Ian and Helene affected the site."), ["Ida", "Ian", "Helene"])
        self.assertEqual(named_events("Hurricane Ida and Baxter made headlines."), ["Ida"])

    def test_same_sentence_does_not_imply_causality(self):
        for text in ("Before Hurricane Ian we recorded $5 million of net pre-tax charges.",
                     "Our supplier reported $5 million of net pre-tax charges due to Hurricane Ian.",
                     "Hurricane Ian damaged our facility; we recorded $5 million of net pre-tax charges for restructuring."):
            with self.subTest(text=text):
                rows = extract_passage(passage(text), "ian")
                self.assertEqual(len(rows), 1)
                self.assertFalse(rows[0]["linked"])

    def test_original_offsets_and_joint_storms(self):
        text = ("The U.S. plant reopened. During the fourth quarter of 2024, we recorded "
                "$18 million of net pre-tax charges due to Hurricanes Ida and Ian.")
        self.assertEqual(len(list(sentences(text))), 2)
        row, = extract_passage(passage(text), "ian")
        self.assertTrue(row["linked"])
        self.assertEqual(text[row["start"]:row["end"]], "$18 million")
        self.assertEqual((row["events"], row["period"], row["status"]), (["Ida", "Ian"], "2024 Q4", "recorded"))

    def test_no_period_from_filing_date_or_competing_periods(self):
        self.assertEqual(monetary_period("The charge was recognized.", ["For fiscal year 2024."]), (None, None))
        self.assertEqual(monetary_period("The full-year 2024 forecast includes the fourth quarter.", []), (None, None))
        self.assertEqual(monetary_period("In the third quarter of 2024 versus the fourth quarter of 2024.", []),
                         (None, None))


if __name__ == "__main__":
    unittest.main()
