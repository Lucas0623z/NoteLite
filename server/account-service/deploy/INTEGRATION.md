# Account and OMR production integration

Use `integrated_service.py` with `notelite-accounts-integrated.service`, installed
as `notelite-accounts.service`. It injects OMR owner/immutable ETag snapshot and
explicit dual-proof migration callbacks; the original unconfigured launcher
continues to fail closed. The integrated process needs write access to both
`/var/lib/notelite-accounts` and `/var/lib/notelite-gateway`, because migration
changes the gateway ownership index transactionally. It never changes uploaded
scores or the OMR task store itself.

The account key is generated once on the server in
`/var/lib/notelite-accounts/internal-key`, mode 0600, owned by audiveris. Both
service processes read it; browsers and native apps never receive it. The OMR
administrator token remains in its pre-existing private file. Neither secret
belongs in source archives, manifests, deployment arguments or command output.

Install `notelite-gateway-accounts.service` as `notelite-gateway.service`. Its
optional account resolver contacts only loopback 8771. An invalid account cookie
never falls back to the previous device's library; an unavailable account
resolver fails closed. Browser mutations need the exact HTTPS Origin and current
account CSRF. Native sessions resolve account identity before legacy device auth.
Conflicting browser and native principals are rejected. `X-NoteLite-Expected-User`
is a consistency check, and cannot grant ownership.

Render nginx with `render_nginx.py --stage https --accounts`. `/api/account/` goes
to loopback 8771; other `/api/` routes retain loopback 8770. The proxy replaces
`X-Real-IP` and strips the internal-key header. `/internal` and `/internal/` are
denied. OMR remains loopback 8765. Existing certificate renewal is unchanged.

Legacy claim requires an authenticated account and a valid old device credential.
For an old browser credential, its own CSRF and HTTPS Origin are required too.
The old owner is derived from that credential, never from caller JSON. A single
SQLite transaction moves only that owner's job index and revokes its old devices
and unused pairing codes. In-flight late registrations cannot recreate that
owner's private library. Owners already representing accounts are not eligible.
Nothing is silently migrated on login. Production tests use isolated synthetic
accounts/owners and must never claim the user's real previously paired library.

`SOURCE-MANIFEST.json` in the public source archive lists exact source bytes.
The deployed module, gateway and account manifests exclude all runtime data.
