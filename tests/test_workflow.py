"""End-to-end tests: move a tenant in, read meters, invoice, collect, report.

These run against a real SQLite database in memory, so they exercise the schema
constraints (UNIQUE, CHECK, foreign keys) as well as the Python.
"""

import unittest

from apartment import billing, db, money, repo, reports
from apartment.billing import BillingError


class WorkflowTestCase(unittest.TestCase):
    """Base fixture: an initialised 30-room building with nobody in it yet."""

    def setUp(self):
        self.conn = db.connect(":memory:")
        db.init_db(self.conn)
        db.seed_rooms(self.conn)

    def tearDown(self):
        self.conn.close()

    def move_in(self, room_code="101", name="สมชาย ใจดี", start="2026-07-01", **kw):
        room = repo.room_by_code(self.conn, room_code)
        tenant_id = repo.add_tenant(self.conn, name, phone="081-234-5678")
        return repo.start_lease(self.conn, room["id"], tenant_id, start, **kw)


class TestSeed(WorkflowTestCase):
    def test_creates_thirty_rooms_across_three_floors(self):
        rows = repo.rooms(self.conn)
        self.assertEqual(len(rows), 30)
        self.assertEqual(sorted({r["floor"] for r in rows}), [1, 2, 3])
        codes = [r["code"] for r in rows]
        self.assertEqual(codes[0], "101")
        self.assertEqual(codes[-1], "310")
        self.assertEqual(len([c for c in codes if c.startswith("2")]), 10)

    def test_seeding_twice_does_not_duplicate(self):
        created = db.seed_rooms(self.conn)
        self.assertEqual(created, 0)
        self.assertEqual(len(repo.rooms(self.conn)), 30)

    def test_reseeding_preserves_an_edited_rent(self):
        room = repo.room_by_code(self.conn, "101")
        self.conn.execute("UPDATE room SET base_rent = ? WHERE id = ?", (money.baht(9999), room["id"]))
        self.conn.commit()
        db.seed_rooms(self.conn)
        self.assertEqual(repo.room_by_code(self.conn, "101")["base_rent"], money.baht(9999))


class TestLeases(WorkflowTestCase):
    def test_move_in_marks_the_room_occupied(self):
        self.move_in("101")
        self.assertEqual(repo.room_by_code(self.conn, "101")["status"], "occupied")

    def test_deposit_defaults_to_two_months(self):
        lease_id = self.move_in("101")
        lease = self.conn.execute("SELECT * FROM lease WHERE id = ?", (lease_id,)).fetchone()
        self.assertEqual(lease["deposit"], lease["monthly_rent"] * 2)

    def test_double_booking_a_room_is_refused(self):
        self.move_in("101")
        with self.assertRaises(BillingError):
            self.move_in("101", name="คนที่สอง")

    def test_move_out_frees_the_room(self):
        lease_id = self.move_in("101")
        repo.end_lease(self.conn, lease_id, "2026-09-30", deposit_refunded=money.baht(7000))
        self.assertEqual(repo.room_by_code(self.conn, "101")["status"], "vacant")
        # And the room can be let again.
        self.move_in("101", name="ผู้เช่าใหม่", start="2026-10-01")


