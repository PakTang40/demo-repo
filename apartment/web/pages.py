"""Operational pages: dashboard, room grid, meter sheet, invoices.

Each function takes a connection plus already-parsed params and returns an HTML
string. Routing and form parsing live in `server.py`; nothing here touches the
request object, so a page can be rendered in a test with a plain dict.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

from .. import billing, db, money, repo, reports
from .layout import (baht_cell, esc, eyebrow, flash, page, period_picker,
                     status_pill, tile)


def _building(conn: sqlite3.Connection) -> str:
    return db.get_settings(conn).get("building_name", "หอพัก")


def _today() -> str:
    return dt.date.today().isoformat()


def _this_period() -> str:
    return _today()[:7]


# ------------------------------------------------------------------- dashboard


def dashboard_page(conn: sqlite3.Connection, period: str | None = None, notice: str = "") -> str:
    period = period or _this_period()
    as_of = _today()
    data = reports.dashboard(conn, period, as_of)
    s = data["summary"]

    tiles = "".join(
        [
            tile("รายรับเดือนนี้", money.fmt(s.collected), f"เก็บได้ {s.collection_rate:.0%} ของที่แจ้งหนี้"),
            tile("ออกใบแจ้งหนี้", money.fmt(s.invoiced), f"ส่วนต่าง {money.fmt(s.gap)}"),
            tile("รายจ่าย", money.fmt(s.expenses)),
            tile(
                "กำไรสุทธิ (เงินสด)",
                money.fmt(s.net),
                "รายรับ - รายจ่าย",
                tone="pos" if s.net >= 0 else "neg",
            ),
            tile(
                "ห้องมีผู้เช่า",
                f"{s.rooms_occupied}/{s.rooms_total}",
                f"อัตราการเช่า {s.occupancy_rate:.0%}",
            ),
            tile(
                "ค้างชำระทั้งหมด",
                money.fmt(data["arrears_total"]),
                f"{data['arrears_count']} ใบ",
                tone="neg" if data["arrears_total"] else "",
            ),
        ]
    )

    todo = []
    if data["unread_meters"]:
        codes = ", ".join(data["unread_meters"])
        todo.append(
            f'<li>ยังไม่ได้จดมิเตอร์ {len(data["unread_meters"])} ห้อง: {esc(codes)} '
            f'— <a href="/meters?period={esc(period)}">ไปจดมิเตอร์</a></li>'
        )
    if data["uninvoiced"]:
        codes = ", ".join(data["uninvoiced"])
        todo.append(
            f'<li>จดมิเตอร์แล้วแต่ยังไม่ออกบิล {len(data["uninvoiced"])} ห้อง: {esc(codes)} '
            f'— <a href="/invoices?period={esc(period)}">ไปออกบิล</a></li>'
        )
    todo_html = (
        f'<div class="card"><h2 style="margin-top:0">สิ่งที่ต้องทำ</h2><ul>{"".join(todo)}</ul></div>'
        if todo
        else '<div class="card"><strong>งานประจำเดือนครบแล้ว</strong> '
        '<span class="muted">— จดมิเตอร์และออกบิลเรียบร้อยทุกห้อง</span></div>'
    )

    aging_rows = "".join(
        f"<tr><td>{esc(bucket)}</td>{baht_cell(amount)}</tr>"
        for bucket, amount in data["aging"].items()
        if amount
    )
    aging_html = (
        f"""<h2>อายุหนี้ค้างชำระ</h2><div class="tablewrap"><table>
        <thead><tr><th>ช่วงเวลา</th><th class="num">ยอดค้าง (บาท)</th></tr></thead>
        <tbody>{aging_rows}</tbody></table></div>"""
        if aging_rows
        else ""
    )

    arrears_rows = "".join(
        f"""<tr>
          <td><a href="/room?code={esc(r.room_code)}"><strong>{esc(r.room_code)}</strong></a></td>
          <td>{esc(r.tenant_name)}</td>
          <td>{esc(r.period)}</td>
          <td>{esc(r.due_date)}</td>
          <td>{esc(r.days_overdue)} วัน</td>
          {baht_cell(r.outstanding)}
          <td>{esc(r.bucket)}</td>
        </tr>"""
        for r in data["arrears"][:15]
    )
    arrears_html = (
        f"""<h2>รายการค้างชำระ (เรียงตามค้างนานที่สุด)</h2><div class="tablewrap"><table>
        <thead><tr><th>ห้อง</th><th>ผู้เช่า</th><th>งวด</th><th>ครบกำหนด</th><th>เกินกำหนด</th>
        <th class="num">ยอดค้าง</th><th>ช่วง</th></tr></thead>
        <tbody>{arrears_rows}</tbody></table></div>"""
        if arrears_rows
        else '<p class="muted">ไม่มีรายการค้างชำระ</p>'
    )

    body = f"""
      {eyebrow("สรุปผลประกอบการ")}
      <h1>ภาพรวม {esc(period)}</h1>
      <p class="sub">ข้อมูล ณ วันที่ {esc(as_of)}</p>
      {flash(notice) if notice else ""}
      {period_picker("/", period)}
      <div class="grid tiles">{tiles}</div>
      {todo_html}
      {aging_html}
      {arrears_html}
    """
    return page("ภาพรวม", body, active="/", building=_building(conn))


# ----------------------------------------------------------------------- rooms


def rooms_page(conn: sqlite3.Connection, notice: str = "", error: str = "") -> str:
    """The floor plan. Its whole job is to be readable in one glance, so every plate
    states its status in words as well as colour, and shows the amount owed."""
    board = reports.room_board(conn, _this_period(), _today())

    total = len(board)
    occupied = sum(1 for r in board if r["occupied"])
    vacant = sum(1 for r in board if r["state"] == "vacant")
    owing_rooms = [r for r in board if r["state"] == "owing"]
    paid_rooms = sum(1 for r in board if r["state"] == "paid")
    maintenance = sum(1 for r in board if r["state"] == "maintenance")
    rent_roll = sum(r["rent"] for r in board if r["occupied"])
    owed_total = sum(r["outstanding"] for r in board)

    tiles = "".join([
        tile("มีผู้เช่า", f"{occupied}/{total}",
             f"อัตราการเช่า {occupied / total:.0%}" if total else ""),
        tile("ห้องว่าง", str(vacant),
             f"เสียโอกาส {money.fmt(sum(r['rent'] for r in board if r['state'] == 'vacant'))}/เดือน"
             if vacant else "เต็มทุกห้อง"),
        tile("ค้างชำระ", money.fmt(owed_total), f"{len(owing_rooms)} ห้อง",
             tone="neg" if owed_total else ""),
        tile("ค่าเช่ารวมต่อเดือน", money.fmt(rent_roll), "จากห้องที่มีผู้เช่าอยู่"),
    ])

    # The legend follows the fills, not the internal state names: two states share the
    # green plate (settled and not-yet-billed), so they share one line here. Naming
    # both keeps the words on the plates predictable.
    waiting = sum(1 for r in board if r["state"] == "occupied")
    legend_items = [
        ("vacant", "ห้องว่าง — ยังไม่มีรายได้", vacant),
        ("occupied", f"มีผู้เช่า ({paid_rooms} ชำระแล้ว · {waiting} รอออกบิล)", paid_rooms + waiting),
        ("owing", "ค้างชำระ — ต้องตามเก็บ", len(owing_rooms)),
    ]
    if maintenance:
        legend_items.append(("maintenance", "ปิดซ่อม", maintenance))
    legend = "".join(
        f'<span class="item"><span class="sw {cls}"></span>{esc(label)} <b>{count}</b> ห้อง</span>'
        for cls, label, count in legend_items
    )

    floors_html = ""
    for floor in sorted({r["floor"] for r in board}):
        on_floor = [r for r in board if r["floor"] == floor]
        cards = ""
        for room in on_floor:
            who = esc(room["tenant_name"]) if room["occupied"] else "ยังไม่มีผู้เช่า"
            # On an empty plate the rent is not income, it is the income being missed.
            rent_prefix = "" if room["occupied"] else "ตั้งไว้ "
            rent_line = (
                f'<div class="rent">{rent_prefix}'
                f'{esc(money.fmt(room["rent"], symbol=False))} ฿ / เดือน</div>'
            )
            overdue = (
                f'<div class="over">เกินกำหนด {esc(room["days_overdue"])} วัน</div>'
                if room["days_overdue"]
                else ""
            )
            detail = f'<span class="amt">{esc(room["detail"])}</span>' if room["detail"] else ""
            cards += f"""<a class="room {esc(room['state'])}" href="/room?code={esc(room['code'])}"
                            title="ห้อง {esc(room['code'])} — {esc(room['label'])}">
              <div class="room-body">
                <div class="code">{esc(room['code'])}</div>
                <div class="who">{who}</div>
                {rent_line}{overdue}
              </div>
              <div class="room-status">{esc(room['label'])} {detail}</div>
            </a>"""

        floor_occupied = sum(1 for r in on_floor if r["occupied"])
        floor_owed = sum(r["outstanding"] for r in on_floor)
        floor_rent = sum(r["rent"] for r in on_floor if r["occupied"])
        owed_stat = (
            f'<span>ค้างชำระ <b style="color:var(--danger)">{esc(money.fmt(floor_owed))}</b></span>'
            if floor_owed
            else '<span>ไม่มีค้างชำระ</span>'
        )
        floors_html += f"""
          <div class="floor-head">
            <div class="title">ชั้น {esc(floor)}</div>
            <div class="stats">
              <span>มีผู้เช่า <b>{esc(floor_occupied)}/{esc(len(on_floor))}</b></span>
              <span>ค่าเช่ารวม <b>{esc(money.fmt(floor_rent))}</b></span>
              {owed_stat}
            </div>
          </div>
          <div class="rooms">{cards}</div>"""

    action = ""
    if owing_rooms:
        worst = sorted(owing_rooms, key=lambda r: -r["outstanding"])[:5]
        listed = " · ".join(
            f"{r['code']} {r['tenant_name']} {money.fmt(r['outstanding'])}" for r in worst
        )
        more = f" · และอีก {len(owing_rooms) - len(worst)} ห้อง" if len(owing_rooms) > len(worst) else ""
        action = flash(f"ต้องตามเก็บ {len(owing_rooms)} ห้อง — {listed}{more}", "err")

    body = f"""
      {eyebrow("ผังอาคาร")}
      <h1>ห้องพัก</h1>
      <p class="sub">ช่อง<strong style="color:var(--plan-vacant-edge)">สีแดง</strong>คือห้องว่าง
         ช่อง<strong style="color:var(--plan-live-edge)">สีเขียว</strong>คือห้องที่มีผู้เช่าอยู่
         ถ้ามีแถบ<strong>สีเหลือง</strong>อยู่ด้านล่างแปลว่าห้องนั้นค้างชำระ —
         คลิกที่ห้องเพื่อดูรายละเอียดและประวัติการชำระ</p>
      {flash(notice) if notice else ""}{flash(error, "err") if error else ""}
      <div class="grid tiles" style="margin-bottom:1.6rem">{tiles}</div>
      {action}
      <div class="legend">{legend}</div>
      {floors_html}
    """
    return page("ห้องพัก", body, active="/rooms", building=_building(conn))


def room_page(conn: sqlite3.Connection, code: str, notice: str = "", error: str = "") -> str:
    room = repo.room_by_code(conn, code)
    if room is None:
        return page("ไม่พบห้อง", f"<h1>ไม่พบห้อง {esc(code)}</h1>", building=_building(conn))

    lease = conn.execute(
        """SELECT l.*, t.full_name, t.phone, t.line_id, t.national_id
           FROM lease l JOIN tenant t ON t.id = l.tenant_id
           WHERE l.room_id = ? AND l.status = 'active'""",
        (room["id"],),
    ).fetchone()

    settings = db.get_settings(conn)

    if lease:
        rates = billing.resolve_rates(dict(lease), settings)
        occupant = f"""
        <div class="card">
          <div class="row">
            <div>
              <h2 style="margin-top:0">{esc(lease['full_name'])}</h2>
              <div class="muted">โทร {esc(lease['phone'] or '-')} · LINE {esc(lease['line_id'] or '-')}</div>
              <div class="muted">เข้าพัก {esc(lease['start_date'])} · เงินประกัน {esc(money.fmt(lease['deposit']))}</div>
            </div>
            <div class="right">
              <div class="muted">ค่าเช่า/เดือน</div>
              <div style="font-size:1.4rem;font-weight:650">{esc(money.fmt(lease['monthly_rent']))}</div>
              <div class="muted">น้ำ {esc(money.fmt(rates.water_rate))}/หน่วย ·
                   ไฟ {esc(money.fmt(rates.electric_rate))}/หน่วย</div>
            </div>
          </div>
          <form class="inline noprint" method="post" action="/room/move-out" style="margin-top:.8rem">
            <input type="hidden" name="lease_id" value="{esc(lease['id'])}">
            <input type="hidden" name="code" value="{esc(code)}">
            <div><label>วันที่ย้ายออก</label><input type="date" name="ended_on" value="{esc(_today())}" required></div>
            <div><label>คืนเงินประกัน (บาท)</label><input type="number" step="0.01" name="deposit_refunded" value="0"></div>
            <button class="danger" type="submit"
                    onclick="return confirm('ยืนยันการย้ายออกและปิดสัญญาเช่า?')">บันทึกย้ายออก</button>
          </form>
        </div>"""
    else:
        occupant = f"""
        <div class="card">
          <h2 style="margin-top:0">ห้องว่าง — รับผู้เช่าใหม่</h2>
          <form method="post" action="/room/move-in" class="inline">
            <input type="hidden" name="code" value="{esc(code)}">
            <div><label>ชื่อ-นามสกุลผู้เช่า</label><input name="full_name" required style="min-width:190px"></div>
            <div><label>เบอร์โทร</label><input name="phone"></div>
            <div><label>LINE ID</label><input name="line_id"></div>
            <div><label>เลขบัตรประชาชน</label><input name="national_id"></div>
            <div><label>วันเริ่มสัญญา</label><input type="date" name="start_date" value="{esc(_today())}" required></div>
            <div><label>ค่าเช่า/เดือน (บาท)</label>
              <input type="number" step="0.01" name="monthly_rent"
                     value="{esc(money.to_baht(room['base_rent']))}"></div>
            <div><label>เงินประกัน (บาท)</label><input type="number" step="0.01" name="deposit"
                     placeholder="ว่าง = {esc(settings.get('deposit_months', '2'))} เดือน"></div>
            <button type="submit">บันทึกผู้เช่าเข้า</button>
          </form>
        </div>"""

    invoice_rows = ""
    for inv in conn.execute(
        """SELECT i.*, COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.invoice_id = i.id), 0) AS paid
           FROM invoice i WHERE i.room_id = ? AND i.status = 'issued'
           ORDER BY i.period DESC LIMIT 24""",
        (room["id"],),
    ):
        settled = billing.settlement(inv["total"], [inv["paid"]])
        invoice_rows += f"""<tr>
          <td>{esc(inv['period'])}</td>
          <td><a href="/invoice?id={esc(inv['id'])}">{esc(inv['number'])}</a></td>
          <td>{esc(inv['due_date'])}</td>
          {baht_cell(inv['total'])}{baht_cell(inv['paid'])}{baht_cell(settled.outstanding)}
          <td>{status_pill(settled.status)}</td>
        </tr>"""

    history = ""
    for old in conn.execute(
        """SELECT l.*, t.full_name FROM lease l JOIN tenant t ON t.id = l.tenant_id
           WHERE l.room_id = ? AND l.status = 'ended' ORDER BY l.start_date DESC""",
        (room["id"],),
    ):
        history += (
            f"<tr><td>{esc(old['full_name'])}</td><td>{esc(old['start_date'])}</td>"
            f"<td>{esc(old['ended_on'] or '-')}</td>{baht_cell(old['monthly_rent'])}</tr>"
        )

    body = f"""
      <h1>ห้อง {esc(code)} <span class="muted" style="font-size:1rem">ชั้น {esc(room['floor'])}</span>
          {status_pill(room['status'])}</h1>
      <p class="sub"><a href="/rooms">← กลับไปผังห้อง</a></p>
      {flash(notice) if notice else ""}{flash(error, "err") if error else ""}
      {occupant}
      <h2>ประวัติใบแจ้งหนี้</h2>
      <div class="tablewrap"><table>
        <thead><tr><th>งวด</th><th>เลขที่</th><th>ครบกำหนด</th><th class="num">ยอดรวม</th>
        <th class="num">ชำระแล้ว</th><th class="num">คงค้าง</th><th>สถานะ</th></tr></thead>
        <tbody>{invoice_rows or '<tr><td colspan="7" class="empty">ยังไม่มีใบแจ้งหนี้</td></tr>'}</tbody>
      </table></div>
      <h2>ผู้เช่าเดิม</h2>
      <div class="tablewrap"><table>
        <thead><tr><th>ชื่อ</th><th>เข้าพัก</th><th>ย้ายออก</th><th class="num">ค่าเช่า</th></tr></thead>
        <tbody>{history or '<tr><td colspan="4" class="empty">ไม่มีประวัติ</td></tr>'}</tbody>
      </table></div>
    """
    return page(f"ห้อง {code}", body, active="/rooms", building=_building(conn))


# ---------------------------------------------------------------------- meters


def meters_page(conn: sqlite3.Connection, period: str | None = None, notice: str = "", error: str = "") -> str:
    """The monthly walk-around sheet: every occupied room, previous reading shown."""
    period = period or _this_period()
    existing = repo.readings_for(conn, period)
    previous = repo.readings_for(conn, billing.prev_period(period))

    rows = ""
    first_months = 0
    for lease in repo.active_leases(conn):
        room_id = lease["room_id"]
        current = existing.get(room_id)
        prior = previous.get(room_id)
        water_curr = current["water_curr"] if current else ""
        elec_curr = current["electric_curr"] if current else ""

        # A room with no earlier reading has no consumption history to subtract from.
        # Defaulting its "previous" to 0 would bill the tenant for the meter's entire
        # lifetime, so the opening numbers stay editable until a prior month exists.
        if current:
            water_prev, elec_prev = current["water_prev"], current["electric_prev"]
            opening = False
        elif prior:
            water_prev, elec_prev = prior["water_curr"], prior["electric_curr"]
            opening = False
        else:
            water_prev = elec_prev = ""
            opening = True
            first_months += 1

        if opening:
            water_prev_cell = (
                f'<td><input type="number" step="0.01" name="water_prev_{esc(room_id)}" '
                f'value="" placeholder="เลขตั้งต้น" style="width:110px"></td>'
            )
            elec_prev_cell = (
                f'<td><input type="number" step="0.01" name="electric_prev_{esc(room_id)}" '
                f'value="" placeholder="เลขตั้งต้น" style="width:110px"></td>'
            )
            done = '<span class="pill warn">เดือนแรก</span>'
        else:
            water_prev_cell = f'<td class="num muted">{esc(water_prev)}</td>'
            elec_prev_cell = f'<td class="num muted">{esc(elec_prev)}</td>'
            done = (
                '<span class="pill ok">บันทึกแล้ว</span>'
                if current
                else '<span class="pill muted">รอจด</span>'
            )

        rows += f"""<tr>
          <td><strong>{esc(lease['room_code'])}</strong></td>
          <td>{esc(lease['tenant_name'])}</td>
          {water_prev_cell}
          <td><input type="number" step="0.01" name="water_{esc(room_id)}" value="{esc(water_curr)}"
                     style="width:110px"></td>
          {elec_prev_cell}
          <td><input type="number" step="0.01" name="electric_{esc(room_id)}" value="{esc(elec_curr)}"
                     style="width:110px"></td>
          <td>{done}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="7" class="empty">ยังไม่มีห้องที่มีผู้เช่า</td></tr>'

    opening_note = (
        flash(
            f"มี {first_months} ห้องที่ยังไม่เคยจดมิเตอร์ — ต้องกรอก “เลขตั้งต้น” ด้วย "
            "ไม่งั้นระบบจะคิดค่าน้ำค่าไฟย้อนหลังตั้งแต่ตอนติดมิเตอร์",
            "err",
        )
        if first_months
        else ""
    )

    body = f"""
      <h1>จดมิเตอร์ — งวด {esc(period)}</h1>
      <p class="sub">กรอกเฉพาะเลขล่าสุดที่อ่านได้ ช่องที่เว้นว่างจะไม่ถูกบันทึก ·
         เลขครั้งก่อนดึงมาให้อัตโนมัติ</p>
      {opening_note}
      {flash(notice) if notice else ""}{flash(error, "err") if error else ""}
      {period_picker("/meters", period)}
      <form method="post" action="/meters">
        <input type="hidden" name="period" value="{esc(period)}">
        <div><label>วันที่จด</label><input type="date" name="read_date" value="{esc(_today())}"></div>
        <div class="tablewrap" style="margin-top:.6rem"><table>
          <thead><tr><th>ห้อง</th><th>ผู้เช่า</th>
            <th class="num">น้ำครั้งก่อน</th><th>น้ำครั้งนี้</th>
            <th class="num">ไฟครั้งก่อน</th><th>ไฟครั้งนี้</th><th>สถานะ</th></tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
        <button type="submit">บันทึกมิเตอร์ทั้งหมด</button>
      </form>
    """
    return page("จดมิเตอร์", body, active="/meters", building=_building(conn))


