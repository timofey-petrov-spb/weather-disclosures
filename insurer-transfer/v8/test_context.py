"""Checks for table titles, segment columns, and strictly scoped trailing notes."""

import gzip
import json
from pathlib import Path
import unittest
from extract import table_records, extract_filing
from source_reader import VisibleText

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "table_audit/supplement"


def run(fragment, form="10-Q"):
    body = (
        "<html><body><p>For the quarterly period ended September 30, 2024.</p>"
        + fragment
        + "</body></html>"
    ).encode()
    reader = VisibleText()
    reader.feed(body.decode())
    reader.close()
    reader.flush()
    rows = [
        dict(
            doc_id="DEMO",
            passage_id=f"DEMO-P{i:05}",
            issuer="Example",
            event="Zeta",
            source_kind=form,
            source_url="https://example.org",
            text=text,
            kind=kind,
        )
        for i, (kind, _, text) in enumerate(reader.rows, 1)
    ]
    return table_records(rows, body)


def regional(region="Gulf (Zeta)", owners=("Marine lines", "Total"), title="Catastrophe Losses Incurred"):
    return f"""<p>{title}</p><table><tr><th>(USD in millions, pre-tax and net of reinsurance)</th>
    <th colspan="2">Three months ended September 30, 2024</th></tr>
    <tr><th>Region</th><th>{owners[0]}</th><th>{owners[1]}</th></tr>
    <tr><td>{region}</td><td>(22)</td><td>28</td></tr></table>"""


NOTE = "Catastrophe losses were attributable to Hurricane Zeta."
DATE = "During the three months ended September 30, 2024 the loss ratio was 12%. "
TABLE = """<table><tr><th>($ in thousands)</th><th colspan="2">Three months ended September 30,</th><th>Change</th></tr>
<tr><th></th><th>2023</th><th>2024</th><th>Change</th></tr>
<tr><td>Catastrophe losses</td><td>96</td><td>(12)</td><td>(108)</td></tr>
<tr><td>Non-catastrophe losses</td><td>77</td><td>88</td><td>11</td></tr></table>"""


class ContextTests(unittest.TestCase):
    def test_region_title_and_distinct_owners(self):
        out = run(regional())
        self.assertEqual([r["signed_usd"] for r in out], [-22_000_000, 28_000_000])
        self.assertEqual([r["segment"] for r in out], ["Marine lines", None])
        self.assertTrue(
            all(
                r["tax_basis"] == "pretax"
                and r["basis"] == "net of reinsurance"
                and r["status"] == "incurred"
                for r in out
            )
        )
        self.assertTrue(all(r["table_observations"][0]["metric_cell"]["passage_id"] for r in out))
        self.assertEqual(
            [
                r["signed_usd"]
                for r in run(regional(owners=("Total", "Marine lines")))
                if r["segment"] == "Marine lines"
            ],
            [28_000_000],
        )

    def test_mixed_and_missing_context(self):
        for region in ("South (Zeta and Iota)", "All storms (Zeta)", "South (Iota)", "South (Zeta/Iota)"):
            self.assertFalse(run(regional(region)))
        self.assertFalse(run(regional(title="Separate events")))
        self.assertFalse(run(regional().replace("USD", "Canadian dollars")))
        self.assertFalse(run(regional().replace("Region", "Division")))
        self.assertFalse(run(regional().replace("<table>", "<p>Other matters</p><table>")))

    def test_unique_following_note(self):
        out = run(TABLE + "<p>" + DATE + NOTE + "</p>")
        self.assertEqual([r["signed_usd"] for r in out], [-12_000])
        self.assertEqual(out[0]["measure"], "Catastrophe losses")
        point = out[0]["table_observations"][0]
        self.assertEqual(point["amount_cell"]["column"], 3)
        self.assertIn("Zeta", point["event_cell"]["text"])

    def test_wrong_period_or_partial_attribution(self):
        for message in (
            DATE.replace("2024", "2023") + NOTE,
            DATE.replace("three", "nine") + NOTE,
            DATE + NOTE.replace("were attributable to", "were partly attributable to"),
            DATE + NOTE.replace("Zeta.", "Zeta and flooding."),
            DATE + NOTE.replace("Zeta.", "Zeta and Hurricane Iota."),
            DATE + NOTE.replace("were attributable to", "included losses from"),
            DATE + "Separate damage from Hurricane Zeta was recorded.",
            NOTE,
        ):
            self.assertFalse(run(TABLE + "<p>" + message + "</p>"), message)
        self.assertFalse(run(TABLE + "<p>Other matters</p><p>" + DATE + NOTE + "</p>"))
        self.assertFalse(
            run(TABLE + "<table><tr><td>Elsewhere</td></tr></table><p>" + DATE + NOTE + "</p>")
        )

    def test_note_with_a_quoted_dollar_value(self):
        correct = NOTE.replace("losses were", "losses of $12 thousand were")
        self.assertEqual([r["signed_usd"] for r in run(TABLE + "<p>" + DATE + correct + "</p>")], [-12000])
        self.assertFalse(run(TABLE + "<p>" + DATE + correct.replace("12 thousand", "12 million") + "</p>"))
        self.assertFalse(
            run(TABLE + "<p>" + DATE + NOTE + " Catastrophe losses also included flooding.</p>")
        )

    def test_title_currency_and_window_outside_grid(self):
        text = """<p>The following table shows catastrophe losses incurred, net of reinsurance, for the year ended 2024.</p>
        <p>Amounts in USD millions</p><table><tr><th>Region</th><th>Reinsurance</th><th>Total</th></tr>
        <tr><td>Atlantic (Zeta)</td><td>8</td><td>10</td></tr></table>"""
        result = run(text, "10-K")
        self.assertEqual([r["signed_usd"] for r in result], [8_000_000, 10_000_000])
        self.assertTrue(all(r["basis"] == "net of reinsurance" for r in result))
        self.assertTrue(all("2024" in r["recognition_period"] for r in result))
        self.assertFalse(
            run(text.replace("for the year ended 2024", "for the years 2023 and 2024"), "10-K")
        )

    @unittest.skipUnless(
        (BASE / "release/CIQ.primary.htm.gz").exists(), "requires pinned development SEC files"
    )
    def test_development_files(self):
        for doc, target, expected_scale in [
            ("CIQ", [26_000_000, 51_000_000, 143_000_000, 220_000_000], 10**6),
            ("PLQ", [12_500_000], 10**3),
        ]:
            raw = gzip.decompress((BASE / "release" / (doc + ".primary.htm.gz")).read_bytes())
            source = gzip.decompress((BASE / "release" / (doc + ".inputs.jsonl.gz")).read_bytes()).decode()
            rows = [json.loads(ln) for ln in source.splitlines()]
            all_records = extract_filing(rows, raw)
            amounts = [r for r in all_records if r.get("source_channel") == "html_table"]
            self.assertEqual([r["signed_usd"] for r in amounts], target)
            self.assertTrue(all(not r["review"] and r["unit_scale"] == expected_scale for r in amounts))
            if doc == "CIQ":
                self.assertTrue(all(len(r["observed_windows"]) == 2 for r in amounts))
            else:
                self.assertEqual(
                    [r["measure"] for r in all_records if r["low_usd"] == 1300000],
                    ["reinsurance acceleration or reinstatement expense"],
                )


if __name__ == "__main__":
    unittest.main()
