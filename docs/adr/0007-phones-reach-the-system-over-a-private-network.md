# ADR-0007: Phones reach the system over a private network, not the internet

Status: accepted · 2026-07-22 · amends [ADR-0004](0004-local-first-no-authentication.md)

## Context

The owner needs the room board and the arrears figures from a phone, away from the
building, and needs them to be current rather than whatever was true when the page
was opened.

ADR-0004 met "no authentication" by being unreachable, and named the exact price of
that: *"Any requirement to reach the system from outside the LAN invalidates both:
the correct response is a rewrite onto a real framework with real auth."*

That conclusion assumed the only way out of the LAN is the public internet. It is
not. The requirement is not *"be on the internet"* — it is *"be reachable by four
specific phones."*

The two are very different problems. Publishing to the internet means anything that
can send a packet can reach the login form, so the login form becomes the only thing
between a stranger and 30 tenants' national ID numbers. Being reachable by four
named devices means the network refuses everyone else before any request is parsed.

`http.server` with no authentication is only unsafe on a network that carries
strangers. ADR-0004's real principle was never "no auth is fine" — it was **"do not
be reachable."** A private overlay network keeps that principle while changing the
boundary from *this Wi-Fi* to *these devices*.

## Decision

Reach the system over **Tailscale**, a WireGuard mesh joining only devices signed in
to the owner's account. `เปิดระบบ.bat /phone` binds the server to the machine's
tailnet address (`100.64.0.0/10`) **and to nothing else**.

Binding one interface rather than `0.0.0.0` is the substance of this decision, not a
detail. `/lan` binds every interface the PC is attached to, which is sound on the
building's own Wi-Fi and indefensible on a cafe's: no password exists, so every
stranger on that network is one guessed IP address from the tenant register. Under
`/phone` there is no socket listening on the cafe's interface at all.

Authentication therefore still lives in the network layer, where ADR-0004 put it:

- Not signed in to the owner's tailnet → the packets never arrive.
- Signed in → full access, exactly as sitting at the PC gives full access.

Pages poll a token derived from the database file's mtime and size and reload when
it moves, so a phone shows current figures without holding a server thread open.

## Consequences

- **The rewrite ADR-0004 demanded is not triggered**, because its trigger — being
  reachable from the public internet — does not occur. If the system is ever put
  behind a public URL, ADR-0004 applies again in full and this ADR does not
  authorise it.
- Every device needs the Tailscale app and a sign-in. A phone that is not set up
  cannot be helped by a password, which is the intended trade.
- Tenant data still never transits a third party. Tailscale's coordination server
  brokers the connection and distributes public keys; it cannot read the traffic,
  which is WireGuard-encrypted end to end. This keeps the PDPA posture of ADR-0004
  substantially intact.
- A lost phone that is still signed in is full access. Revoke it from the Tailscale
  admin console — this is now part of losing a phone, and it is the one operational
  duty this ADR adds.
- `/lan` is kept for the building's own Wi-Fi, now with an on-screen warning that it
  admits every device on the network.
