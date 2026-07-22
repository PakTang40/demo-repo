# ADR-0005: A restrained, editorial visual language

Status: accepted · 2026-07-22

## Context

An apartment invoice is the one artefact of this business a tenant physically holds.
It is also the document they judge the operation by. The first cut of the UI was
functional but generic — default system greys, filled status blobs, heavy borders —
which reads as an internal admin tool rather than as a well-run building.

The owner asked for something that feels more considered. The constraint from
ADR-0001 still holds absolutely: **no external fonts, stylesheets, or assets.** The
app must render identically with the network unplugged.

## Decision

One `CSS` string in `web/layout.py`, built on system resources only.

- **Colour.** A warm bone/ivory ground (`#f7f4ee`) with brown-black ink, rather than
  grey on white. **Antique brass** (`#8a6a35`, `#c9a86a` in dark) is the *only*
  accent. Semantic colours are muted to their deep forms — burgundy for money owed,
  forest for money received — never saturated red or green.
- **Type.** A serif stack (Constantia → Georgia → Palatino) for headings, room
  numbers, and headline figures; the sans stack for body and table data. Because
  font fallback resolves per glyph, Thai text lands on Leelawadee UI automatically
  while Latin and numerals take the serif. Numerals in any column are forced to
  `lining-nums tabular-nums` — Constantia and Georgia default to old-style figures,
  which bounce above and below the baseline and make a money column unreadable.
- ~~**Labels** are uppercase, ~0.7rem, letter-spaced `.11–.16em`.~~ **Reversed
  2026-07-22 — see the second amendment below.** Labels are now ~0.85rem at normal
  tracking.
- **Lines, not boxes.** Hairline rules (`--line`), soft radii (`--r-sm`/`--r`/`--r-lg`
  = 6/10/14px), and a very soft large-offset shadow.
- **Space is the main lever.** Generous padding, `line-height: 1.72`, wide margins
  above section headings. Density is the thing that makes an interface feel cheap.
- **Status is always words plus colour, never colour alone.** Pills are outlined
  chips in small caps. Room plates carry a full-width status strip that *spells out*
  ชำระแล้ว / ค้างชำระ / ว่าง / รอออกบิล / ปิดซ่อม, with the amount owed printed on it.

  > **Amended 2026-07-22.** The first version of the floor plan used a small coloured
  > dot in the corner of each plate. It looked more refined and was materially harder
  > to read — the owner said so immediately. A colour-only status fails in sunlight,
  > on a cheap monitor, for the ~8% of men with colour-vision deficiency, and for
  > anyone scanning 30 plates in a few seconds. **Refinement is never worth a loss of
  > legibility on an operational screen.** When the two conflict, legibility wins and
  > the decoration has to find another job.

  > **Amended again 2026-07-22.** The owner asked for the floor plan to be blunt:
  > *"ถ้าว่างสีแดงเข้มทั้งช่อง และห้องไม่ว่างเป็นสีเขียวทั้งช่อง."* The status strip
  > became the whole plate. The fill now answers **occupancy** — deep red for empty,
  > green for let — because that is the landlord's first question and an empty room
  > is the thing that actually costs money. The words stay on every plate, so the
  > amendment above is not weakened: this is words *plus* a much louder colour.
  >
  > **This inverts the meaning of red on one screen.** In every report red is money
  > lost or owed; on the floor plan it is a room earning nothing. Because the two
  > readings are both "bad", the reversal is survivable — but it is the reason the
  > fills use their own tokens (`--plan-vacant`, `--plan-live`, `--plan-alert`,
  > `--plan-maint`) rather than `--danger`/`--ok`. Wiring the plates to the semantic
  > tokens would silently drag every report's palette along with the next change.
  >
  > **Arrears then needed a third signal**, since an occupied debtor is still green.
  > Amber (`--plan-alert`) takes over the status band and rings the plate: it is the
  > one hue neither fill can swallow, and it survives both palettes.

- **Comfort over editorial polish in the chrome.** Uppercase micro-labels at
  `.11–.16em` tracking were the signature of the first cut. They are wrong for this
  app: Thai has no capitals, so `text-transform: uppercase` does nothing to most of
  the interface, while wide tracking pulls apart clusters in a script written without
  spaces between words — actively harder to read. Body type is 16px/1.72, labels sit
  at ~0.85rem with normal tracking, `--muted` was darkened to 4.6:1 contrast, and the
  nav is real tappable pills. The editorial feel now comes from the serif, the ivory
  ground, and the space — none of which cost legibility.

Print styles are treated as a first-class target, not an afterthought: chrome and
shadows drop away, the invoice sets in black on white with a rule under the table
head. The coloured plates deliberately print as **plain outlined cards** — a solid
fill prints muddy on a mono laser and drains a colour cartridge, and the words on
each plate already carry the status.

## Consequences

- The whole visual system lives in one string in one file. Changing the accent is a
  one-line edit to `--accent`; there is no theme layer to keep in sync.
- Dark mode is a full second palette under `prefers-color-scheme`, not an inversion.
- **Cost:** the serif stack is Windows-specific. On a Mac or Linux machine the Latin
  headings fall back through Georgia to the generic serif, which is close enough;
  Thai is unaffected either way. Acceptable — this runs on the owner's PC (ADR-0004).
- **Cost:** `.tile:has(...)` is used for accent bars. Supported in every current
  browser; if it fails the bar simply stays neutral, which is a clean degradation.
- Page markup must keep using the shared components (`page`, `tile`, `flash`,
  `baht_cell`, `status_pill`, `eyebrow`) rather than growing inline styles, or this
  decision decays one page at a time.
- The two floor-plan fills are pinned by
  `tests/test_web.py::test_vacant_and_occupied_plates_carry_the_two_agreed_fills`
  and the amber override by `test_arrears_stay_visible_on_a_green_plate`. They are a
  business decision the owner made explicitly, not a design preference, so a future
  restyle has to change them on purpose rather than by drift.