# -------------------------------------------------------------------- invoices


def invoices_page(conn: sqlite3.Connection, period: str | None = None, notice: str = "",
                  error: str = "", items: list[str] | None = None) -> str:
    period = period or _this_period()
    rows_data = repo.invoices(conn, period)
    pending = reports.uninvoiced_rooms(conn, period)
    unread = reports.unread_meters(conn, period)

    rows = ""
    total_billed = total_paid = 0
    for inv in rows_data:
        settled = billing.settlement(inv["total"], [inv["paid"]])
        total_billed += inv["total"]
        total_paid += inv["paid"]
        rows += f"""<tr>
          <td><strong>{esc(inv['room_code'])}</strong></td>
          <td>{esc(inv['tenant_name'])}</td>
          <td><a href="/invoice?id={esc(inv['id'])}">{esc(inv['number'])}</a></td>
          <td>{esc(inv['due_date'])}</td>
          {baht_cell(inv['total'])}{baht_cell(inv['paid'])}{baht_cell(settled.outstanding)}
          <td>{status_pill(settled.status)}</td>
          <td class="noprint">
            <form method="post" action="/payment" class="inline">
              <input type="hidden" name="invoice_id" value="{esc(inv['id'])}">
              <input type="hidden" name="period" value="{esc(period)}">
              <input type="number" step="0.01" name="amount" style="width:105px"
                     value="{esc(money.to_baht(settled.outstanding))}" required>
              <select name="method">
                <option value="transfer">โอน</option><option value="cash">เงินสด</option>
                <option value="promptpay">พร้อมเพย์</option>
              </select>
              <button class="secondary" type="submit">รับชำระ</button>
            </form>
          </td>
        </tr>"""

    outstanding = total_billed - total_paid
    foot = (
        f'<tfoot><tr><td colspan="4">รวม {len(rows_data)} ใบ</td>'
        f"{baht_cell(total_billed)}{baht_cell(total_paid)}{baht_cell(outstanding)}"
        f'<td colspan="2"></td></tr></tfoot>'
        if rows_data
        else ""
    )

    warnings = ""
    if unread:
        warnings += flash(f"ยังไม่ได้จดมิเตอร์ {len(unread)} ห้อง — ออกบิลไม่ได้จนกว่าจะจด", "err", unread)
    if pending:
        warnings += flash(f"พร้อมออกบิล {len(pending)} ห้อง", "ok", pending)

    body = f"""
      <h1>ใบแจ้งหนี้ — งวด {esc(period)}</h1>
      <p class="sub">ออกบิลได้เฉพาะห้องที่มีผู้เช่าและจดมิเตอร์แล้ว · กดซ้ำได้ ระบบจะไม่ออกซ้ำ</p>
      {flash(notice, "ok", items) if notice else ""}{flash(error, "err") if error else ""}
      {warnings}
      <div class="card noprint">
        <form class="inline" method="post" action="/invoices/generate">
          <input type="hidden" name="period" value="{esc(period)}">
          <div><label>วันที่ออกบิล</label><input type="date" name="issue_date" value="{esc(_today())}"></div>
          <button type="submit">ออกใบแจ้งหนี้ทั้งงวด</button>
        </form>
        <form class="inline" method="post" action="/invoices/late-fees" style="margin-top:.6rem">
          <input type="hidden" name="period" value="{esc(period)}">
          <button class="secondary" type="submit"
                  onclick="return confirm('เพิ่มค่าปรับล่าช้าให้ทุกใบที่เกินกำหนด?')">คิดค่าปรับล่าช้า</button>
          <span class="muted">เพิ่มได้ครั้งเดียวต่อใบ</span>
        </form>
      </div>
      {period_picker("/invoices", period)}
      <div class="tablewrap"><table>
        <thead><tr><th>ห้อง</th><th>ผู้เช่า</th><th>เลขที่</th><th>ครบกำหนด</th>
          <th class="num">ยอดรวม</th><th class="num">ชำระแล้ว</th><th class="num">คงค้าง</th>
          <th>สถานะ</th><th class="noprint">รับชำระ</th></tr></thead>
        <tbody>{rows or '<tr><td colspan="9" class="empty">ยังไม่มีใบแจ้งหนี้ในงวดนี้</td></tr>'}</tbody>
        {foot}
      </table></div>
    """
    return page("ใบแจ้งหนี้", body, active="/invoices", building=_building(conn))


