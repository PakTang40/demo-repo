"""HTML shell and the handful of components every page reuses.

No template engine: pages are Python functions returning strings. At this size that
is less machinery than a template language, and `esc()` on every interpolation is
the whole safety story.

The visual language is set out in docs/adr/0005-visual-language.md. In short: warm
ivory and ink instead of grey-on-white, antique brass as the only accent, a serif
for headings and headline figures, hairlines instead of borders, and generous space.
Nothing here loads an external font or asset -- the app must work with no network.
"""

from __future__ import annotations

import html as _html

from .. import money

# Type stacks resolve per-glyph: Latin lands on the serif, Thai falls through to
# Leelawadee UI (present on every Windows 11 install). Numerals are forced to lining
# tabular figures wherever they sit in a column, because Constantia and Georgia
# default to old-style figures that jump above and below the baseline in a table.
CSS = """
:root {
  --serif: Constantia, Georgia, "Palatino Linotype", "Leelawadee UI", "Sarabun", serif;
  --sans: "Leelawadee UI", "Segoe UI", "Sarabun", system-ui, -apple-system, sans-serif;

  --bg: #f7f4ee;          /* warm bone, not white */
  --surface: #fffdf8;
  --surface-alt: #f3efe6;
  --ink: #24201a;         /* soft black: pure #000 on ivory glares */
  --ink-soft: #4a443a;
  --muted: #6f6759;       /* darkened from #8a8175 -- 4.6:1, readable when tired */
  --line: #e6dfd2;        /* hairline */
  --line-strong: #d3c9b6;
  --accent: #8a6a35;      /* antique brass */
  --accent-bright: #a8823f;
  --accent-soft: #f2ebdc;
  --ok: #3d6b52;
  --ok-soft: #e8efe9;
  --warn: #8a6520;
  --warn-soft: #f6eeda;
  --danger: #8c3838;      /* deep burgundy, never fire-engine red */
  --danger-soft: #f6e9e7;
  --zebra: #fbf9f4;
  --shadow: 0 1px 2px rgba(30,27,22,.04), 0 8px 24px -12px rgba(30,27,22,.10);

  /* Rounded corners throughout: at a glance, softer edges read as calmer. */
  --r-sm: 6px;
  --r: 10px;
  --r-lg: 14px;

  /* Floor-plan fills. Deliberately separate tokens from --danger/--ok: on the room
     board red means EMPTY (no income), not "error", and the two must be free to
     diverge. See docs/adr/0005. */
  --plan-vacant: linear-gradient(158deg, #9c3331 0%, #7a1f1e 100%);
  --plan-vacant-edge: #661b1a;
  --plan-vacant-ink: #fdf1ee;
  --plan-live: linear-gradient(158deg, #2f7350 0%, #1e5638 100%);
  --plan-live-edge: #1a4a30;
  --plan-live-ink: #f0fbf4;
  --plan-alert: #e8b53f;          /* arrears: amber cuts through both fills */
  --plan-alert-ink: #2a1e04;
  --plan-maint: linear-gradient(158deg, #6e6759 0%, #514b40 100%);
  --plan-maint-edge: #453f36;
  --plan-maint-ink: #f5f1e8;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14120e;
    --surface: #1c1915;
    --surface-alt: #24201a;
    --ink: #ece6da;
    --ink-soft: #c4bcae;
    --muted: #8d8477;
    --line: #302b23;
    --line-strong: #443d32;
    --accent: #c9a86a;
    --accent-bright: #dcbd82;
    --accent-soft: #2a2318;
    --ok: #7fb894;
    --ok-soft: #1d2a22;
    --warn: #d4a960;
    --warn-soft: #2c2415;
    --danger: #d98a84;
    --danger-soft: #2e1d1c;
    --zebra: #1f1c17;
    --shadow: 0 1px 2px rgba(0,0,0,.3), 0 8px 24px -12px rgba(0,0,0,.5);

    /* Same hues, dimmed: a saturated fill that is right in daylight glows at night. */
    --plan-vacant: linear-gradient(158deg, #8a2e2c 0%, #641d1c 100%);
    --plan-vacant-edge: #a3453f;
    --plan-vacant-ink: #fbe9e5;
    --plan-live: linear-gradient(158deg, #2a6a49 0%, #194e33 100%);
    --plan-live-edge: #3d8a62;
    --plan-live-ink: #e6f7ec;
    --plan-alert: #d9a838;
    --plan-alert-ink: #241a03;
    --plan-maint: linear-gradient(158deg, #55503f 0%, #3d382f 100%);
    --plan-maint-edge: #6d6555;
    --plan-maint-ink: #ece7dc;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--ink); font-family: var(--sans);
  font-size: 16px; line-height: 1.72; letter-spacing: 0;
  -webkit-font-smoothing: antialiased;
}
/* Thai has no spaces between words and no capitals: wide tracking pulls the
   clusters apart and makes a line genuinely harder to read, while uppercasing
   does nothing at all. Small-caps labels therefore stay small-caps in *shape*
   only -- the tracking is kept to a whisper everywhere Thai can appear. */
a { color: var(--accent); text-underline-offset: 3px; }
a:hover { color: var(--accent-bright); }

/* ---------- masthead ---------- */
header.top {
  background: var(--surface); border-bottom: 1px solid var(--line);
  padding: 0 2rem; position: sticky; top: 0; z-index: 10;
  box-shadow: 0 1px 0 rgba(0,0,0,.02);
}
header.top::before {
  content: ""; display: block; height: 2px; margin: 0 -2rem;
  background: linear-gradient(90deg, var(--accent) 0%, var(--accent-bright) 42%, transparent 92%);
}
header.top .inner {
  max-width: 1240px; margin: 0 auto; display: flex; gap: 2.2rem;
  align-items: center; flex-wrap: wrap; padding: .9rem 0;
}
header.top .brand {
  font-family: var(--serif); font-size: 1.22rem; font-weight: 600;
  letter-spacing: .01em; margin-right: .4rem; white-space: nowrap;
}
header.top nav { display: flex; gap: .3rem; flex-wrap: wrap; }
header.top nav a {
  text-decoration: none; color: var(--ink-soft); font-size: .93rem;
  letter-spacing: .01em; padding: .4rem .8rem; border-radius: var(--r-sm);
  transition: color .15s, background .15s;
}
header.top nav a:hover { color: var(--ink); background: var(--surface-alt); }
header.top nav a.active {
  color: var(--accent); background: var(--accent-soft); font-weight: 600;
}

main { max-width: 1240px; margin: 0 auto; padding: 2.6rem 2rem 5rem; }

/* ---------- headings ---------- */
h1 {
  font-family: var(--serif); font-size: 2.05rem; font-weight: 600;
  letter-spacing: -.012em; line-height: 1.28; margin: 0 0 .4rem;
}
h2 {
  font-family: var(--serif); font-size: 1.3rem; font-weight: 600;
  letter-spacing: -.005em; margin: 2.8rem 0 1rem;
  padding-bottom: .55rem; border-bottom: 1px solid var(--line);
}
.eyebrow {
  font-size: .8rem; letter-spacing: .05em; color: var(--accent);
  margin: 0 0 .5rem; font-weight: 600;
}
.sub { color: var(--muted); margin: 0 0 1.9rem; font-size: .97rem; max-width: 68ch; }

/* ---------- surfaces ---------- */
.card {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--r);
  padding: 1.5rem 1.65rem; margin-bottom: 1.2rem; box-shadow: var(--shadow);
}
.grid { display: grid; gap: 1rem; }
.tiles { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
.tile {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--r);
  padding: 1.25rem 1.35rem 1.3rem; box-shadow: var(--shadow); position: relative;
  overflow: hidden;
}
.tile::before {
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  background: var(--line-strong);
}
.tile .label {
  color: var(--muted); font-size: .84rem; letter-spacing: .01em; line-height: 1.45;
}
.tile .value {
  font-family: var(--serif); font-size: 1.8rem; font-weight: 600;
  letter-spacing: -.015em; line-height: 1.3; margin-top: .3rem;
  font-variant-numeric: lining-nums tabular-nums;
}
.tile .hint { color: var(--muted); font-size: .82rem; margin-top: .3rem; line-height: 1.5; }
.tile:has(.value.pos)::before { background: var(--ok); }
.tile:has(.value.neg)::before { background: var(--danger); }
.value.pos { color: var(--ok); } .value.neg { color: var(--danger); }

/* ---------- tables ---------- */
.tablewrap {
  overflow-x: auto; border: 1px solid var(--line); border-radius: var(--r);
  margin-bottom: 1.2rem; background: var(--surface); box-shadow: var(--shadow);
}
table { width: 100%; border-collapse: collapse; background: transparent; }
th, td {
  padding: .85rem 1.05rem; text-align: left;
  border-bottom: 1px solid var(--line); white-space: nowrap;
}
th {
  background: var(--surface-alt); font-size: .82rem; color: var(--muted);
  font-weight: 600; letter-spacing: .01em;
  border-bottom: 1px solid var(--line-strong);
}
tbody tr { transition: background .12s; }
tbody tr:nth-child(even) { background: var(--zebra); }
tbody tr:hover { background: var(--surface-alt); }
tbody tr:last-child td { border-bottom: none; }
tbody td.empty {
  text-align: center; color: var(--muted); padding: 2.4rem 1rem;
  font-style: italic; white-space: normal;
}
tfoot td {
  font-weight: 600; background: var(--surface-alt);
  border-top: 1px solid var(--line-strong); border-bottom: none;
}
td.num, th.num { text-align: right; font-variant-numeric: lining-nums tabular-nums; }
td.num { font-feature-settings: "tnum"; }

/* ---------- floor plan ----------
   The whole plate is filled with its colour, so the board can be read from across
   the room: RED = empty, GREEN = someone lives there. That is the landlord's first
   question and it now answers itself without reading a word.

   Red here means "no income", not "error" -- the opposite of its meaning in a
   report. That reversal is only safe because every plate still spells its status
   out in words: colour alone is not a status. It fails in sunlight, on a cheap
   monitor, and for the ~8% of men with colour-vision deficiency.

   Arrears ride on top as an amber band, because an occupied room that owes money
   is still occupied -- and amber is the one signal neither fill can swallow. */
.floor-head {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 1rem 1.6rem; flex-wrap: wrap;
  margin: 2.8rem 0 1.1rem; padding-bottom: .6rem; border-bottom: 1px solid var(--line);
}
.floor-head .title {
  font-family: var(--serif); font-size: 1.38rem; font-weight: 600; letter-spacing: -.005em;
}
.floor-head .stats { display: flex; gap: 1.6rem; flex-wrap: wrap; font-size: .88rem; color: var(--muted); }
.floor-head .stats b {
  color: var(--ink); font-weight: 600; font-variant-numeric: lining-nums tabular-nums;
}

.legend {
  display: flex; gap: 1.5rem; flex-wrap: wrap; align-items: center;
  font-size: .88rem; color: var(--ink-soft); padding: .95rem 1.25rem;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--r);
  box-shadow: var(--shadow);
}
.legend .item { display: flex; gap: .55rem; align-items: center; }
.legend .item b { font-variant-numeric: lining-nums tabular-nums; }
.legend .sw {
  width: 18px; height: 18px; border-radius: var(--r-sm); border: 1px solid; flex: none;
}
.legend .sw.vacant { background: var(--plan-vacant); border-color: var(--plan-vacant-edge); }
.legend .sw.paid,
.legend .sw.occupied { background: var(--plan-live); border-color: var(--plan-live-edge); }
.legend .sw.owing { background: var(--plan-alert); border-color: var(--plan-alert); }
.legend .sw.maintenance { background: var(--plan-maint); border-color: var(--plan-maint-edge); }

.rooms { display: grid; grid-template-columns: repeat(auto-fill, minmax(172px, 1fr)); gap: .9rem; }
.room {
  --plate: var(--surface);
  --plate-ink: var(--ink);
  --plate-edge: var(--line-strong);
  display: flex; flex-direction: column; text-decoration: none; min-height: 152px;
  background: var(--plate); color: var(--plate-ink);
  border: 1px solid var(--plate-edge); border-radius: var(--r); overflow: hidden;
  box-shadow: var(--shadow);
  transition: box-shadow .16s, transform .16s;
}
.room:hover {
  transform: translateY(-3px);
  box-shadow: 0 3px 6px rgba(30,27,22,.10), 0 16px 32px -14px rgba(30,27,22,.35);
}
.room-body { padding: .95rem 1rem .85rem; flex: 1; }
.room .code {
  font-family: var(--serif); font-weight: 600; font-size: 1.85rem;
  letter-spacing: .005em; line-height: 1.05; font-variant-numeric: lining-nums;
}
.room .who {
  font-size: .88rem; line-height: 1.5; margin-top: .3rem; opacity: .95;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.room .rent {
  font-size: .8rem; margin-top: .2rem; opacity: .78;
  font-variant-numeric: lining-nums tabular-nums;
}
.room .over { font-size: .8rem; font-weight: 700; margin-top: .3rem; opacity: .95; }

/* The status band: translucent white over the fill, so it belongs to the plate
   instead of sitting on it. Arrears override it with solid amber. */
.room-status {
  font-size: .84rem; font-weight: 700; letter-spacing: .01em;
  padding: .5rem .6rem; text-align: center;
  background: rgba(255,255,255,.17); border-top: 1px solid rgba(255,255,255,.28);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.room-status .amt { font-variant-numeric: lining-nums tabular-nums; }

.room.vacant {
  --plate: var(--plan-vacant); --plate-ink: var(--plan-vacant-ink);
  --plate-edge: var(--plan-vacant-edge);
}
.room.paid, .room.occupied, .room.owing {
  --plate: var(--plan-live); --plate-ink: var(--plan-live-ink);
  --plate-edge: var(--plan-live-edge);
}
.room.maintenance {
  --plate: var(--plan-maint); --plate-ink: var(--plan-maint-ink);
  --plate-edge: var(--plan-maint-edge);
}
.room.owing {
  border-color: var(--plan-alert);
  box-shadow: 0 0 0 2px var(--plan-alert), var(--shadow);
}
.room.owing:hover { box-shadow: 0 0 0 2px var(--plan-alert),
                                0 16px 32px -14px rgba(30,27,22,.35); }
.room.owing .room-status {
  background: var(--plan-alert); color: var(--plan-alert-ink);
  border-top-color: var(--plan-alert);
}

/* ---------- pills ---------- */
.pill {
  display: inline-block; padding: .2rem .7rem; border-radius: 999px;
  font-size: .8rem; font-weight: 600; letter-spacing: .01em;
  border: 1px solid currentColor; line-height: 1.55;
}
.pill.ok { color: var(--ok); background: var(--ok-soft); }
.pill.warn { color: var(--warn); background: var(--warn-soft); }
.pill.danger { color: var(--danger); background: var(--danger-soft); }
.pill.muted { color: var(--muted); background: transparent; border-color: var(--line-strong); }

/* ---------- forms ---------- */
form.inline { display: flex; gap: .8rem; align-items: flex-end; flex-wrap: wrap; }
label {
  display: block; font-size: .85rem; color: var(--muted); margin-bottom: .35rem;
  letter-spacing: .01em;
}
input, select, textarea {
  font: inherit; font-size: .97rem; padding: .58rem .75rem;
  border: 1px solid var(--line-strong); border-radius: var(--r-sm);
  background: var(--surface); color: var(--ink); transition: border-color .15s, box-shadow .15s;
}
input:hover, select:hover { border-color: var(--muted); }
input:focus, select:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
input[type=number] { text-align: right; font-variant-numeric: lining-nums tabular-nums; }
input::placeholder { color: var(--muted); opacity: .7; font-size: .9rem; }
button {
  font: inherit; font-size: .92rem; font-weight: 600; letter-spacing: .01em;
  padding: .6rem 1.3rem; border-radius: var(--r-sm);
  border: 1px solid var(--accent); background: var(--accent); color: #fffdf8;
  cursor: pointer; transition: background .15s, color .15s, box-shadow .15s;
}
button:hover { background: var(--accent-bright); border-color: var(--accent-bright);
               box-shadow: var(--shadow); }
button.secondary { background: transparent; color: var(--accent); }
button.secondary:hover { background: var(--accent-soft); color: var(--accent); }
button.danger { background: var(--danger); border-color: var(--danger); color: #fffdf8; }
button.danger:hover { background: var(--danger); filter: brightness(1.12); }

/* ---------- notices ---------- */
.flash {
  padding: .95rem 1.25rem; border-radius: var(--r); margin-bottom: 1.25rem;
  border: 1px solid; border-left-width: 4px; font-size: .97rem;
}
.flash.ok { background: var(--ok-soft); border-color: var(--ok); color: var(--ok); }
.flash.err { background: var(--danger-soft); border-color: var(--danger); color: var(--danger); }
.flash ul { margin: .45rem 0 0; padding-left: 1.25rem; }
.flash li { margin-top: .15rem; }

/* ---------- misc ---------- */
.muted { color: var(--muted); }
.right { text-align: right; }
.row { display: flex; gap: 1.4rem; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; }
.stack > * + * { margin-top: .7rem; }
.bar { height: 3px; background: var(--surface-alt); border-radius: 2px; overflow: hidden; }
.bar > span { display: block; height: 100%; background: var(--accent); }
.rule { border: none; border-top: 1px solid var(--line); margin: 1.1rem 0; }
.figure {
  font-family: var(--serif); font-size: 1.55rem; font-weight: 600;
  letter-spacing: -.012em; font-variant-numeric: lining-nums tabular-nums;
}
footer.foot {
  max-width: 1240px; margin: 0 auto; padding: 2rem 2rem 3rem;
  border-top: 1px solid var(--line); color: var(--muted); font-size: .85rem;
  letter-spacing: .01em; display: flex; justify-content: space-between; flex-wrap: wrap; gap: .5rem;
}

/* ---------- keyboard users get a visible, brass focus ring everywhere ---------- */
a:focus-visible, button:focus-visible, input:focus-visible,
select:focus-visible, .room:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--r-sm);
}

/* ---------- phone / tablet (the owner uses this on the walk-around) ---------- */
@media (max-width: 860px) {
  header.top { padding: 0 1.1rem; }
  header.top::before { margin: 0 -1.1rem; }
  header.top .inner { gap: .6rem; padding: .75rem 0; }
  header.top nav { gap: .2rem; }
  header.top nav a { font-size: .88rem; padding: .35rem .6rem; }
  main { padding: 1.6rem 1.1rem 4rem; }
  h1 { font-size: 1.7rem; }
  h2 { margin-top: 2.1rem; }
  .card { padding: 1.2rem 1.25rem; }
  .tiles { grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: .75rem; }
  .tile .value { font-size: 1.5rem; }
  .rooms { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: .7rem; }
  .row { gap: 1rem; }
  footer.foot { padding: 1.5rem 1.1rem 2.5rem; }
  /* Meter entry happens one-handed on a phone: fingers need a real target. */
  input, select { padding: .65rem .75rem; font-size: 16px; }  /* 16px stops iOS zooming */
  button { padding: .68rem 1.25rem; }
}
@media (max-width: 520px) {
  .rooms { grid-template-columns: repeat(auto-fill, minmax(138px, 1fr)); }
  .room { min-height: 138px; }
  .room .code { font-size: 1.65rem; }
  form.inline { gap: .6rem; }
  form.inline > div { flex: 1 1 46%; }
  form.inline input, form.inline select { width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; }
  .room:hover { transform: none; }
}

/* ---------- print: the invoice is the one thing a tenant holds ---------- */
@media print {
  header.top, .noprint, footer.foot { display: none !important; }
  body { background: #fff; color: #000; font-size: 11.5pt; }
  main { max-width: none; padding: 0; }
  .card, .tablewrap, .tile {
    border: none; box-shadow: none; padding-left: 0; padding-right: 0;
  }
  .tile::before { display: none; }
  th { background: #fff; border-bottom: 1px solid #000; }
  td, th { padding: .4rem .5rem; }
  tbody tr:nth-child(even) { background: #fff; }
  .legend { border: none; padding: 0; box-shadow: none; }
  /* Solid fills eat a colour cartridge and print muddy on a mono laser. The words
     carry the status anyway, so the plates print as plain outlined cards. */
  .room {
    break-inside: avoid; box-shadow: none !important;
    background: #fff !important; color: #000 !important; border: 1px solid #000 !important;
  }
  .room-status {
    background: #fff !important; color: #000 !important;
    border-top: 1px solid #000 !important;
  }
  .legend .sw { border: 1px solid #000 !important; background: #fff !important; }
  .floor-head { break-after: avoid; }
  h1 { font-size: 17pt; }
  h2 { font-size: 12pt; margin-top: 1.2rem; }
  a { color: #000; text-decoration: none; }
  .pill { border-color: #000; color: #000; background: transparent; }
}
"""

