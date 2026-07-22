"""Money pages: expenses, the yearly P&L, per-room performance, and settings."""

from __future__ import annotations

import datetime as dt
import sqlite3

from .. import db, money, repo, reports
from .layout import baht_cell, esc, eyebrow, flash, page, tile

EXPENSE_CATEGORIES = [
    ("utility", "ค่าสาธารณูปโภค (บิลรวมของตึก)"),
    ("repair", "ค่าซ่อมบำรุง"),
    ("salary", "ค่าจ้าง/เงินเดือน"),
    ("tax", "ภาษี/ค่าธรรมเนียม"),
    ("supplies", "วัสดุอุปกรณ์"),
    ("other", "อื่น ๆ"),
]
CATEGORY_LABEL = dict(EXPENSE_CATEGORIES)

MONTH_TH = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
            "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def _building(conn: sqlite3.Connection) -> str:
    return db.get_settings(conn).get("building_name", "หอพัก")


# -------------------------------------------------------------------- expenses


def expenses_page(conn: sqlite3.Connection, period: str | None = None,
                  notice: str = "", error: str = "") -> str:
    period = period or dt.date.today().isoformat()[:7]
    rows_data = repo.expenses(conn, period)

    room_options = "".join(
        f'<option value="{esc(r["id"])}">{esc(r["code"])}</option>' for r in repo.rooms(conn)
    )
    category_options = "".join(
        f'<option value="{esc(key)}">{esc(label)}</option>' for key, label in EXPENSE_CATEGORIES
    )

    rows = ""
    total = 0
    for e in rows_data:
        total += e["amount"]
        rows += (
            f"<tr><td>{esc(e['spent_on'])}</td>"
            f"<td>{esc(CATEGORY_LABEL.get(e['category'], e['category']))}</td>"
            f"<td>{esc(e['description'])}</td>"
            f"<td>{esc(e['room_code'] or 'ทั้งตึก')}</td>"
            f"<td>{esc(e['vendor'] or '-')}</td>"
            f"{baht_cell(e['amount'])}</tr>"
        )

    body = f"""
      {eyebrow("บันทึกรายจ่าย")}
      <h1>รายจ่าย — {esc(period)}</h1>
      <p class="sub">บันทึกทุกบาทที่จ่ายออก ไม่งั้นหน้าภาพรวมจะบอกได้แค่รายรับ ไม่ใช่กำไร</p>
      {flash(notice) if notice else ""}{flash(error, "err") if error else ""}
      <div class="card">
        <form class="inline" method="post" action="/expenses">
          <input type="hidden" name="period" value="{esc(period)}">
          <div><label>วันที่</label><input type="date" name="spent_on"
               value="{esc(dt.date.today().isoformat())}" required></div>
          <div><label>หมวด</label><select name="category">{category_options}</select></div>
          <div><label>รายละเอียด</label><input name="description" required style="min-width:220px"></div>
          <div><label>ห้อง (ถ้าเจาะจง)</label>
            <select name="room_id"><option value="">ทั้งตึก</option>{room_options}</select></div>
          <div><label>ผู้ขาย/ผู้รับเงิน</label><input name="vendor"></div>
          <div><label>จำนวนเงิน (บาท)</label><input type="number" step="0.01" name="amount" required></div>
          <button type="submit">บันทึกรายจ่าย</button>
        </form>
      </div>
      <form class="inline noprint" method="get" action="/expenses">
        <div><label>เดือน</label><input type="month" name="period" value="{esc(period)}"></div>
        <button class="secondary" type="submit">แสดง</button>
      </form>
      <div class="tablewrap"><table>
        <thead><tr><th>วันที่</th><th>หมวด</th><th>รายละเอียด</th><th>ห้อง</th><th>ผู้ขาย</th>
          <th class="num">จำนวนเงิน (บาท)</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="6" class="empty">ยังไม่มีรายจ่ายในเดือนนี้</td></tr>'}</tbody>
        <tfoot><tr><td colspan="5">รวม</td>{baht_cell(total)}</tr></tfoot>
      </table></div>
    """
    return page("รายจ่าย", body, active="/expenses", building=_building(conn))


