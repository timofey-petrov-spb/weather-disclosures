"""Public regression cases with invented issuers, amounts, units and dates."""
import unittest

from extract import compact_scale, event_dates, extract_filing, multi_event_total
from source_reader import VisibleText


def read(fragment):
    body = ("<html><body><p>For the fiscal year ended December 31, 2024.</p>" +
            fragment + "</body></html>").encode()
    parser = VisibleText()
    parser.feed(body.decode())
    parser.close()
    parser.flush()
    rows = [dict(doc_id="F", passage_id=f"F-P{i:05d}", issuer="Example Insurance",
                 source_kind="10-K", event="Zeta", accession="example", source_url="about:blank",
                 kind=kind, text=text)
            for i, (kind, _, text) in enumerate(parser.rows, 1)]
    return extract_filing(rows, body)


def table_rows(fragment):
    return [r for r in read(fragment) if r.get("table_observations") and not r["review"]]


def loss_table(scale, note=""):
    return (f"<table><tr><td></td><th colspan='2'>As of December 31, 2024</th></tr>"
            f"<tr><th>{scale}</th><th>Gross Incurred Loss</th><th>Net Incurred Loss (2)</th></tr>"
            "<tr><td>Hurricane Zeta</td><td>7,023</td><td>(5,439)</td></tr>"
            "<tr><td>Hurricane Rhea</td><td>403</td><td>212</td></tr></table>" + note)


class Tests(unittest.TestCase):
    def test_nonliteral_units_and_unit_conflicts(self):
        for label in ("($000’s)", "USD 000s", "(US$000)", "$K"):
            self.assertEqual(compact_scale(label),1000)
            rows = table_rows(loss_table(label))
            self.assertEqual([r["signed_usd"] for r in rows], [7023000,-5439000])
        self.assertEqual(table_rows("<p>Amounts in USD millions.</p>" + loss_table("($000s)")), [])
        self.assertEqual(table_rows("<p>Amounts in thousands of Canadian dollars.</p>" + loss_table("($000s)")), [])
        self.assertEqual(compact_scale("($000,000s)"),10**6)
        self.assertIsNone(compact_scale("C$000s"))
        self.assertEqual(table_rows(loss_table("C$000s")),[])
        self.assertEqual(table_rows(loss_table("($000?)")),[])

    def test_adjacent_numbered_footnote(self):
        rows=table_rows(loss_table("$000", "<table><tr><td>(2) Net of reinsurance recoveries.</td></tr></table>"))
        self.assertEqual(rows[0]["basis"],"gross")
        self.assertIn("net of reinsurance recoveries",rows[1]["basis"])
        self.assertTrue(rows[1]["table_observations"][0]["accounting_context"])

    def test_governing_paragraph_and_controls(self):
        prefix = "<p>The following table shows gross incurred losses for the year ended December 31, 2024:</p>"
        fragment = ("<table><tr><th colspan='2'>(US$ millions)</th></tr><tr><td>Hurricane Zeta</td><td>2.6</td></tr>"
                    "<tr><td>Hurricane Rhea</td><td>9.3</td></tr><tr><td>Total</td><td>11.9</td></tr></table>")
        records=table_rows(prefix+fragment)
        self.assertEqual([r["signed_usd"] for r in records], [2600000])
        self.assertIn("gross incurred",records[0]["measure"])
        self.assertIn("following table",records[0]["table_observations"][0]["metric_cell"]["text"])
        self.assertEqual(table_rows(prefix.replace("gross incurred losses","industry-wide insured losses")+fragment),[])
        self.assertEqual(table_rows(prefix+"<p>Historical examples.</p>"+fragment),[])

    def test_signed_segment_rows_and_occurrences(self):
        fragment = ("<table><tr><td>Date of event</td><td>8/2/24 &amp;</td><td>9/4/24</td></tr>"
                    "<tr><td></td><td>8/3/24</td></tr><tr><td>Hurricane</td><td>Zeta</td><td>Rhea</td></tr>"
                    "<tr><th colspan='3'>USD thousands</th></tr><tr><th>Net loss estimates</th></tr>"
                    "<tr><td>Commercial Lines</td><td>(6)</td><td>19</td></tr><tr><td>Total</td><td>(6)</td><td>19</td></tr></table>")
        records=table_rows(fragment)
        self.assertEqual([(r["segment"],r["signed_usd"]) for r in records],[("Commercial Lines",-6000),(None,-6000)])
        self.assertEqual(records[0]["event_dates"], ["2024-08-02","2024-08-03"])
        self.assertEqual(records[0]["recognition_period"],"FY2024")

    def test_dates_are_valid_and_century_anchored(self):
        self.assertEqual(event_dates("12/31/99",2000),["1999-12-31"])
        self.assertEqual(event_dates("01/01/00",1999),["2000-01-01"])
        self.assertEqual(event_dates("02/29/23",2024),[])
        self.assertEqual(event_dates("01/05/50",2000),[])
        self.assertEqual(event_dates("02/29/24",None),[])
        self.assertEqual(event_dates("02/29/2024",None),["2024-02-29"])

    def test_multi_event_amount_is_distinct_from_allocated_prose(self):
        def is_total(text):
            return multi_event_total(dict(event="Zeta",amount_text="$12 million",evidence=text))
        self.assertTrue(is_total("The losses from Hurricanes Zeta, Alpha and Rhea totaled $12 million."))
        self.assertTrue(is_total("Hurricanes Zeta and Rhea in the United States, with a total net impact of $12 million."))
        self.assertFalse(is_total("Hurricanes Alpha and Rhea cost $30 million. Hurricane Zeta cost $12 million."))
        self.assertFalse(is_total("Hurricane Zeta cost $12 million, while Hurricane Rhea cost $20 million."))


if __name__ == "__main__":
    unittest.main()