NAV = [
    ("/", "ภาพรวม"),
    ("/rooms", "ห้องพัก"),
    ("/meters", "จดมิเตอร์"),
    ("/invoices", "ใบแจ้งหนี้"),
    ("/expenses", "รายจ่าย"),
    ("/reports", "รายงานการเงิน"),
    ("/settings", "ตั้งค่า"),
]


def esc(value) -> str:
    """Escape anything for HTML text or an attribute value."""
    return _html.escape(str(value if value is not None else ""), quote=True)


def page(title: str, body: str, active: str = "/", building: str = "หอพัก") -> str:
    links = []
    for href, label in NAV:
        cls = ' class="active"' if href == active else ""
        links.append(f'<a href="{esc(href)}"{cls}>{esc(label)}</a>')
    nav = "".join(links)
    return f"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · {esc(building)}</title>
<style>{CSS}</style>
</head>
<body>
<header class="top">
  <div class="inner">
    <span class="brand">{esc(building)}</span>
    <nav>{nav}</nav>
  </div>
</header>
<main>{body}</main>
<footer class="foot">
  <span>{esc(building)}</span>
  <span>ระบบจัดการหอพัก · ข้อมูลเก็บในเครื่องนี้เท่านั้น</span>
</footer>
</body>
</html>"""


def tile(label: str, value: str, hint: str = "", tone: str = "") -> str:
    tone_class = f" {tone}" if tone else ""
    hint_html = f'<div class="hint">{esc(hint)}</div>' if hint else ""
    return (
        f'<div class="tile"><div class="label">{esc(label)}</div>'
        f'<div class="value{tone_class}">{esc(value)}</div>{hint_html}</div>'
    )


def flash(message: str | None, kind: str = "ok", items: list[str] | None = None) -> str:
    if not message and not items:
        return ""
    body = esc(message or "")
    if items:
        body += "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"
    return f'<div class="flash {esc(kind)}">{body}</div>'


def eyebrow(text: str) -> str:
    """A small-caps kicker above a heading."""
    return f'<p class="eyebrow">{esc(text)}</p>'


def baht_cell(satang: int, tone: bool = False) -> str:
    """A right-aligned money cell, optionally red when negative."""
    style = ' style="color:var(--danger)"' if tone and satang < 0 else ""
    return f'<td class="num"{style}>{esc(money.fmt(satang, symbol=False))}</td>'


def status_pill(status: str) -> str:
    mapping = {
        "paid": ("ok", "ชำระแล้ว"),
        "partial": ("warn", "ชำระบางส่วน"),
        "unpaid": ("danger", "ค้างชำระ"),
        "occupied": ("ok", "มีผู้เช่า"),
        "vacant": ("muted", "ว่าง"),
        "maintenance": ("warn", "ปิดซ่อม"),
    }
    tone, label = mapping.get(status, ("muted", status))
    return f'<span class="pill {tone}">{esc(label)}</span>'


def period_picker(action: str, period: str, extra: str = "") -> str:
    return f"""<form class="inline noprint" method="get" action="{esc(action)}"
                     style="margin-bottom:1.6rem">
      <div><label>เลือกงวด</label><input type="month" name="period" value="{esc(period)}"></div>
      {extra}
      <button class="secondary" type="submit">แสดง</button>
    </form>"""