# --------------------------------------------------------------------- reports


def reports_page(conn: sqlite3.Connection, year: int | None = None, notice: str = "") -> str:
    year = year or dt.date.today().year
    table = reports.yearly_table(conn, year)

    year_invoiced = sum(m.invoiced for m in table)
    year_collected = sum(m.collected for m in table)
    year_expenses = sum(m.expenses for m in table)
    year_net = year_collected - year_expenses
    best = max(table, key=lambda m: m.collected)

    tiles = "".join([
        tile("รายรับทั้งปี", money.fmt(year_collected), f"เก็บได้ {year_collected / year_invoiced:.0%} ของที่แจ้งหนี้" if year_invoiced else ""),
        tile("ออกใบแจ้งหนี้ทั้งปี", money.fmt(year_invoiced)),
        tile("รายจ่ายทั้งปี", money.fmt(year_expenses)),
        tile("กำไรสุทธิทั้งปี", money.fmt(year_net), "รายรับ - รายจ่าย",
             tone="pos" if year_net >= 0 else "neg"),
        tile("เดือนที่เก็บได้มากสุด", MONTH_TH[int(best.period[5:7]) - 1] if best.collected else "-",
             money.fmt(best.collected) if best.collected else ""),
        tile("ค้างชำระสะสม", money.fmt(year_invoiced - year_collected),
             tone="neg" if year_invoiced > year_collected else ""),
    ])

    peak = max((m.collected for m in table), default=0) or 1
    month_rows = ""
    for m in table:
        idx = int(m.period[5:7]) - 1
        share = int(100 * m.collected / peak)
        month_rows += f"""<tr>
          <td>{esc(MONTH_TH[idx])}</td>
          {baht_cell(m.invoiced)}{baht_cell(m.collected)}{baht_cell(m.expenses)}
          {baht_cell(m.net)}
          <td>{esc(f"{m.collection_rate:.0%}") if m.invoiced else "-"}</td>
          <td>{esc(m.rooms_occupied)}/{esc(m.rooms_total)}</td>
          <td style="min-width:120px"><div class="bar"><span style="width:{share}%"></span></div></td>
        </tr>"""

    rooms = reports.room_performance(conn, year)
    room_rows = ""
    for r in sorted(rooms, key=lambda x: -x["collected"]):
        room_rows += (
            f'<tr><td><a href="/room?code={esc(r["room_code"])}"><strong>{esc(r["room_code"])}</strong></a></td>'
            f"<td>{esc(r['floor'])}</td>"
            f"<td>{esc(r['months_billed'])}/12</td>"
            f"{baht_cell(r['invoiced'])}{baht_cell(r['collected'])}{baht_cell(r['outstanding'])}</tr>"
        )

    body = f"""
      {eyebrow("งบกำไรขาดทุน")}
      <h1>รายงานการเงิน ปี {esc(year)}</h1>
      <p class="sub">รายรับนับตามเงินที่ได้รับจริงในเดือนนั้น (เกณฑ์เงินสด) ไม่ใช่ยอดที่ออกบิล</p>
      {flash(notice) if notice else ""}
      <form class="inline noprint" method="get" action="/reports">
        <div><label>ปี</label><input type="number" name="year" value="{esc(year)}" style="width:100px"></div>
        <button class="secondary" type="submit">แสดง</button>
        <a href="/export/excel?year={esc(year)}"><button class="secondary" type="button">ดาวน์โหลด Excel</button></a>
      </form>
      <div class="grid tiles">{tiles}</div>

      <h2>สรุปรายเดือน</h2>
      <div class="tablewrap"><table>
        <thead><tr><th>เดือน</th><th class="num">ออกบิล</th><th class="num">เก็บได้</th>
          <th class="num">รายจ่าย</th><th class="num">กำไรสุทธิ</th><th>อัตราเก็บเงิน</th>
          <th>ห้องมีผู้เช่า</th><th>สัดส่วน</th></tr></thead>
        <tbody>{month_rows}</tbody>
        <tfoot><tr><td>รวม</td>{baht_cell(year_invoiced)}{baht_cell(year_collected)}
          {baht_cell(year_expenses)}{baht_cell(year_net)}<td colspan="3"></td></tr></tfoot>
      </table></div>

      <h2>ผลตอบแทนรายห้อง</h2>
      <div class="tablewrap"><table>
        <thead><tr><th>ห้อง</th><th>ชั้น</th><th>เดือนที่ออกบิล</th>
          <th class="num">ออกบิล</th><th class="num">เก็บได้</th><th class="num">คงค้าง</th></tr></thead>
        <tbody>{room_rows}</tbody>
      </table></div>
    """
    return page("รายงานการเงิน", body, active="/reports", building=_building(conn))


