"""Tests for the pure billing engine -- no database touched."""

import unittest

from apartment import billing, money
from apartment.billing import BillingError, Rates, Reading


class TestMoney(unittest.TestCase):
    def test_baht_to_satang_is_exact(self):
        self.assertEqual(money.baht(3500), 350_000)
        self.assertEqual(money.baht("18.50"), 1850)
        self.assertEqual(money.baht(0), 0)

    def test_float_input_does_not_drift(self):
        # 0.1 + 0.2 style drift is exactly what integer satang exists to prevent.
        self.assertEqual(money.baht(0.1) + money.baht(0.2), money.baht(0.3))

    def test_multiply_rounds_half_up(self):
        # 18.00 baht/unit x 12.5 units = 225.00
        self.assertEqual(money.multiply(money.baht(18), 12.5), money.baht(225))
        # 8.33 baht x 3 units = 24.99
        self.assertEqual(money.multiply(money.baht("8.33"), 3), money.baht("24.99"))
        # Half-satang rounds up, not to-even.
        self.assertEqual(money.multiply(1, 0.5), 1)

    def test_fmt(self):
        self.assertEqual(money.fmt(350_000), "฿3,500.00")
        self.assertEqual(money.fmt(-1250), "-฿12.50")
        self.assertEqual(money.fmt(0, symbol=False), "0.00")


class TestUnits(unittest.TestCase):
    def test_normal_consumption(self):
        self.assertEqual(billing.units(1000, 1042), 42)

    def test_zero_consumption_is_allowed(self):
        self.assertEqual(billing.units(500, 500), 0)

    def test_backwards_meter_raises(self):
        with self.assertRaises(BillingError):
            billing.units(1000, 999)

    def test_fractional_readings(self):
        self.assertAlmostEqual(billing.units(10.5, 23.25), 12.75)


class TestResolveRates(unittest.TestCase):
    DEFAULTS = {
        "water_rate": str(money.baht(18)),
        "electric_rate": str(money.baht(8)),
        "common_fee": str(money.baht(100)),
        "late_fee_per_day": str(money.baht(50)),
        "late_fee_grace_days": "3",
    }

    def test_null_lease_rates_fall_back_to_defaults(self):
        rates = billing.resolve_rates(
            {"water_rate": None, "electric_rate": None, "common_fee": None}, self.DEFAULTS
        )
        self.assertEqual(rates.water_rate, money.baht(18))
        self.assertEqual(rates.electric_rate, money.baht(8))
        self.assertEqual(rates.common_fee, money.baht(100))

    def test_lease_override_wins(self):
        rates = billing.resolve_rates(
            {"water_rate": money.baht(15), "electric_rate": None, "common_fee": 0}, self.DEFAULTS
        )
        self.assertEqual(rates.water_rate, money.baht(15))
        self.assertEqual(rates.electric_rate, money.baht(8))
        # An explicit 0 is an override, not a missing value.
        self.assertEqual(rates.common_fee, 0)


class TestBuildDraft(unittest.TestCase):
    def setUp(self):
        self.rates = Rates(
            water_rate=money.baht(18),
            electric_rate=money.baht(8),
            common_fee=money.baht(100),
        )
        self.reading = Reading(
            water_prev=100, water_curr=110, electric_prev=2000, electric_curr=2150
        )

    def test_total_is_rent_plus_utilities_plus_common(self):
        draft = billing.build_draft("2026-07", money.baht(3500), self.reading, self.rates)
        expected = (
            money.baht(3500)  # rent
            + money.baht(180)  # 10 water units x 18
            + money.baht(1200)  # 150 electric units x 8
            + money.baht(100)  # common
        )
        self.assertEqual(draft.total, expected)

    def test_lines_carry_the_rate_that_produced_them(self):
        draft = billing.build_draft("2026-07", money.baht(3500), self.reading, self.rates)
        water = next(l for l in draft.lines if l.kind == "water")
        self.assertEqual(water.quantity, 10)
        self.assertEqual(water.unit_price, money.baht(18))
        self.assertEqual(water.amount, money.baht(180))

    def test_zero_common_fee_omits_the_line(self):
        rates = Rates(water_rate=money.baht(18), electric_rate=money.baht(8), common_fee=0)
        draft = billing.build_draft("2026-07", money.baht(3500), self.reading, rates)
        self.assertNotIn("common", {l.kind for l in draft.lines})

    def test_zero_usage_still_shows_the_line(self):
        reading = Reading(water_prev=100, water_curr=100, electric_prev=2000, electric_curr=2000)
        draft = billing.build_draft("2026-07", money.baht(3500), reading, self.rates)
        water = next(l for l in draft.lines if l.kind == "water")
        self.assertEqual(water.amount, 0)

    def test_extras_are_appended(self):
        extra = billing.Line("other", "ค่ากุญแจหาย", 1, money.baht(200), money.baht(200))
        draft = billing.build_draft(
            "2026-07", money.baht(3500), self.reading, self.rates, extras=[extra]
        )
        self.assertEqual(draft.lines[-1].description, "ค่ากุญแจหาย")
        self.assertEqual(draft.total, money.baht(3500 + 180 + 1200 + 100 + 200))

    def test_backwards_meter_propagates(self):
        bad = Reading(water_prev=110, water_curr=100, electric_prev=2000, electric_curr=2150)
        with self.assertRaises(BillingError):
            billing.build_draft("2026-07", money.baht(3500), bad, self.rates)