class TestMeterReadings(WorkflowTestCase):
    def test_previous_reading_carries_forward(self):
        self.move_in("101")
        room = repo.room_by_code(self.conn, "101")
        repo.save_reading(self.conn, room["id"], "2026-07", water_curr=110, electric_curr=2150,
                          water_prev=100, electric_prev=2000)
        # August omits prev -- it should pick up July's curr automatically.
        repo.save_reading(self.conn, room["id"], "2026-08", water_curr=125, electric_curr=2300)
        august = repo.readings_for(self.conn, "2026-08")[room["id"]]
        self.assertEqual(august["water_prev"], 110)
        self.assertEqual(august["electric_prev"], 2000 + 150)

    def test_first_ever_reading_is_treated_as_an_opening_reading(self):
        # No prior month exists, so consumption is zero rather than the whole
        # lifetime of the meter.
        room = repo.room_by_code(self.conn, "101")
        repo.save_reading(self.conn, room["id"], "2026-07", water_curr=110, electric_curr=2150)
        reading = repo.readings_for(self.conn, "2026-07")[room["id"]]
        self.assertEqual(reading["water_prev"], 110)
        self.assertEqual(reading["electric_prev"], 2150)
        self.assertEqual(billing.units(reading["water_prev"], reading["water_curr"]), 0)

    def test_resaving_a_period_updates_in_place(self):
        room = repo.room_by_code(self.conn, "101")
        repo.save_reading(self.conn, room["id"], "2026-07", 110, 2150, water_prev=100, electric_prev=2000)
        repo.save_reading(self.conn, room["id"], "2026-07", 115, 2160, water_prev=100, electric_prev=2000)
        readings = repo.readings_for(self.conn, "2026-07")
        self.assertEqual(readings[room["id"]]["water_curr"], 115)
        self.assertEqual(len(readings), 1)

    def test_typo_that_runs_the_meter_backwards_is_rejected(self):
        room = repo.room_by_code(self.conn, "101")
        repo.save_reading(self.conn, room["id"], "2026-07", 110, 2150, water_prev=100, electric_prev=2000)
        with self.assertRaises(BillingError):
            repo.save_reading(self.conn, room["id"], "2026-08", water_curr=99, electric_curr=2300)
        self.assertNotIn("2026-08", [r["period"] for r in self.conn.execute("SELECT period FROM meter_reading")])


