---
name: backlog:oauth-state-binding-hardening
description: "Harden the Fyers OAuth callback against first-use state/auth_code interception"
date: 04-07-26
metadata:
  node_type: memory
  type: backlog-note
  feature: security-remediation
---

# OAuth State-Binding Hardening (backlog)

**Origin:** Phase 2 adversarial-validation review (`harness-phase2/adversarial-validation.json`), accepted as a documented residual by explicit user decision on 2026-07-04 (see `harness-phase2/review-decision.json`).

## Gap

Phase 2 replaced the raw `state=user_id` OAuth parameter with a signed, single-use nonce
(`auth_utils.py:140-176`, `consume_oauth_state`). This closes forgery, tampering, and simple
replay: a guessed or bit-flipped state cannot be produced without the server's signing key, and
a nonce already consumed is rejected on any later presentation.

What remains open: the nonce is not bound to the browser/session that initiated the flow at
`/fyers/auth-url`. The `state` value travels through a browser redirect as a query parameter —
the classic OAuth interception surface (browser history, `Referer` leakage, a shared proxy/CDN
log, or a MITM network position). An attacker who captures both `state` and `auth_code` before
the legitimate browser completes the redirect could complete `/fyers/callback` themselves and
receive the victim's session — once, first-use only.

## Why accepted as a residual (not a blocker)

Requires an active network-position attacker or log/history access at the exact right moment —
a narrow window, consistent with other already-accepted residuals in this program (e.g. Phase 1's
7-day signed-cookie grace period). Not exploitable by guessing, forgery, or replay alone.

## Proposed fix (not yet implemented)

Bind the OAuth flow to the initiating browser:
1. At `/fyers/auth-url` generation, set a short-lived, `HttpOnly`, `Secure` cookie containing a
   random verifier value (PKCE-style), and include a hash of it in the signed `state` payload.
2. At `/fyers/callback`, re-derive the hash from the cookie presented on that request and compare
   against the value embedded in the signed `state`. Reject on mismatch or missing cookie.
3. This closes the interception window because the attacker would also need the victim's cookie
   jar, not just the redirect URL.

## Scope

Files likely touched: `trading-app/auth_utils.py` (state payload + verifier hash), `trading-app/app.py`
(`/fyers/auth-url` and `/fyers/callback` handlers). Should run through the standard RIPER-5 flow
(not a quick fix — touches the auth/OAuth trust boundary) when picked up.
