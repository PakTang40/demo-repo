"""HTTP plumbing: a router over stdlib http.server.

Deliberately small. Handlers are plain functions returning either an HTML string
or a `Redirect`, and every POST redirects afterwards (POST/Redirect/GET) so the
owner can refresh an invoice page without paying a tenant twice.

Not exposed to the internet: it binds to 127.0.0.1 unless `--host` says otherwise,
and there is no authentication. See docs/adr/0004-local-first-no-auth.md.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import traceback
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .. import db, money, repo
from ..billing import BillingError
from . import finance, live, pages


@dataclass
class Redirect:
    location: str


class AppError(Exception):
    """A message meant for the owner, not a stack trace."""


# --------------------------------------------------------------- form helpers


def one(form: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form.get(key)
    return values[0].strip() if values and values[0] is not None else default


def money_field(form: dict, key: str, default: int | None = 0) -> int | None:
    """Read a baht form field as satang. Blank means 'use the default'."""
    raw = one(form, key)
    if raw == "":
        return default
    try:
        return money.baht(raw)
    except Exception as exc:
        raise AppError(f"จำนวนเงินไม่ถูกต้อง: {raw}") from exc


def int_field(form: dict, key: str, default: int | None = None) -> int | None:
    raw = one(form, key)
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise AppError(f"ตัวเลขไม่ถูกต้อง: {raw}") from exc


def float_field(form: dict, key: str) -> float | None:
    raw = one(form, key)
    if raw == "":
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise AppError(f"ค่ามิเตอร์ไม่ถูกต้อง: {raw}") from exc


def back(path: str, ok: str = "", err: str = "", **params) -> Redirect:
    """Build a redirect that carries a flash message in the query string."""
    parts = [f"{k}={quote(str(v))}" for k, v in params.items() if v not in (None, "")]
    if ok:
        parts.append(f"ok={quote(ok)}")
    if err:
        parts.append(f"err={quote(err)}")
    query = "&".join(parts)
    return Redirect(f"{path}?{query}" if query else path)


# -------------------------------------------------------------- GET handlers


def get_dashboard(conn, q, form):
    return pages.dashboard_page(conn, period=one(q, "period") or None, notice=one(q, "ok"))


def get_rooms(conn, q, form):
    return pages.rooms_page(conn, notice=one(q, "ok"), error=one(q, "err"))


def get_room(conn, q, form):
    return pages.room_page(conn, one(q, "code"), notice=one(q, "ok"), error=one(q, "err"))


def get_meters(conn, q, form):
    return pages.meters_page(conn, period=one(q, "period") or None,
                             notice=one(q, "ok"), error=one(q, "err"))


def get_invoices(conn, q, form):
    return pages.invoices_page(conn, period=one(q, "period") or None,
                               notice=one(q, "ok"), error=one(q, "err"),
                               items=q.get("item"))


def get_invoice(conn, q, form):
    invoice_id = int_field(q, "id")
    if invoice_id is None:
        raise AppError("ไม่ได้ระบุเลขที่ใบแจ้งหนี้")
    return pages.invoice_page(conn, invoice_id)


def get_expenses(conn, q, form):
    return finance.expenses_page(conn, period=one(q, "period") or None,
                                 notice=one(q, "ok"), error=one(q, "err"))


def get_reports(conn, q, form):
    return finance.reports_page(conn, year=int_field(q, "year"), notice=one(q, "ok"))


def get_settings(conn, q, form):
    return finance.settings_page(conn, notice=one(q, "ok"), error=one(q, "err"))


# -------------------------------------------------------------- POST handlers


def post_move_in(conn, q, form):
    code = one(form, "code")
    room = repo.room_by_code(conn, code)
    if room is None:
        raise AppError(f"ไม่พบห้อง {code}")
    name = one(form, "full_name")
    if not name:
        raise AppError("ต้องระบุชื่อผู้เช่า")
    tenant_id = repo.add_tenant(
        conn, name,
        phone=one(form, "phone"),
        line_id=one(form, "line_id"),
        national_id=one(form, "national_id"),
    )
    repo.start_lease(
        conn,
        room_id=room["id"],
        tenant_id=tenant_id,
        start_date=one(form, "start_date") or dt.date.today().isoformat(),
        monthly_rent=money_field(form, "monthly_rent", default=room["base_rent"]),
        deposit=money_field(form, "deposit", default=None),
    )
    return back("/room", ok=f"บันทึกผู้เช่าเข้าห้อง {code} เรียบร้อย", code=code)


def post_move_out(conn, q, form):
    lease_id = int_field(form, "lease_id")
    code = one(form, "code")
    repo.end_lease(
        conn,
        lease_id=lease_id,
        ended_on=one(form, "ended_on") or dt.date.today().isoformat(),
        deposit_refunded=money_field(form, "deposit_refunded", default=0),
    )
    return back("/room", ok=f"ปิดสัญญาเช่าห้อง {code} แล้ว", code=code)


def post_meters(conn, q, form):
    """Save the whole sheet at once; blank inputs are left alone."""
    period = one(form, "period")
    read_date = one(form, "read_date") or dt.date.today().isoformat()
    saved, failed = 0, []

    for lease in repo.active_leases(conn):
        room_id = lease["room_id"]
        water = float_field(form, f"water_{room_id}")
        electric = float_field(form, f"electric_{room_id}")
        if water is None and electric is None:
            continue
        if water is None or electric is None:
            failed.append(f"{lease['room_code']}: กรอกไม่ครบทั้งน้ำและไฟ")
            continue
        # Present only on a room's first-ever reading; None elsewhere so save_reading
        # falls back to last month's closing numbers.
        water_prev = float_field(form, f"water_prev_{room_id}")
        electric_prev = float_field(form, f"electric_prev_{room_id}")
        try:
            repo.save_reading(conn, room_id, period, water_curr=water,
                              electric_curr=electric, read_date=read_date,
                              water_prev=water_prev, electric_prev=electric_prev)
            saved += 1
        except BillingError as exc:
            failed.append(f"{lease['room_code']}: {exc}")

    if failed:
        return back("/meters", err=" · ".join(failed[:4]), period=period)
    return back("/meters", ok=f"บันทึกมิเตอร์ {saved} ห้องเรียบร้อย", period=period)


def post_generate_invoices(conn, q, form):
    period = one(form, "period")
    result = repo.generate_invoices(conn, period, issue_date=one(form, "issue_date") or None)
    created, skipped = result["created"], result["skipped"]
    if not created and skipped:
        return back("/invoices", err="ไม่ได้ออกบิลใหม่: " + " · ".join(skipped[:4]), period=period)
    message = f"ออกใบแจ้งหนี้ {len(created)} ใบ ({', '.join(created)})"
    if skipped:
        message += f" · ข้าม {len(skipped)} ห้อง"
    return back("/invoices", ok=message, period=period)


def post_late_fees(conn, q, form):
    period = one(form, "period")
    touched = repo.apply_late_fees(conn)
    if not touched:
        return back("/invoices", ok="ไม่มีใบที่ต้องคิดค่าปรับเพิ่ม", period=period)
    return back("/invoices", ok=f"เพิ่มค่าปรับล่าช้า {len(touched)} ใบ", period=period)


def post_payment(conn, q, form):
    invoice_id = int_field(form, "invoice_id")
    amount = money_field(form, "amount", default=0)
    repo.record_payment(
        conn,
        invoice_id=invoice_id,
        amount=amount,
        paid_on=one(form, "paid_on") or None,
        method=one(form, "method") or "transfer",
        reference=one(form, "reference"),
    )
    destination = one(form, "back")
    if destination:
        return Redirect(f"{destination}&ok={quote('บันทึกการชำระเรียบร้อย')}")
    return back("/invoices", ok=f"รับชำระ {money.fmt(amount)} เรียบร้อย", period=one(form, "period"))


def post_void_invoice(conn, q, form):
    invoice_id = int_field(form, "invoice_id")
    repo.void_invoice(conn, invoice_id, reason=one(form, "reason") or "ยกเลิกโดยผู้ดูแล")
    return back("/invoices", ok="ยกเลิกใบแจ้งหนี้แล้ว", period=one(form, "period"))


def post_expense(conn, q, form):
    amount = money_field(form, "amount", default=0)
    if not amount:
        raise AppError("ต้องระบุจำนวนเงิน")
    repo.record_expense(
        conn,
        spent_on=one(form, "spent_on") or dt.date.today().isoformat(),
        category=one(form, "category") or "other",
        description=one(form, "description"),
        amount=amount,
        room_id=int_field(form, "room_id", default=None),
        vendor=one(form, "vendor"),
    )
    return back("/expenses", ok="บันทึกรายจ่ายเรียบร้อย", period=one(form, "period"))


def post_settings(conn, q, form):
    for key, _label, kind in finance.SETTING_FIELDS:
        if key not in form:
            continue
        value = money_field(form, key) if kind == "money" else one(form, key)
        db.set_setting(conn, key, value)
    return back("/settings", ok="บันทึกการตั้งค่าเรียบร้อย")


def post_backup(conn, q, form):
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = db.PROJECT_DIR / "data" / "backups" / f"apartment-{stamp}.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    # sqlite3's own backup API is consistent even with WAL pages outstanding.
    with sqlite3.connect(target) as destination:
        conn.backup(destination)
    return back("/settings", ok=f"สำรองข้อมูลไปที่ {target.name} แล้ว")


ROUTES = {
    ("GET", "/"): get_dashboard,
    ("GET", "/rooms"): get_rooms,
    ("GET", "/room"): get_room,
    ("GET", "/meters"): get_meters,
    ("GET", "/invoices"): get_invoices,
    ("GET", "/invoice"): get_invoice,
    ("GET", "/expenses"): get_expenses,
    ("GET", "/reports"): get_reports,
    ("GET", "/settings"): get_settings,
    ("POST", "/room/move-in"): post_move_in,
    ("POST", "/room/move-out"): post_move_out,
    ("POST", "/meters"): post_meters,
    ("POST", "/invoices/generate"): post_generate_invoices,
    ("POST", "/invoices/late-fees"): post_late_fees,
    ("POST", "/payment"): post_payment,
    ("POST", "/invoice/void"): post_void_invoice,
    ("POST", "/expenses"): post_expense,
    ("POST", "/settings"): post_settings,
    ("POST", "/backup"): post_backup,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "ApartmentManager/1.0"
    db_path: Path | None = None

    def log_message(self, fmt, *args):  # quieter console
        # /api/version is polled every few seconds by every open page; logging it
        # would bury the messages the owner actually needs to see.
        if not str(args[0]).startswith(("GET /static", "GET /favicon", "GET /api/version")):
            super().log_message(fmt, *args)

    # -- dispatch -----------------------------------------------------------

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/export/excel":
            return self._export_excel(parse_qs(parsed.query))
        if parsed.path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if parsed.path == "/api/version":
            # Polled by every open page every few seconds, so it never touches
            # SQLite -- two stat() calls, no connection, no query.
            token = live.data_version(self.db_path)
            return self._send(200, token.encode("ascii"), "text/plain; charset=utf-8")
        self._dispatch("GET", parsed.path, parse_qs(parsed.query), {})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        self._dispatch("POST", parsed.path, parse_qs(parsed.query), parse_qs(raw, keep_blank_values=True))

    def _dispatch(self, method: str, path: str, query: dict, form: dict):
        handler = ROUTES.get((method, path))
        if handler is None:
            body = "<h1>404</h1><p><a href='/'>กลับหน้าแรก</a></p>"
            return self._send(404, body.encode("utf-8"), "text/html; charset=utf-8")

        conn = db.connect(self.db_path)
        try:
            result = handler(conn, query, form)
        except (AppError, BillingError) as exc:
            referer = self.headers.get("Referer") or "/"
            result = Redirect(_with_error(referer, str(exc)))
        except Exception:
            traceback.print_exc()
            return self._send(500, _error_page(traceback.format_exc()).encode("utf-8"), "text/html")
        finally:
            conn.close()

        if isinstance(result, Redirect):
            self.send_response(303)
            self.send_header("Location", result.location)
            self.end_headers()
            return
        self._send(200, result.encode("utf-8"), "text/html; charset=utf-8")

    def _export_excel(self, query: dict):
        from ..excel import export_year

        year = int(one(query, "year") or dt.date.today().year)
        conn = db.connect(self.db_path)
        try:
            payload = export_year(conn, year)
        finally:
            conn.close()
        self.send_response(200)
        self.send_header("Content-Type",
                         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="apartment-{year}.xlsx"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send(self, status: int, payload: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        # Every page is live financial data, and the CSS is inlined into it. A cached
        # copy is always both stale and wrong -- and indistinguishable from the app
        # not having been updated at all.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.end_headers()
        if payload:
            self.wfile.write(payload)


def _with_error(referer: str, message: str) -> str:
    parsed = urlparse(referer)
    base = parsed.path or "/"
    params = [p for p in (parsed.query or "").split("&") if p and not p.startswith(("ok=", "err="))]
    params.append(f"err={quote(message)}")
    return f"{base}?{'&'.join(params)}"


def _error_page(detail: str) -> str:
    from .layout import esc, page

    return page(
        "เกิดข้อผิดพลาด",
        f"<h1>เกิดข้อผิดพลาด</h1><p>ระบบทำงานผิดพลาด กรุณาแจ้งรายละเอียดนี้:</p>"
        f"<pre class='card' style='overflow:auto'>{esc(detail)}</pre>"
        f"<p><a href='/'>กลับหน้าแรก</a></p>",
    )


class _Server(ThreadingHTTPServer):
    """The HTTP server, with Python's port-reuse default turned off.

    `HTTPServer.allow_reuse_address` is True by default, and on Windows SO_REUSEADDR
    means something different than it does on Linux: a second process is allowed to
    bind a port that is *already actively listening*. The new instance then starts
    without any error while the original process keeps accepting the connections --
    so the browser silently keeps talking to whichever server booted first, running
    whatever code it loaded into memory back then.

    That produced exactly the symptom you would least suspect: edit the code,
    restart, see "พร้อมใช้งานแล้ว", and get the old page with no error anywhere.
    Refusing to reuse the address turns that into a loud, obvious failure.
    """

    allow_reuse_address = False
    daemon_threads = True


ADDRESS_IN_USE = (10048, 48, 98)  # WSAEADDRINUSE, EADDRINUSE (BSD), EADDRINUSE (Linux)


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: Path | None = None,
    open_browser: bool = False,
) -> None:
    Handler.db_path = db_path
    try:
        server = _Server((host, port), Handler)
    except OSError as exc:
        if exc.errno in ADDRESS_IN_USE or getattr(exc, "winerror", None) in ADDRESS_IN_USE:
            print(f"\n  ⚠  พอร์ต {port} ถูกใช้งานอยู่แล้ว — ระบบน่าจะเปิดค้างจากครั้งก่อน\n")
            print("  ถ้าเปิดหน้าเว็บแล้วเห็นข้อมูลหรือหน้าตาเก่า แปลว่ากำลังคุยกับตัวเก่าอยู่")
            print("  วิธีแก้: ปิดหน้าต่างสีดำของระบบที่ค้างไว้ทั้งหมด แล้วกด เปิดระบบ.bat ใหม่")
            print("          (ไฟล์ .bat จะปิดตัวเก่าให้อัตโนมัติอยู่แล้ว)\n")
            print(f"  หรือจะเปิดอีกพอร์ตหนึ่งก็ได้:  python -m apartment serve --port {port + 1}\n")
            raise SystemExit(1) from exc
        raise

    url = f"http://localhost:{port}"
    print("\n  ระบบจัดการหอพัก พร้อมใช้งานแล้ว")
    print(f"  เปิดเบราว์เซอร์ไปที่:  {url}")
    if host == "0.0.0.0":
        print(f"  จากมือถือในวง Wi-Fi เดียวกัน: http://<IP ของเครื่องนี้>:{port}")
    print(f"  ฐานข้อมูล: {db_path or db.DEFAULT_DB}")
    print("  กด Ctrl+C เพื่อปิดระบบ\n")

    if open_browser:
        import webbrowser

        # Safe to call now: the socket is bound, so the browser cannot beat us to it.
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  ปิดระบบแล้ว")
    finally:
        server.server_close()