# -------------------------------------------------------------------- settings


SETTING_FIELDS = [
    ("building_name", "ชื่อหอพัก", "text"),
    ("building_address", "ที่อยู่ (แสดงบนใบแจ้งหนี้)", "text"),
    ("promptpay_id", "พร้อมเพย์ (แสดงบนใบแจ้งหนี้)", "text"),
    ("base_rent", "ค่าเช่าตั้งต้นของห้องใหม่", "money"),
    ("water_rate", "ค่าน้ำต่อหน่วย", "money"),
    ("electric_rate", "ค่าไฟต่อหน่วย", "money"),
    ("common_fee", "ค่าส่วนกลางต่อเดือน (0 = ไม่เก็บ)", "money"),
    ("deposit_months", "เงินประกัน (กี่เดือน)", "number"),
    ("due_day", "วันครบกำหนดชำระของทุกเดือน", "number"),
    ("late_fee_per_day", "ค่าปรับล่าช้าต่อวัน", "money"),
    ("late_fee_grace_days", "ผ่อนผันกี่วันก่อนคิดค่าปรับ", "number"),
]


def settings_page(conn: sqlite3.Connection, notice: str = "", error: str = "") -> str:
    current = db.get_settings(conn)
    fields = ""
    for key, label, kind in SETTING_FIELDS:
        raw = current.get(key, "")
        if kind == "money":
            value = esc(money.to_baht(int(raw or 0)))
            control = f'<input type="number" step="0.01" name="{esc(key)}" value="{value}">'
            label += " (บาท)"
        elif kind == "number":
            control = f'<input type="number" name="{esc(key)}" value="{esc(raw)}">'
        else:
            control = f'<input name="{esc(key)}" value="{esc(raw)}" style="min-width:280px">'
        fields += f'<div style="margin-bottom:.7rem"><label>{esc(label)}</label>{control}</div>'

    body = f"""
      <h1>ตั้งค่า</h1>
      <p class="sub">อัตราที่แก้ที่นี่มีผลกับ<strong>บิลที่ออกใหม่เท่านั้น</strong> —
         ใบที่ออกไปแล้วเก็บอัตราของตัวเองไว้ในบรรทัดรายการ จึงไม่ถูกแก้ย้อนหลัง</p>
      {flash(notice) if notice else ""}{flash(error, "err") if error else ""}
      <div class="card" style="max-width:560px">
        <form method="post" action="/settings">{fields}
          <button type="submit">บันทึกการตั้งค่า</button>
        </form>
      </div>
      <div class="card" style="max-width:560px">
        <h2 style="margin-top:0">สำรองข้อมูล</h2>
        <p class="muted">ข้อมูลทั้งหมดอยู่ในไฟล์เดียว — คัดลอกไฟล์นี้ไปเก็บไว้ที่อื่นคือการสำรองข้อมูลที่สมบูรณ์</p>
        <code>{esc(db.DEFAULT_DB)}</code>
        <form method="post" action="/backup" style="margin-top:.7rem">
          <button class="secondary" type="submit">สำรองข้อมูลตอนนี้</button>
        </form>
      </div>
    """
    return page("ตั้งค่า", body, active="/settings", building=_building(conn))
