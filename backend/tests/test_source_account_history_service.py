"""Synthetic outer-interval economics, independent of monthly percentage sums."""

import copy
import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
from types import SimpleNamespace

from hermes_finance.domain.monthly_return_chain import calculate_interval_return
from hermes_finance.services.source_account_history import extend_history, latest_history

START, SEAM, END = date(2029, 12, 31), date(2030, 9, 30), date(2030, 10, 31)


def history_case():
    proof = {
        "proof_id": 1,
        "covered_from": "2030-01-01",
        "covered_to": str(SEAM),
        "history_from_zero": True,
        "status": "current",
        "reason_codes": [],
        "interval": {
            "opening_kopecks": "0",
            "closing_kopecks": "110000",
            "contributions_kopecks": "100000",
            "withdrawals_kopecks": "0",
            "coupons_kopecks": "1000",
            "dividends_kopecks": "0",
            "pnl": {"value": "10000"},
            "reason_codes": [],
            "external_flows": [
                {"date": "2030-01-01", "amount_kopecks": "100000", "status": "confirmed"}
            ],
        },
    }
    result = calculate_interval_return(
        (SEAM, 110000), (END, 140000), [(date(2030, 10, 16), 20000, "confirmed")]
    )
    row = SimpleNamespace(result=result, flags=(), coupons_kopecks=500, dividends_kopecks=0)
    flow = SimpleNamespace(
        event_date=date(2030, 10, 16), amount_kopecks=20000, status="confirmed", included=True
    )
    monthly = SimpleNamespace(months=(row,), investment_reports=(proof,), flows=(flow,))
    return proof, monthly


