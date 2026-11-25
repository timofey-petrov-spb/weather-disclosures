import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from money_roles import classify_sentence


class MoneyRolesTests(unittest.TestCase):
    def test_past_combined_impact_and_per_share(self):
        sentence = ("The firm incurred additional expenses and experienced loss of revenues "
                    "estimated at $87 million, or $0.42 per diluted share.")
        result, eps = classify_sentence(sentence)
        self.assertEqual(result["metric"], "additional expenses and lost revenues combined")
        self.assertEqual(result["status"], "past_period_estimate")
        self.assertEqual((result["low_usd"], result["high_usd"]), (87_000_000, 87_000_000))
        self.assertEqual(eps, {"start": sentence.index("$0.42"), "end": sentence.index("$0.42") + 5,
                               "raw": "$0.42", "low_usd": None, "high_usd": None,
                               "metric": None, "status": "unknown"})

    def test_forecast_and_normalized_range(self):
        sentence = ("We anticipate additional expenses and lost revenue of approximately "
                    "$0.2 billion to $310 million, or $0.32 to $0.48 per diluted share.")
        result, eps = classify_sentence(sentence)
        self.assertEqual(result["raw"], "$0.2 billion to $310 million")
        self.assertEqual(sentence[result["start"]:result["end"]], result["raw"])
        self.assertEqual((result["low_usd"], result["high_usd"]), (200_000_000, 310_000_000))
        self.assertEqual(result["status"], "forecast")
        self.assertEqual(eps["low_usd"], None)

    def test_issuer_sales_estimate_and_local_forecast(self):
        past = classify_sentence("The storm had an estimated USD 42m adverse impact on sales.")[0]
        self.assertEqual((past["metric"], past["status"]), ("adverse sales impact", "past_period_estimate"))
        sentence = ("We expect net sales in the fourth quarter to be negatively impacted by $124 million, "
                    "including $28 to $30 million impact on widget sales.")
        forecast, segment = classify_sentence(sentence)
        self.assertEqual((forecast["metric"], forecast["status"]), ("adverse sales impact", "forecast"))
        self.assertEqual((segment["low_usd"], segment["high_usd"]), (28_000_000, 30_000_000))
        self.assertEqual((segment["metric"], segment["status"]), (None, "unknown"))

    def test_competing_clauses_and_equal_values(self):
        sentence = ("We recorded $87m of pre-tax net charges and expect $87m in insurance recoveries.")
        charge, insurance = classify_sentence(sentence)
        self.assertEqual((charge["metric"], charge["status"]), ("net pre-tax charges", "recorded"))
        self.assertEqual((insurance["metric"], insurance["status"]), ("insurance recoveries", "forecast"))
        self.assertNotEqual(charge["start"], insurance["start"])

    def test_gross_net_and_unrelated_numbers(self):
        rows = classify_sentence("Sales totaled $234m, including insurance products. "
                                 "Unrelated claims payments, net of insurance recoveries, were $88m.")
        self.assertEqual([row["metric"] for row in rows], [None, None])
        charge = classify_sentence("During the quarter, we recorded $9m of net charges.")[0]
        self.assertIsNone(charge["metric"])  # no pre-tax qualifier
        op_income = classify_sentence("The storm had an adverse impact of $60m on segment operating income.")[0]
        self.assertIsNone(op_income["metric"])

    def test_reconciliation_components_keep_distinct_roles(self):
        sentence = ("This consisted of $23 million related to the write-off of damaged inventory and fixed assets, "
                    "as well as $47 million of remediation, idle facility, air freight and other costs, "
                    "offset by $19 million of insurance recoveries.")
        a, b, c = classify_sentence(sentence)
        self.assertEqual([r["metric"] for r in (a, b, c)], [
            "asset and inventory write-offs", "remediation and other costs", "insurance recoveries"])
        self.assertTrue(all(r["status"] == "unknown" for r in (a, b, c)))

    def test_mixed_currency_or_units_go_to_review(self):
        for expr in ["C$30 million", "CAD $30 million", "R$30 million", "€30 million",
                     "USD 30 to CAD 45 million", "$2 to 7 million euros",
                     "$1.75 million per share", "$4.50/share", "$44 Canadian dollars",
                     "$50m to $20m", "at least $45m", "$100 million to $140"]:
            with self.subTest(expr=expr):
                row = classify_sentence(f"We recorded {expr} of net pre-tax charges.")[0]
                self.assertEqual((row["low_usd"], row["high_usd"], row["metric"], row["status"]),
                                 (None, None, None, "unknown"))

    def test_currency_list_offsets_and_shared_scale(self):
        sentence = "Guidance was between US$1.25 and $1.5 billion, compared with CAD 450m and $10,250.50."
        a, b, c = classify_sentence(sentence)
        for row in (a, b, c):
            self.assertEqual(sentence[row["start"]:row["end"]], row["raw"])
        self.assertEqual((a["low_usd"], a["high_usd"]), (1_250_000_000, 1_500_000_000))
        self.assertIsNone(b["low_usd"])
        self.assertEqual(c["low_usd"], 10250.5)

    def test_hypothetical_and_movement(self):
        self.assertIsNone(classify_sentence("If the storm persists, we expect $2m of net pre-tax charges.")[0]["metric"])
        changed = classify_sentence("Sales moved from $1m to $3m.")[0]
        self.assertEqual((changed["low_usd"], changed["high_usd"]), (None, None))
        self.assertEqual(classify_sentence("The wind reached 91 mph."), [])

    def test_negated_recognition_and_eps_header(self):
        row = classify_sentence("We have not yet recognized $16 million of insurance recoveries.")[0]
        self.assertEqual((row["metric"], row["status"]), (None, "unknown"))
        row = classify_sentence("Diluted EPS was $3.25 for the quarter.")[0]
        self.assertIsNone(row["low_usd"])

    def test_unmarked_units_in_lists_are_left_open(self):
        for expr, i in [("$3 and $5 million", 0), ("$7 million and $9", 1)]:
            with self.subTest(expr=expr):
                row = classify_sentence("Other amounts included " + expr + ".")[i]
                self.assertIsNone(row["low_usd"])


if __name__ == "__main__":
    unittest.main()
