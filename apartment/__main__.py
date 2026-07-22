"""Command line entry point: `python -m apartment <command>`.

`serve` is what the owner uses daily; the rest exist so that anything the web UI can
do can also be scripted, and so a fresh machine can be set up without clicking.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

from . import db, money, net, repo, reports
from .billing import BillingError


def cmd_init(args) -> int:
    conn = db.connect(args.db)
    db.init_db(conn)
    created = db.seed_rooms(conn, floors=args.floors, per_floor=args.rooms_per_floor)
    total = len(repo.rooms(conn))
    print(f"เตรียมฐานข้อมูลที่ {args.db or db.DEFAULT_DB}")
    print(f"สร้างห้องใหม่ {created} ห้อง (ทั้งหมด {total} ห้อง)")
    conn.close()
    return 0


def cmd_serve(args) -> int:
    from .web.server import serve

    host = args.host
    if host == "tailscale":
        # Resolved before the database is touched: refusing to start is the whole
        # point, and it should not leave a half-initialised database behind.
        host = net.tailscale_ip()
        if host is None:
            print(net.NOT_READY)
            return 1

    conn = db.connect(args.db)
    db.init_db(conn)
    if not repo.rooms(conn):
        db.seed_rooms(conn)
        print("สร้างห้องเริ่มต้น 30 ห้องแล้ว")
    conn.close()
    serve(
        host=host,
        port=args.port,
        db_path=Path(args.db) if args.db else None,
        open_browser=args.open,
    )
    return 0


def cmd_invoice(args) -> int:
    conn = db.connect(args.db)
    result = repo.generate_invoices(conn, args.period, issue_date=args.issue_date)
    print(f"งวด {result['period']}: ออกบิล {len(result['created'])} ใบ")
    for code in result["created"]:
        print(f"  + {code}")
    for reason in result["skipped"]:
        print(f"  - {reason}")
    conn.close()
    return 0


def cmd_report(args) -> int:
    conn = db.connect(args.db)
    period = args.period or dt.date.today().isoformat()[:7]
    s = reports.monthly_summary(conn, period)
    print(f"\n  สรุปงวด {period}")
    print(f"  {'ออกใบแจ้งหนี้':<20} {money.fmt(s.invoiced):>16}")
    print(f"  {'เก็บเงินได้':<20} {money.fmt(s.collected):>16}  ({s.collection_rate:.0%})")
    print(f"  {'รายจ่าย':<20} {money.fmt(s.expenses):>16}")
    print(f"  {'กำไรสุทธิ':<20} {money.fmt(s.net):>16}")
    print(f"  {'ห้องมีผู้เช่า':<20} {s.rooms_occupied}/{s.rooms_total} ({s.occupancy_rate:.0%})")

    overdue = reports.arrears(conn, dt.date.today().isoformat())
    if overdue:
        print(f"\n  ค้างชำระ {len(overdue)} ใบ:")
        for row in overdue[:10]:
            print(f"    ห้อง {row.room_code:<5} {row.tenant_name:<22} "
                  f"{money.fmt(row.outstanding):>13}  เกิน {row.days_overdue} วัน")
    unread = reports.unread_meters(conn, period)
    if unread:
        print(f"\n  ยังไม่ได้จดมิเตอร์: {', '.join(unread)}")
    print()
    conn.close()
    return 0


def open_in_default_app(path: Path) -> None:
    """Hand the workbook to whatever the owner has associated with .xlsx."""
    try:
        os.startfile(path)  # Windows; the only platform this system ships on
    except AttributeError:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.run([opener, str(path)], check=False)
    except OSError as exc:
        print(f"เปิดไฟล์อัตโนมัติไม่ได้ ({exc}) — เปิดเองได้ที่ {path.resolve()}")


def cmd_export(args) -> int:
    from .excel import export_year

    conn = db.connect(args.db)
    payload = export_year(conn, args.year)
    conn.close()

    target = Path(args.out or f"apartment-{args.year}.xlsx")
    try:
        target.write_bytes(payload)
    except PermissionError:
        # Excel takes an exclusive lock, so the second export of the day fails
        # here rather than anywhere interesting. Say which file, and why.
        print(f"เขียนไฟล์ไม่ได้: {target.name} กำลังเปิดค้างอยู่ใน Excel")
        print("ปิดไฟล์นั้นใน Excel ก่อน แล้วสั่งใหม่อีกครั้ง")
        return 1

    print(f"บันทึกไฟล์ {target.resolve()} ({len(payload):,} bytes)")
    if args.open:
        open_in_default_app(target)
    return 0


def cmd_backup(args) -> int:
    import sqlite3

    conn = db.connect(args.db)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(args.out) if args.out else db.PROJECT_DIR / "data" / "backups" / f"apartment-{stamp}.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as destination:
        conn.backup(destination)
    conn.close()
    print(f"สำรองข้อมูลไปที่ {target.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m apartment",
        description="ระบบจัดการหอพักและบันทึกรายรับ",
    )
    parser.add_argument("--db", help="ตำแหน่งไฟล์ฐานข้อมูล (ค่าเริ่มต้น data/apartment.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="สร้างฐานข้อมูลและห้องพักเริ่มต้น")
    p.add_argument("--floors", type=int, default=db.FLOORS)
    p.add_argument("--rooms-per-floor", type=int, default=db.ROOMS_PER_FLOOR)
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("serve", help="เปิดหน้าเว็บสำหรับใช้งานประจำวัน")
    p.add_argument("--host", default="127.0.0.1",
                   help="0.0.0.0 = มือถือในวง Wi-Fi เดียวกัน · "
                        "tailscale = มือถือจากที่ไหนก็ได้ ผ่านเครือข่ายส่วนตัว")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true",
                   help="เปิดเบราว์เซอร์ให้อัตโนมัติเมื่อระบบพร้อม (ไฟล์ .bat ใช้ตัวเลือกนี้)")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("invoice", help="ออกใบแจ้งหนี้ทั้งงวด")
    p.add_argument("period", help="งวด เช่น 2026-07")
    p.add_argument("--issue-date")
    p.set_defaults(func=cmd_invoice)

    p = sub.add_parser("report", help="สรุปผลประกอบการรายเดือนบนหน้าจอ")
    p.add_argument("--period")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("export", help="ส่งออกข้อมูลทั้งปีเป็น Excel")
    p.add_argument("--year", type=int, default=dt.date.today().year)
    p.add_argument("--out")
    p.add_argument("--open", action="store_true",
                   help="เปิดไฟล์ใน Excel ให้เลยเมื่อสร้างเสร็จ (ไฟล์ .bat /excel ใช้ตัวเลือกนี้)")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("backup", help="สำรองฐานข้อมูล")
    p.add_argument("--out")
    p.set_defaults(func=cmd_backup)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except BillingError as exc:
        print(f"ผิดพลาด: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
