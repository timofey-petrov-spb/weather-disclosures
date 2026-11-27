"""Source-cell contracts for historical and modern financial tables."""

import json
from pathlib import Path
import unittest
from extract import records_for_table, extract_filing, v7
from source_reader import VisibleText

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "transfer8/holdout"


def samples(fragment):
    body = (
        "<html><body><p>For the fiscal year ended December 31, 2024.</p>" + fragment + "</body></html>"
    ).encode()
    parser = VisibleText()
    parser.feed(body.decode())
    parser.close()
    parser.flush()
    rows = [
        dict(
            doc_id="D",
            passage_id=f"D-P{i:05d}",
            event="Zeta",
            issuer="Example Insurance",
            source_kind="10-K",
            source_url="https://example.org/filing",
            kind=kind,
            text=text,
        )
        for i, (kind, _, text) in enumerate(parser.rows, 1)
    ]
    return [
        r
        for t in v7.read_tables(body, rows)
        for r in records_for_table(t, rows, "FY2024", rows[0]["passage_id"])
    ]


def columns(unit, first="Hurricane Zeta", last=""):
    return (
        unit
        + """<table><tr><th colspan="7">2024 Calendar Year</th></tr>
    <tr><th>Named event</th><th colspan="3">Net losses and loss expenses</th>
    <th colspan="3">Reinstatement premiums earned</th></tr>
    <tr><td>"""
        + first
        + """</td><td>(</td><td>33.2</td><td>)</td><td>$</td><td>6</td><td></td></tr></table>"""
        + last
    )