def invoice_page(conn: sqlite3.Connection, invoice_id: int) -> str:
    """A single printable invoice/receipt — Ctrl+P gives the tenant a clean copy."""
    detail = repo.invoice_detail(conn, invoice_id)
    if detail is None:
        return page("ไม่พบใบแจ้งหนี้", "<h1>ไม่พบใบแจ้งหนี้</h1>", building=_building(conn))

    inv, settled = detail["invoice"], detail["settlement"]
    settings = db.get_settings(conn)

    lines = "".join(
        f"<tr><td>{esc(l['description'])}</td>"
        f'<td class="num">{esc(f"{l["quantity"]:g}")}</td>'
        f"{baht_cell(l['unit_price'])}{baht_cell(l['amount'])}</tr>"
        for l in detail["lines"]
    )
    payments = "".join(
        f"<tr><td>{esc(p['paid_on'])}</td><td>{esc(p['method'])}</td>"
        f"<td>{esc(p['reference'] or '-')}</td>{baht_cell(p['amount'])}</tr>"
        for p in detail["payments"]
    )
    promptpay = settings.get("promptpay_id", "")
    pay_to = (
        f"""<div class="card" style="border-left:2px solid var(--accent)">
              <p class="eyebrow" style="margin-bottom:.2rem">ช่องทางชำระเงิน</p>
              <div>พร้อมเพย์ <span class="figure" style="font-size:1.1rem">{esc(promptpay)}</span></div>
            </div>"""
        if promptpay
        else ""
    )

    body = f"""
      <p class="noprint"><a href="/invoices?period={esc(inv['period'])}">← กลับไปรายการใบแจ้งหนี้</a>
         · <a href="#" onclick="window.print();return false">พิมพ์</a></p>

      <div class="card" style="padding-top:1.6rem">
        <div class="row">
          <div>
            <p class="eyebrow" style="margin-bottom:.35rem">
              {esc(settings.get('building_name', 'หอพัก'))}</p>
            <h1 style="margin:0 0 .3rem">ใบแจ้งหนี้ / ใบเสร็จรับเงิน</h1>
            <div class="muted" style="font-size:.86rem">
              {esc(settings.get('building_address', ''))}</div>
          </div>
          <div class="right">
            <p class="eyebrow" style="margin-bottom:.2rem">เลขที่</p>
            <div class="figure" style="font-size:1.15rem">{esc(inv['number'])}</div>
            <div class="muted" style="font-size:.82rem;margin-top:.45rem">
              งวด {esc(inv['period'])}<br>
              ออกวันที่ {esc(inv['issue_date'])}<br>
              ครบกำหนด {esc(inv['due_date'])}
            </div>
          </div>
        </div>

        <hr class="rule" style="border-top:1px solid var(--accent);opacity:.45;margin:1.3rem 0">

        <div class="row">
          <div>
            <p class="eyebrow" style="margin-bottom:.15rem">ห้องพัก</p>
            <div class="figure">{esc(inv['room_code'])}</div>
          </div>
          <div style="flex:1;min-width:180px">
            <p class="eyebrow" style="margin-bottom:.15rem">ผู้เช่า</p>
            <div style="font-size:1.02rem">{esc(inv['tenant_name'])}</div>
            <div class="muted" style="font-size:.84rem">{esc(inv['tenant_phone'] or '')}</div>
          </div>
          <div class="right">
            <p class="eyebrow" style="margin-bottom:.3rem">สถานะ</p>
            {status_pill(settled.status)}
          </div>
        </div>
      </div>

      <div class="tablewrap"><table>
        <thead><tr><th>รายการ</th><th class="num">จำนวน</th><th class="num">ราคา/หน่วย</th>
          <th class="num">จำนวนเงิน (บาท)</th></tr></thead>
        <tbody>{lines}</tbody>
        <tfoot>
          <tr><td colspan="3" class="right">รวมทั้งสิ้น</td>
              <td class="num figure" style="font-size:1.15rem">
                {esc(money.fmt(inv['total'], symbol=False))}</td></tr>
          <tr><td colspan="3" class="right">ชำระแล้ว</td>{baht_cell(settled.paid)}</tr>
          <tr><td colspan="3" class="right">คงค้าง</td>{baht_cell(settled.outstanding)}</tr>
        </tfoot>
      </table></div>
      {pay_to}

      <h2>ประวัติการชำระ</h2>
      <div class="tablewrap"><table>
        <thead><tr><th>วันที่</th><th>ช่องทาง</th><th>อ้างอิง</th><th class="num">จำนวนเงิน</th></tr></thead>
        <tbody>{payments or '<tr><td colspan="4" class="empty">ยังไม่มีการชำระ</td></tr>'}</tbody>
      </table></div>

      <div class="card noprint">
        <form class="inline" method="post" action="/payment">
          <input type="hidden" name="invoice_id" value="{esc(inv['id'])}">
          <input type="hidden" name="back" value="/invoice?id={esc(inv['id'])}">
          <div><label>วันที่ชำระ</label><input type="date" name="paid_on" value="{esc(_today())}"></div>
          <div><label>จำนวนเงิน (บาท)</label><input type="number" step="0.01" name="amount"
               value="{esc(money.to_baht(settled.outstanding))}" required></div>
          <div><label>ช่องทาง</label><select name="method">
            <option value="transfer">โอน</option><option value="cash">เงินสด</option>
            <option value="promptpay">พร้อมเพย์</option></select></div>
          <div><label>อ้างอิง</label><input name="reference" placeholder="เลขที่สลิป"></div>
          <button type="submit">บันทึกการชำระ</button>
        </form>
      </div>
    """
    return page(inv["number"], body, active="/invoices", building=_building(conn))