class TestLateFee(unittest.TestCase):
    RATES = Rates(
        water_rate=0,
        electric_rate=0,
        common_fee=0,
        late_fee_per_day=money.baht(50),
        late_fee_grace_days=3,
    )

    def test_within_grace_period_is_free(self):
        self.assertIsNone(
            billing.late_fee(money.baht(4000), "2026-07-05", "2026-07-08", self.RATES)
        )

    def test_charges_only_days_beyond_grace(self):
        line = billing.late_fee(money.baht(4000), "2026-07-05", "2026-07-13", self.RATES)
        self.assertIsNotNone(line)
        self.assertEqual(line.quantity, 5)  # 8 days late - 3 grace
        self.assertEqual(line.amount, money.baht(250))

    def test_not_yet_due(self):
        self.assertIsNone(
            billing.late_fee(money.baht(4000), "2026-07-05", "2026-07-01", self.RATES)
        )

    def test_disabled_when_rate_is_zero(self):
        rates = Rates(water_rate=0, electric_rate=0, common_fee=0, late_fee_per_day=0)
        self.assertIsNone(billing.late_fee(money.baht(4000), "2026-01-05", "2026-12-31", rates))


class TestSettlement(unittest.TestCase):
    def test_unpaid(self):
        s = billing.settlement(money.baht(4000), [])
        self.assertEqual(s.status, "unpaid")
        self.assertEqual(s.outstanding, money.baht(4000))

    def test_partial(self):
        s = billing.settlement(money.baht(4000), [money.baht(1500)])
        self.assertEqual(s.status, "partial")
        self.assertEqual(s.outstanding, money.baht(2500))

    def test_paid_in_installments(self):
        s = billing.settlement(money.baht(4000), [money.baht(1500), money.baht(2500)])
        self.assertEqual(s.status, "paid")
        self.assertEqual(s.outstanding, 0)

    def test_overpayment_is_tracked_not_negative(self):
        s = billing.settlement(money.baht(4000), [money.baht(4500)])
        self.assertEqual(s.status, "paid")
        self.assertEqual(s.outstanding, 0)
        self.assertEqual(s.overpaid, money.baht(500))


class TestPeriods(unittest.TestCase):
    def test_next_and_prev_wrap_the_year(self):
        self.assertEqual(billing.next_period("2026-12"), "2027-01")
        self.assertEqual(billing.prev_period("2026-01"), "2025-12")
        self.assertEqual(billing.next_period("2026-07"), "2026-08")

    def test_due_date_clamps_to_short_months(self):
        self.assertEqual(billing.due_date_for("2026-07", 5), "2026-07-05")
        # Day 30 does not exist in February -- clamp, never roll into March.
        self.assertEqual(billing.due_date_for("2026-02", 30), "2026-02-28")
        self.assertEqual(billing.due_date_for("2028-02", 30), "2028-02-29")
        self.assertEqual(billing.due_date_for("2026-12", 31), "2026-12-31")

    def test_invoice_number_is_sortable(self):
        self.assertEqual(billing.invoice_number("2026-07", "101"), "INV-2026-07-101")

    def test_days_overdue(self):
        self.assertEqual(billing.days_overdue("2026-07-05", "2026-07-20"), 15)
        self.assertEqual(billing.days_overdue("2026-07-05", "2026-07-01"), 0)


if __name__ == "__main__":
    unittest.main()