class TestSourceAccountHistory(unittest.TestCase):
    def test_missing_interior_seam_does_not_remove_known_outer_return(self):
        proof, monthly = history_case()
        proof["interval"].update(
            closing_kopecks=None, pnl={"value": None}, reason_codes=["missing_endpoint"]
        )
        monthly.months[0].result = replace(
            monthly.months[0].result,
            opening_kopecks=None,
            growth_kopecks=None,
            reason_codes=("missing_endpoint",),
            missing_endpoint=True,
        )
        result = extend_history(proof, monthly)["interval"]
        self.assertEqual(result["pnl"]["value"], "20000")
        self.assertIsNotNone(result["modified_dietz"]["value"])

    def test_nonzero_reliable_period_is_selected_without_claiming_inception(self):
        proof, _ = history_case()
        proof["history_from_zero"] = False
        proof["interval"]["opening_kopecks"] = "50000"
        self.assertIs(latest_history([proof]), proof)

    def test_october_extends_both_accounts_with_outer_dietz_not_sum_of_rates(self):
        for account, scale in (("synthetic-brokerage", 1), ("synthetic-iis", 2)):
            with self.subTest(account=account):
                proof, monthly = history_case()
                if scale == 2:
                    raw = proof["interval"]
                    for key in (
                        "opening_kopecks",
                        "closing_kopecks",
                        "contributions_kopecks",
                        "coupons_kopecks",
                    ):
                        raw[key] = str(int(raw[key]) * scale)
                    raw["external_flows"][0]["amount_kopecks"] = "200000"
                    raw["pnl"]["value"] = "20000"
                    r = monthly.months[0]
                    r.result = replace(
                        r.result,
                        opening_kopecks=220000,
                        closing_kopecks=280000,
                        contributions_kopecks=40000,
                        growth_kopecks=20000,
                    )
                    r.coupons_kopecks = 1000
                    monthly.flows[0].amount_kopecks = 40000
                before = copy.deepcopy((proof, monthly))
                result = extend_history(proof, monthly)
                self.assertEqual(result["covered_to"], str(END))
                self.assertEqual(result["interval"]["pnl"]["value"], str(20000 * scale))
                self.assertEqual(result["interval"]["contributions_kopecks"], 120000 * scale)
                self.assertEqual(result["interval"]["coupons_kopecks"], 1500 * scale)
                with localcontext() as context:
                    context.prec = 60
                    expected = Decimal(20000 * 304) / Decimal(100000 * 303 + 20000 * 15)
                self.assertEqual(Decimal(result["interval"]["modified_dietz"]["value"]), expected)
                self.assertEqual(len(result["interval"]["external_flows"]), 2)
                self.assertEqual((proof, monthly), before)

    def test_seam_day_flow_occurs_once_and_closing_day_has_zero_weight(self):
        proof, monthly = history_case()
        proof["interval"]["external_flows"][0]["date"] = str(SEAM)
        monthly.flows[0].event_date = END
        monthly.months[0].result = calculate_interval_return(
            (SEAM, 110000), (END, 140000), [(END, 20000, "confirmed")]
        )
        result = extend_history(proof, monthly)["interval"]
        self.assertEqual(result["contributions_kopecks"], 120000)
        self.assertEqual(result["pnl"]["value"], "20000")
        with localcontext() as context:
            context.prec = 60
            expected = Decimal(20000 * 304) / Decimal(100000 * 31)
        self.assertEqual(Decimal(result["modified_dietz"]["value"]), expected)

    def test_unknown_gap_overlap_stale_or_mismatched_seam_never_becomes_zero(self):
        for failure in ("unknown", "gap", "overlap", "stale", "seam", "schedule"):
            with self.subTest(failure=failure):
                proof, monthly = history_case()
                row = monthly.months[0]
                if failure == "unknown":
                    row.result = replace(
                        row.result,
                        growth_kopecks=None,
                        contributions_kopecks=None,
                        reason_codes=("unknown_flow",),
                    )
                elif failure == "gap":
                    row.result = replace(row.result, opening_date=date(2030, 10, 1))
                elif failure == "overlap":
                    monthly.months += (copy.deepcopy(row),)
                elif failure == "stale":
                    proof.update(
                        status="stale",
                        interval=None,
                        reason_codes=["investment_proof_dependencies_changed"],
                    )
                elif failure == "seam":
                    row.result = replace(row.result, opening_kopecks=110001)
                else:
                    proof["interval"].pop("external_flows")
                observed = extend_history(proof, monthly)
                self.assertEqual(observed["covered_to"], str(END))
                if failure == "stale":
                    self.assertIsNone(observed["interval"])
                    continue
                for name in ("pnl", "modified_dietz"):
                    self.assertIsNone(observed["interval"][name]["value"])
                self.assertIsNone(observed["interval"]["contributions_kopecks"])
                self.assertTrue(observed["reason_codes"])

    def test_existing_latest_exact_history_and_as_of_never_fall_back(self):
        proof, monthly = history_case()
        self.assertIs(extend_history(proof, monthly, through=SEAM), proof)
        newer = {**proof, "proof_id": 2, "status": "stale", "interval": None}
        self.assertIs(latest_history([proof, newer]), newer)
        selected = latest_history([{**proof, "history_from_zero": False}])
        self.assertIsNotNone(selected)
        self.assertFalse(selected["history_from_zero"])
        self.assertIsNone(extend_history(None, monthly))

    def test_valuation_gap_preserves_independently_known_income(self):
        proof, monthly = history_case()
        row = monthly.months[0]
        row.result = replace(row.result, opening_kopecks=110001)
        result = extend_history(proof, monthly)["interval"]
        self.assertIsNone(result["pnl"]["value"])
        self.assertEqual(result["coupons_kopecks"], 1500)
        self.assertEqual(result["dividends_kopecks"], 0)

    def test_same_date_equal_amount_distinct_occurrences_retain_multiplicity(self):
        proof, monthly = history_case()
        monthly.flows += (copy.deepcopy(monthly.flows[0]),)
        monthly.months[0].result = calculate_interval_return(
            (SEAM, 110000),
            (END, 160000),
            [(date(2030, 10, 16), 20000, "confirmed")] * 2,
        )
        result = extend_history(proof, monthly)["interval"]
        self.assertEqual(result["contributions_kopecks"], 140000)
        self.assertEqual(result["pnl"]["value"], "20000")
        self.assertEqual(len(result["external_flows"]), 3)

    def test_empty_month_and_known_zero_income_are_not_missing(self):
        proof, monthly = history_case()
        row = monthly.months[0]
        row.result = calculate_interval_return((SEAM, 110000), (END, 110000), [])
        row.coupons_kopecks = 0
        monthly.flows = ()
        result = extend_history(proof, monthly)["interval"]
        self.assertEqual(result["pnl"]["value"], "10000")
        self.assertEqual(result["coupons_kopecks"], 1000)
        self.assertEqual(result["withdrawals_kopecks"], 0)


if __name__ == "__main__":
    unittest.main()