class TestInvoicing(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.move_in("101")
        self.room = repo.room_by_code(self.conn, "101")
        repo.save_reading(self.conn, self.room["id"], "2026-07", water_curr=110, electric_curr=2150,
                          water_prev=100, electric_prev=2000, read_date="2026-07-01")

    def test_generates_one_invoice_per_occupied_room_with_a_reading(self):
        result = repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        self.assertEqual(result["created"], ["101"])
        invoices = repo.invoices(self.conn, "2026-07")
        self.assertEqual(len(invoices), 1)
        self.assertEqual(invoices[0]["number"], "INV-2026-07-101")

    def test_invoice_total_matches_its_lines(self):
        repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        detail = repo.invoice_detail(self.conn, repo.invoices(self.conn, "2026-07")[0]["id"])
        self.assertEqual(detail["invoice"]["total"], sum(l["amount"] for l in detail["lines"]))
        # 3500 rent + 10 water x 18 + 150 electric x 8 = 3500 + 180 + 1200
        self.assertEqual(detail["invoice"]["total"], money.baht(4880))

    def test_running_twice_does_not_double_bill(self):
        repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        second = repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        self.assertEqual(second["created"], [])
        self.assertEqual(len(second["skipped"]), 1)
        self.assertEqual(len(repo.invoices(self.conn, "2026-07")), 1)

    def test_room_without_a_reading_is_skipped_not_billed_at_zero(self):
        self.move_in("102", name="สมหญิง", start="2026-07-01")
        result = repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        self.assertEqual(result["created"], ["101"])
        self.assertTrue(any("102" in s for s in result["skipped"]))

    def test_vacant_rooms_are_never_invoiced(self):
        repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        self.assertEqual(len(repo.invoices(self.conn, "2026-07")), 1)

    def test_changing_the_rate_later_does_not_rewrite_history(self):
        repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        before = repo.invoices(self.conn, "2026-07")[0]["total"]
        db.set_setting(self.conn, "water_rate", money.baht(30))
        self.assertEqual(repo.invoices(self.conn, "2026-07")[0]["total"], before)

    def test_void_keeps_the_number_and_frees_the_period(self):
        repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        invoice_id = repo.invoices(self.conn, "2026-07")[0]["id"]
        repo.void_invoice(self.conn, invoice_id, reason="ออกบิลผิด")
        self.assertEqual(repo.invoices(self.conn, "2026-07"), [])
        row = self.conn.execute("SELECT status FROM invoice WHERE id = ?", (invoice_id,)).fetchone()
        self.assertEqual(row["status"], "void")

    def test_cannot_void_an_invoice_that_was_paid(self):
        repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        invoice_id = repo.invoices(self.conn, "2026-07")[0]["id"]
        repo.record_payment(self.conn, invoice_id, money.baht(1000), paid_on="2026-07-05")
        with self.assertRaises(BillingError):
            repo.void_invoice(self.conn, invoice_id, reason="เปลี่ยนใจ")


class TestPayments(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.move_in("101")
        room = repo.room_by_code(self.conn, "101")
        repo.save_reading(self.conn, room["id"], "2026-07", 110, 2150, water_prev=100, electric_prev=2000)
        repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        self.invoice_id = repo.invoices(self.conn, "2026-07")[0]["id"]

    def test_partial_then_full_payment(self):
        repo.record_payment(self.conn, self.invoice_id, money.baht(2000), paid_on="2026-07-05")
        detail = repo.invoice_detail(self.conn, self.invoice_id)
        self.assertEqual(detail["settlement"].status, "partial")
        repo.record_payment(self.conn, self.invoice_id, money.baht(2880), paid_on="2026-07-20")
        detail = repo.invoice_detail(self.conn, self.invoice_id)
        self.assertEqual(detail["settlement"].status, "paid")
        self.assertEqual(detail["settlement"].outstanding, 0)

    def test_zero_or_negative_payment_is_refused(self):
        with self.assertRaises(BillingError):
            repo.record_payment(self.conn, self.invoice_id, 0)
        with self.assertRaises(BillingError):
            repo.record_payment(self.conn, self.invoice_id, money.baht(-500))

    def test_late_fee_applies_once_only(self):
        first = repo.apply_late_fees(self.conn, as_of="2026-07-20")
        self.assertEqual(len(first), 1)
        after_first = repo.invoices(self.conn, "2026-07")[0]["total"]
        second = repo.apply_late_fees(self.conn, as_of="2026-07-25")
        self.assertEqual(second, [])
        self.assertEqual(repo.invoices(self.conn, "2026-07")[0]["total"], after_first)

    def test_late_fee_adds_to_the_invoice_total(self):
        before = repo.invoices(self.conn, "2026-07")[0]["total"]
        repo.apply_late_fees(self.conn, as_of="2026-07-13")  # due 07-05, 8 days late, 3 grace
        after = repo.invoices(self.conn, "2026-07")[0]["total"]
        self.assertEqual(after - before, money.baht(250))  # 5 billable days x 50

    def test_paid_invoice_gets_no_late_fee(self):
        repo.record_payment(self.conn, self.invoice_id, money.baht(4880), paid_on="2026-07-05")
        self.assertEqual(repo.apply_late_fees(self.conn, as_of="2026-08-30"), [])


class TestRoomBoard(WorkflowTestCase):
    """The floor plan's data. Each room must land in exactly one honest state."""

    def bill(self, code, period="2026-07", pay=None):
        room = repo.room_by_code(self.conn, code)
        repo.save_reading(self.conn, room["id"], period, 110, 2150,
                          water_prev=100, electric_prev=2000)
        repo.generate_invoices(self.conn, period, issue_date=f"{period}-01")
        invoice = [i for i in repo.invoices(self.conn, period) if i["room_code"] == code][0]
        if pay:
            repo.record_payment(self.conn, invoice["id"], pay, paid_on=f"{period}-05")
        return invoice

    def board(self, period="2026-07", as_of="2026-07-20"):
        return {r["code"]: r for r in reports.room_board(self.conn, period, as_of)}

    def test_covers_every_room_exactly_once(self):
        board = reports.room_board(self.conn, "2026-07", "2026-07-20")
        self.assertEqual(len(board), 30)
        self.assertEqual(len({r["code"] for r in board}), 30)

    def test_vacant_room_reports_its_asking_rent(self):
        room = self.board()["101"]
        self.assertEqual(room["state"], "vacant")
        self.assertEqual(room["label"], "ว่าง")
        self.assertFalse(room["occupied"])
        self.assertEqual(room["rent"], repo.room_by_code(self.conn, "101")["base_rent"])

    def test_paid_room(self):
        self.move_in("101")
        self.bill("101", pay=money.baht(4880))
        room = self.board()["101"]
        self.assertEqual(room["state"], "paid")
        self.assertEqual(room["label"], "ชำระแล้ว")
        self.assertEqual(room["outstanding"], 0)

    def test_unpaid_room_shows_the_amount_and_the_days(self):
        self.move_in("101")
        self.bill("101")
        room = self.board()["101"]
        self.assertEqual(room["state"], "owing")
        self.assertEqual(room["label"], "ค้างชำระ")
        self.assertEqual(room["outstanding"], money.baht(4880))
        self.assertEqual(room["days_overdue"], 15)  # due 07-05, as of 07-20
        self.assertIn("4,880", room["detail"])

    def test_partial_payment_still_counts_as_owing(self):
        self.move_in("101")
        self.bill("101", pay=money.baht(2000))
        room = self.board()["101"]
        self.assertEqual(room["state"], "owing")
        self.assertEqual(room["outstanding"], money.baht(2880))

    def test_occupied_but_not_yet_invoiced(self):
        self.move_in("101")
        room = self.board()["101"]
        self.assertEqual(room["state"], "occupied")
        self.assertEqual(room["label"], "รอออกบิล")
        self.assertEqual(room["outstanding"], 0)

    def test_maintenance_wins_over_everything(self):
        self.conn.execute("UPDATE room SET status='maintenance' WHERE code='105'")
        self.conn.commit()
        self.assertEqual(self.board()["105"]["state"], "maintenance")

    def test_old_debt_shows_even_when_this_month_is_not_billed_yet(self):
        # June unpaid; August has no invoice at all. The room must still read as owing.
        self.move_in("101", start="2026-06-01")
        self.bill("101", period="2026-06")
        room = self.board(period="2026-08", as_of="2026-08-20")["101"]
        self.assertEqual(room["state"], "owing")
        self.assertEqual(room["outstanding"], money.baht(4880))
        self.assertGreater(room["days_overdue"], 60)

    def test_debt_accumulates_across_periods(self):
        self.move_in("101", start="2026-06-01")
        self.bill("101", period="2026-06")
        self.bill("101", period="2026-07")
        room = self.board()["101"]
        self.assertEqual(room["outstanding"], money.baht(4880) * 2)

    def test_occupied_room_reports_the_lease_rent_not_the_room_rent(self):
        self.move_in("101", monthly_rent=money.baht(4200))
        self.assertEqual(self.board()["101"]["rent"], money.baht(4200))


class TestReports(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        # Two occupied rooms, one paid in full, one unpaid.
        for code, name in (("101", "สมชาย"), ("205", "สมหญิง")):
            self.move_in(code, name=name)
            room = repo.room_by_code(self.conn, code)
            repo.save_reading(self.conn, room["id"], "2026-07", 110, 2150,
                              water_prev=100, electric_prev=2000)
        repo.generate_invoices(self.conn, "2026-07", issue_date="2026-07-01")
        paid_invoice = [i for i in repo.invoices(self.conn, "2026-07") if i["room_code"] == "101"][0]
        repo.record_payment(self.conn, paid_invoice["id"], money.baht(4880), paid_on="2026-07-05")
        repo.record_expense(self.conn, "2026-07-10", "repair", "ซ่อมปั๊มน้ำ", money.baht(3000))
        repo.record_expense(self.conn, "2026-07-15", "utility", "ค่าน้ำประปารวม", money.baht(2000))

    def test_monthly_summary_separates_invoiced_from_collected(self):
        s = reports.monthly_summary(self.conn, "2026-07")
        self.assertEqual(s.invoiced, money.baht(4880) * 2)
        self.assertEqual(s.collected, money.baht(4880))
        self.assertEqual(s.gap, money.baht(4880))
        self.assertAlmostEqual(s.collection_rate, 0.5)

    def test_net_is_cash_in_minus_cash_out(self):
        s = reports.monthly_summary(self.conn, "2026-07")
        self.assertEqual(s.expenses, money.baht(5000))
        self.assertEqual(s.net, money.baht(4880) - money.baht(5000))

    def test_occupancy_rate(self):
        s = reports.monthly_summary(self.conn, "2026-07")
        self.assertEqual(s.rooms_total, 30)
        self.assertEqual(s.rooms_occupied, 2)
        self.assertAlmostEqual(s.occupancy_rate, 2 / 30)

    def test_income_is_broken_down_by_kind(self):
        s = reports.monthly_summary(self.conn, "2026-07")
        self.assertEqual(s.by_kind["rent"], money.baht(3500) * 2)
        self.assertEqual(s.by_kind["water"], money.baht(180) * 2)
        self.assertEqual(s.by_kind["electric"], money.baht(1200) * 2)

    def test_expenses_broken_down_by_category(self):
        s = reports.monthly_summary(self.conn, "2026-07")
        self.assertEqual(s.by_expense_category["repair"], money.baht(3000))
        self.assertEqual(s.by_expense_category["utility"], money.baht(2000))

    def test_arrears_lists_only_the_unpaid_room(self):
        rows = reports.arrears(self.conn, as_of="2026-07-20")
        self.assertEqual([r.room_code for r in rows], ["205"])
        self.assertEqual(rows[0].outstanding, money.baht(4880))
        self.assertEqual(rows[0].days_overdue, 15)

    def test_aging_buckets(self):
        aging = reports.arrears_aging(self.conn, as_of="2026-09-15")
        self.assertEqual(aging["61-90 วัน"], money.baht(4880))
        self.assertEqual(aging["1-30 วัน"], 0)

    def test_payment_in_a_later_month_counts_as_that_months_income(self):
        unpaid = [i for i in repo.invoices(self.conn, "2026-07") if i["room_code"] == "205"][0]
        repo.record_payment(self.conn, unpaid["id"], money.baht(4880), paid_on="2026-08-03")
        july = reports.monthly_summary(self.conn, "2026-07")
        august = reports.monthly_summary(self.conn, "2026-08")
        self.assertEqual(july.collected, money.baht(4880))
        self.assertEqual(august.collected, money.baht(4880))
        self.assertEqual(august.invoiced, 0)  # nothing billed in August

    def test_dashboard_flags_the_unread_meters(self):
        self.move_in("310", name="ผู้เช่าใหม่")
        data = reports.dashboard(self.conn, "2026-07", as_of="2026-07-20")
        self.assertIn("310", data["unread_meters"])
        self.assertEqual(data["arrears_count"], 1)

    def test_dashboard_flags_rooms_read_but_not_yet_invoiced(self):
        self.move_in("310", name="ผู้เช่าใหม่")
        room = repo.room_by_code(self.conn, "310")
        repo.save_reading(self.conn, room["id"], "2026-07", 50, 900, water_prev=40, electric_prev=800)
        data = reports.dashboard(self.conn, "2026-07", as_of="2026-07-20")
        self.assertNotIn("310", data["unread_meters"])
        self.assertIn("310", data["uninvoiced"])

    def test_room_performance_reports_vacancy_as_months_billed(self):
        rows = {r["room_code"]: r for r in reports.room_performance(self.conn, 2026)}
        self.assertEqual(rows["101"]["months_billed"], 1)
        self.assertEqual(rows["102"]["months_billed"], 0)
        self.assertEqual(rows["101"]["collected"], money.baht(4880))
        self.assertEqual(rows["205"]["outstanding"], money.baht(4880))

    def test_yearly_table_has_twelve_months(self):
        table = reports.yearly_table(self.conn, 2026)
        self.assertEqual(len(table), 12)
        self.assertEqual(table[6].period, "2026-07")
        self.assertEqual(table[6].collected, money.baht(4880))
        self.assertEqual(table[0].collected, 0)

    def test_utility_usage_per_room(self):
        usage = {u["room_code"]: u for u in reports.utility_usage(self.conn, "2026-07")}
        self.assertEqual(usage["101"]["water_units"], 10)
        self.assertEqual(usage["101"]["electric_units"], 150)


if __name__ == "__main__":
    unittest.main()
