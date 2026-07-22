# ADR-0004: Local-first, single operator, no authentication

Status: accepted · 2026-07-22 · amended by
[ADR-0007](0007-phones-reach-the-system-over-a-private-network.md), which extends
the reachability boundary from the LAN to a private Tailscale network. The decision
below stands; ADR-0007 argues that a tailnet is a narrowing of it, not an exception.

## Context

The system has exactly one user: the building's owner. It holds tenant names, phone
numbers, national ID numbers, and the building's full financial history — data that
would matter a great deal if exposed, and that carries obligations under Thailand's
PDPA.

Adding real authentication (accounts, password hashing, sessions, CSRF tokens, TLS)
is a substantial amount of security-critical code. Getting it *almost* right is worse
than not having it, because it invites exposure while providing little protection.

## Decision

Do not build authentication. Instead, do not be reachable:

- The server binds **`127.0.0.1`** by default — only this PC can connect.
- `--host 0.0.0.0` (or `เปิดระบบ.bat /lan`) opens it to the local network, and is
  documented as *for a phone on your own Wi-Fi*, behind the router's NAT.
- The system is **never** to be port-forwarded or placed on a public address.

## Consequences

- No passwords to manage, no session bugs, no CSRF surface worth attacking from
  outside the LAN.
- Physical access to the unlocked PC is full access. That matches the trust model: it
  is the owner's own machine and their own business.
- Tenant personal data never leaves the building's own hardware, which is the
  simplest possible PDPA posture.
- **This decision is the load-bearing reason ADR-0001's `http.server` is acceptable.**
  Any requirement to reach the system from outside the LAN invalidates both: the
  correct response is a rewrite onto a real framework with real auth, not adding a
  password form to this one.