class Contracts(unittest.TestCase):
    def test_measure_columns_and_accounting_sign(self):
        intro = "<p>Financial effects on the group and its subsidiaries were as follows (in thousands of U.S. dollars):</p>"
        out = samples(columns(intro))
        self.assertEqual(
            [(r["measure"], r["signed_usd"], r["unit_scale"]) for r in out],
            [
                ("Net losses and loss expenses", -33200, 1000),
                ("Reinstatement premiums earned", 6000, 1000),
            ],
        )
        self.assertEqual(len(out[0]["table_observations"][0]["sign_cells"]), 2)
        self.assertIsNone(out[0]["tax_basis"])
        self.assertTrue(all(r["table_observations"][0]["unit_cell"]["passage_id"] for r in out))

    def test_trailing_unit_and_conflicts(self):
        self.assertEqual(
            [
                r["signed_usd"]
                for r in samples(columns("", last="<p>All figures are expressed in USD millions.</p>"))
            ],
            [-33200000, 6000000],
        )
        self.assertEqual(samples(columns("<p>Figures in thousands of Canadian dollars:</p>")), [])
        self.assertEqual(
            samples(columns("<p>Amounts in USD thousands.</p>", last="<p>Amounts in USD millions.</p>")),
            [],
        )
        self.assertEqual(
            samples(columns("<p>The following are the industry-wide losses (USD in thousands):</p>")), []
        )

    def test_sections_competing_event_and_zero(self):
        table = """<table><tr><th colspan="3">Year ended December 31, 2024</th></tr>
        <tr><th colspan="3">(USD in millions)</th></tr><tr><th></th><th>Insurance</th><th>Reinsurance</th></tr>
        <tr><th>Net premiums earned</th></tr><tr><td>Zeta</td><td>(3)</td><td>0</td></tr>
        <tr><td>Rhea</td><td>8</td><td>3</td></tr>
        <tr><th>Gross losses and loss expenses</th></tr><tr><td>Zeta</td><td>7</td><td>—</td></tr>
        <tr><th>Number of policies</th></tr><tr><td>Zeta</td><td>17</td><td>3</td></tr></table>"""
        out = samples(table)
        self.assertEqual(
            [(r["signed_usd"], r["segment"], r["measure"]) for r in out],
            [
                (-3000000, "Insurance", "Net premiums earned"),
                (0, "Reinsurance", "Net premiums earned"),
                (7000000, "Insurance", "Gross losses and loss expenses"),
            ],
        )

    def test_separate_year_groups(self):
        table = """<table><tr><td></td><th colspan="2">Marine Insurance Losses</th></tr>
        <tr><th colspan="2">Year ended December 31, 2024</th><th colspan="2">Year ended December 31, 2023</th></tr>
        <tr><td></td><th colspan="2">($ in thousands)</th></tr>
        <tr><td>Hurricane Zeta</td><td>$7</td><td>Beach fire</td><td>$99</td></tr></table>
        <p>Losses for 2024 are reported net of reinsurance recoveries.</p>"""
        out = samples(table)
        self.assertEqual([r["signed_usd"] for r in out], [7000])
        self.assertEqual(out[0]["segment"], "Marine Insurance")
        self.assertIn("2024", out[0]["reporting_or_recognition_period"])
        self.assertIn("net of reinsurance", out[0]["basis"])
        self.assertEqual(
            samples(
                table.replace("Hurricane Zeta", "Beach fire").replace(
                    "<td>Beach fire</td><td>$99", "<td>Hurricane Zeta</td><td>$99"
                )
            ),
            [],
        )

    def test_event_column_and_caption(self):
        common = '<tr><th colspan="3">Year ended December 31, 2024</th></tr><tr><th colspan="3">USD in thousands</th></tr>'
        data = "<tr><td>Gross losses</td><td>(4)</td><td>15</td></tr>"
        out = samples(
            "<table>"
            + common
            + "<tr><td></td><th>Hurricane Zeta</th><th>Hurricane Rhea</th></tr>"
            + data
            + "</table>"
        )
        self.assertEqual([r["signed_usd"] for r in out], [-4000])
        frag = (
            "<p>The following table shows the effect of Hurricane Zeta:</p><table>"
            + common
            + "<tr><td>Net losses</td><td>$12</td></tr></table>"
        )
        self.assertEqual([r["signed_usd"] for r in samples(frag)], [12000])
        self.assertEqual(samples(frag.replace("Hurricane Zeta:", "Hurricanes Zeta and Rhea:")), [])
        self.assertEqual(samples(frag.replace("Hurricane Zeta:", "Hurricane Zeta and Rhea:")), [])

    def test_split_currency_and_sign_cells(self):
        frag = """<table><tr><th colspan="6">2024 Calendar Year</th></tr>
        <tr><th>Named event</th><th colspan="5">Net losses</th></tr>
        <tr><td>Hurricane Zeta</td><td>(</td><td>$</td><td>80</td><td>)</td></tr></table>"""
        out = samples("<p>Amounts in USD millions.</p>" + frag)
        self.assertEqual([r["signed_usd"] for r in out], [-80000000])

    def test_html_caption(self):
        fragment = """<table><caption>Impact of Hurricane Zeta for the year ended December 31, 2024 (USD in thousands)</caption>
        <tr><td>Acquisition costs</td><td>23</td></tr></table>"""
        r = samples(fragment)
        self.assertEqual([p["signed_usd"] for p in r], [23000])
        self.assertEqual(r[0]["table_observations"][0]["event_cell"]["element"], "caption")

    @unittest.skipUnless(
        (SOURCE / "reference.json").exists(),
        "Full original filings are exercised by the public study replay",
    )
    def test_original_development_facts(self):
        ref = json.loads((SOURCE / "reference.json").read_text(encoding="utf8"))["claims"]
        self.assertEqual(len(ref), 16)
        for doc in ("PR05", "XL05", "AS05"):
            folder = SOURCE / "sources" / doc
            rows = list(
                map(json.loads, (folder / "inputs.jsonl").read_text(encoding="utf8").splitlines())
            )
            outputs = extract_filing(rows, (folder / (doc + ".htm")).read_bytes())
            for r in (g for g in ref if g["doc_id"] == doc):
                found = [
                    p
                    for p in outputs
                    if any(
                        (a["amount_cell"]["table"], a["amount_cell"]["row"], a["amount_cell"]["column"])
                        == (r["table"], r["row"], r["visible_column"])
                        for a in p.get("table_observations", [])
                    )
                ]
                self.assertEqual(len(found), 1, r["id"])
                p = found[0]
                self.assertEqual(
                    (p["signed_usd"], p["unit_scale"], p["currency"], p["measure"].lower()),
                    (r["signed_low_usd"], r["scale"], "USD", r["measure"].lower()),
                )
            if doc == "PR05":
                self.assertEqual(
                    [p["measure"] for p in outputs if p["low_usd"] == 54000000],
                    ["Reinstatement or additional premiums earned"],
                )


if __name__ == "__main__":
    unittest.main()
