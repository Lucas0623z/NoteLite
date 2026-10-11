# NoteLite accounts and classroom backend

This is a separate, standard-library Python service. It adds account registration,
multiple independent sessions sharing one user UUID, personal MusicXML sync,
official-score practice history, six-character temporary classroom codes, homework,
and explicitly submitted classroom recordings. It does not run pitch detection or
claim that uploaded recordings have been analysed.

## Run and verify

Python 3.12 or newer is recommended. From the repository root:

```powershell
python -m unittest discover -s server/account-service -v
```

The tests use a real HTTP server on loopback, durable SQLite, synthetic accounts,
and a tiny generated WAV. They do not read production passwords or tokens. The
service rejects unverified OMR references and legacy migrations by default.

```text
python account_service.py --root /var/lib/notelite-accounts --port 8771 \
  --public-origin https://124.221.211.156 \
  --internal-key-file /var/lib/notelite-accounts/internal-key
```

Bind only `127.0.0.1`; expose `/api/account/` through the existing trusted HTTPS
server. The supplied systemd/nginx files are templates, not evidence of deployment.
The operator generates a random internal key, stores it outside the source tree with
mode `0600`, and shares it only with the OMR gateway process. Do not put it into
JavaScript, application bundles, reports, access logs or source archives.

## Accounts and authentication

* Usernames: 3–32 ASCII letters, digits, `.`, `_`, `-`, case insensitive.
* Passwords: 15–256 characters, at most 1024 UTF-8 bytes; no silent truncation.
* Password storage: unique 16-byte salt and scrypt `N=131072, r=8, p=1`, 32-byte
  output. Two simultaneous password computations maximum. This follows the
  [OWASP password storage recommendation](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt).
* Registration: 6 requests per real client IP per hour. Login: 12/IP/minute and
  10/IP/username/15 minutes. Unknown usernames perform the same scrypt work.
  Nginx must overwrite `X-Real-IP`, not append a client-supplied value.
* Browser sessions: `__Host-notelite-account`, `HttpOnly; Secure; SameSite=Strict;
  Path=/`, 30 days. Registration/login require the configured HTTPS Origin. Every
  browser mutation requires the same Origin and `X-NoteLite-CSRF`. `/me` returns
  a stable, token-derived CSRF value; multiple tabs do not invalidate one another.
* Native sessions: independently issued Bearer token, 90 days; store it in an
  origin-scoped platform Keychain/credential store. A browser token is never
  accepted as a native bearer or vice versa.
* Only session/CSRF hashes are stored. Raw bearer tokens are returned only at
  native login/registration; the browser token is returned only as HttpOnly cookie.
* A user can inspect and revoke their own sessions. Revoking one device does not
  revoke other devices. The service bounds active sessions at 32 per account.
* `X-NoteLite-Expected-User` is an optional current-user UUID consistency check.
  After authentication a mismatch returns `409` before reading/writing. The
  header never grants access. Send it on requests made from an already loaded
  account screen to prevent stale background uploads after account switching.

Password reset/email verification are not provided by this username-only release.
There is no public administrator or teacher-promotion endpoint.

## Public API

All paths below are relative to `/api/account`. JSON requests use
`Content-Type: application/json`; unknown/duplicate fields and nonfinite numbers
are rejected. Protected endpoints require the authentication described above.

| Method | Path | Request / response |
| --- | --- | --- |
| GET | `/health` | Public status and ownership-adapter availability |
| POST | `/register`, `/login` | `{username,password,mode,deviceName?}` → identity/session |
| GET | `/me` | Current identity; browser additionally receives `csrf` |
| POST | `/logout` | Revoke current session; clear account cookie |
| GET | `/sessions` | `{sessions:[{sessionId,deviceName,kind,createdAt,expiresAt}]}` |
| DELETE | `/sessions/{uuid}` | Revoke only a session belonging to the authenticated user |
| GET | `/catalog` | Legal official-score catalogue metadata |
| GET | `/catalog/{id}/musicxml` | Official MusicXML |
| GET | `/scores` | Personal score metadata, newest first |
| POST | `/scores` | `{title,musicxml,requestId?}` or `{title,jobId,scoreIndex,revision,requestId?}` |
| GET | `/scores/{uuid}` | `{id,title,revision,updatedAt,etag,omr?}` |
| GET | `/scores/{uuid}/musicxml` | Personal XML, plus exact `ETag` |
| PUT | `/scores/{uuid}` | `{musicxml,title?}`, mandatory `If-Match` → new revision |
| POST | `/history` | Idempotent practice event with score snapshot |
| GET | `/history?limit=100&cursor=…` | Own events and optional `nextCursor`; limit 1–200 |
| GET | `/history/{eventId}/musicxml` | Exact practiced XML, SHA256 as ETag |
| GET | `/history/{eventId}/analyses` | Owner only: immutable analysis version metadata and `latestVersion` |
| POST | `/history/{eventId}/analyses` | Owner only: `{requestId,parentVersion,sourceHash,analysis}` → new immutable NoteWise V2 analysis |
| GET | `/history/{eventId}/analyses/{version}` | Owner only: one immutable analysis, its canonical SHA256 and score source hash |
| GET / POST | `/courses` | Own/enrolled classrooms / create `{title}` (max 40 chars) |
| GET | `/courses/{uuid}` | Role, teacher username, shared scores, delivered scores, sharing scope |
| POST | `/courses/{uuid}/scores` | Teacher only: `{sourceKind:'official'|'personal',scoreId}` → immutable course snapshot |
| POST | `/courses/{uuid}/codes` | Teacher only: `{ttlSeconds?,maxUses?}` → one-time display of 6-character code |
| DELETE | `/courses/{uuid}/codes/{codeId}` | Teacher revokes this code |
| POST | `/course-codes/preview` | `{code}` → course name, teacher and explicit sharing scope |
| POST | `/course-codes/join` | `{code}` → student membership and own practice-score copies |
| DELETE | `/courses/{uuid}/membership` | Student leaves; previously submitted homework retained |
| GET | `/courses/{uuid}/roster` | Teacher only: enrolled usernames/UUIDs and joined times |
| GET / POST | `/courses/{uuid}/assignments` | List / teacher creates `{title,courseScoreId,dueAt?,requirements?}` |
| POST | `/uploads` | Student: `{assignmentId,size,mime,sha256}` → reserved upload |
| GET | `/uploads/{uuid}` | Same student: `{uploadId,assignmentId,size,offset,mime,complete,expiresAt}` |
| PUT | `/uploads/{uuid}` | Binary chunk ≤8 MiB, `Upload-Offset`, `application/octet-stream` |
| POST | `/uploads/{uuid}/complete` | Verify full size, SHA256 and container signature/format |
| POST | `/assignments/{uuid}/submissions` | Student: `{eventId,uploadId?,analysis?,analysisVersion?}` → submitted homework pinned to that analysis version |
| GET | `/assignments/{uuid}/submissions` | Teacher sees that assignment; student sees only own submissions |
| GET | `/submissions/{uuid}` | Submitting student or that classroom's teacher only |
| GET | `/submissions/{uuid}/musicxml` | Same scope, exact practiced-score snapshot |
| GET | `/submissions/{uuid}/audio` | Same scope, streamed attachment; supports one byte Range |
| POST | `/legacy/claim` | Dual-proof migration hook; disabled until configured |

The only seeded official score is `notelite-four-notes-v1`, revision `1`: the
newly composed C4–D4–E4–F4 exercise in 4/4 at quarter=80, dedicated to CC0-1.0.
No third-party score collection is silently downloaded or uploaded.

### Identity response

```json
{
  "authenticated": true,
  "userId": "00000000-0000-0000-0000-000000000001",
  "username": "lucas",
  "sessionId": "00000000-0000-0000-0000-000000000002",
  "deviceName": "iPad",
  "expiresAt": "2027-01-09T00:00:00+00:00",
  "kind": "native",
  "token": "ONLY_RETURNED_ON_NATIVE_REGISTRATION_OR_LOGIN"
}
```

The UUIDs/token text in this example are placeholders, not usable credentials.
Browser responses omit `token` and include `csrf`.

### Score sync and retry

Creation optionally takes UUID `requestId`. An identical request retried by the
same user returns `200`, the same score ID and `duplicate:true`; first creation
returns `201` and `duplicate:false`. Reusing the ID for different input returns
`409`. Different users have independent request-ID namespaces. OMR reference
retries can return the previous result without repeating upstream import.

The score ETag is `"{scoreUUID}:{revision}"`. Saving with a stale version returns
`409`, and never overwrites the other device's edit. Missing `If-Match` returns
`428`. The client must reload and merge consciously. Personal storage is bounded
at 1000 scores / 100 MiB. MusicXML is limited to 10 MiB each; only partwise scores
with a part-list and part are accepted. Benign external MusicXML DOCTYPE is
preserved but removed before parsing; no external DTD is fetched. Internal DTDs
and entity declarations are refused.

### Practice event

```json
{
  "eventId": "00000000-0000-0000-0000-000000000003",
  "sourceKind": "official",
  "scoreId": "notelite-four-notes-v1",
  "scoreRevision": 1,
  "mode": "free",
  "durationSeconds": 30,
  "startedAt": "2026-10-11T09:00:00Z",
  "endedAt": "2026-10-11T09:00:30Z",
  "analysis": null
}
```

The server checks the revision when present, owns/validates the referenced score,
and persists exact practiced MusicXML + SHA256 + revision. Later score edits do
not modify history. The server returns `{event,duplicate,scoreValidated:false}`;
the stored event contains `scoreRevision`, `scoreSha256` and an explicit analysis
state. Equal event-ID retries return `200`; changed contents return `409`, even
across devices. History is bounded to 20,000 events and 100 MiB of score snapshots
per account. Pagination orders equal receipt timestamps by UUID, so events are
not skipped.

`mode` is `free`, `strict`, `follow` or `playback`. Timing is client reported, not
proof of performance accuracy. No accuracy percentage or synthetic pitch score
is accepted. Free timing and playback cannot contain pitch analysis. For actual
analysis, the permitted shape is:

```json
{
  "status": "uncertain",
  "source": "client-reported",
  "errors": [{"type":"uncertain","measure":1,"confidence":0.4}]
}
```

Status may be `uncertain` or `analysed`; error types are `wrong`, `missed`, `extra`,
`rhythm`, `uncertain`. Optional error fields are `noteId`, `measure`,
`expectedMidi`, `playedMidi`, `cents`, `confidence`. At most 5000 errors / 1 MiB.
Every saved result includes `verifiedByServer:false`. Null/omitted analysis is
stored as `{status:'unanalysed',source:'none',errors:null,verifiedByServer:false}`.
Submitting homework without a separate analysis reuses this event's analysis.

### NoteWise V2 evidence and reanalysis

Structured V2 records bind `takeId` to the practice event UUID and
`sourceScoreSha256` to the immutable practiced MusicXML. The server checks the
score relationship and derives dimension denominators from raw opportunities and
detector evidence using `performance_analysis.py`. Measurement remains client
reported (`verifiedByServer:false`); `snapshotValidatedByServer:true` describes
the checked score relationship only. A new V2 history event creates version 1.
The original history payload and practiced XML never change when reanalysed.

Reanalysis uses a UUID `requestId`, the last seen integer `parentVersion` and
mandatory `sourceHash` equal to the event's stored XML SHA256. Concurrent changes
or a changed request body with a reused request ID return `409`. An exact retry
returns its original version even after later versions exist. Each canonical JSON
payload is limited to 1 MiB of UTF-8; each event has at most 64 versions, with
128 MiB total analysis storage per account. History lists expose the latest
analysis/version/hash. The separate version list returns metadata only; fetch
one version to read its full evidence. Teachers see the submitted version and
cannot read later private reanalyses or the owner's private version endpoints.

`deploy/public-source-files.json` is the explicit public source allowlist,
including the normalizer, synthetic fixture, regression tests and both interface
schemas. Generate staged source hashes with
`python deploy/build-public-manifest.py --output manifest.json`. Public archive
builders must copy only these paths; private prompts, keys, recordings, SQLite
files and user history must remain outside the source offer. Both installers
reject an incomplete module manifest and compile the normalizer before restart.

### Classroom privacy and recording

Creation makes that user the classroom's teacher. Code redemption makes another
user a student; it cannot grant teacher privileges. Codes use six cryptographically
random characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789` (30 bits); only SHA256
hashes are stored. Default lifetime is 24 hours, maximum 7 days; default 50 new
members, maximum 500. Preview and join share a limit of 6/account/minute and
20/real-IP/minute. The UI must show preview's `sharingScope` before confirming
join. Retrying join is idempotent and does not consume another use or duplicate
practice-score copies. Expired/revoked codes cannot join; an exhausted code
cannot admit new users.

Students submit an event for the assigned course score (or their delivered copy),
optionally with a completed audio upload and real client-reported analysis. The
teacher can access only that classroom's submitted event, practiced-score
snapshot and recording. Teacher roster access does not grant private history,
other personal scores, unsubmitted uploads, or other classrooms' data. Leaving a
classroom stops future uploads/submissions; previously explicitly submitted work
remains accessible to that classroom teacher and its author.

Audio is stored as private UUID files, never SQLite BLOBs. Default single-file
limit is 100 MiB, per-account reserved/complete limit 1 GiB, free-disk reserve
256 MiB; configurable CLI flags end in `-mb`. Uploads expire after 7 days if
unfinished. Chunk positions must match exactly (`409` otherwise), final size and
SHA256 must agree, and an accepted audio container signature is required. PCM
WAV additionally validates channel/sample format and actual frame count. Accepted
MIME types: `audio/wav`, `audio/mpeg`, `audio/ogg`, `audio/mp4`. Container validation
does not imply the recording was listened to, decoded by a detector, or assessed.
Completed audio is not public: only a scoped submission route exposes it, with
`nosniff`, no-store and safe attachment name. Back up the SQLite DB and recordings
directory together. This release retains submitted homework until an operator
applies an explicit retention policy; it does not silently erase class evidence.

## Existing OMR gateway integration

New jobs authenticated by an account must use the account user UUID as their
owner. Existing anonymous-device owner UUIDs must remain intact until dual-proof
migration. Do not rewrite production ownership to a test account.

The gateway can ask this loopback-only endpoint:

```text
POST /internal/account/resolve
X-NoteLite-Internal-Key: <server-only secret>
Content-Type: application/json

{"token":"<client session token>","kind":"native"}
```

Successful response:

```json
{"owner":"<user UUID>","sessionId":"<session UUID>","kind":"native","csrfHash":"<SHA256>","expiresAt":"<ISO timestamp>"}
```

Nginx must deny `/internal/` and strip the internal-key header on public proxied
requests. The account resolver returns `401` for an expired/revoked/wrong-profile
session; gateway outages must fail closed (`502`/`503`), never fall back to another
user. If `__Host-notelite-account` exists, do not fall back to the old device cookie
when it is invalid. Browser OMR writes require original matching Origin and
SHA256(`X-NoteLite-CSRF`) == `csrfHash`; the resolver itself does not authorize a
public write. Native accounts use a distinct profile before old-device fallback.

For OMR imports instantiate `Store(..., omr_import=callback)`:

```text
callback(user_uuid, job_uuid, score_index, requested_revision) -> exact MusicXML
```

The adapter must verify the existing gateway DB's job owner is this user UUID,
check the selected score and revision before/after reading the upstream XML,
and reject another user with `404` or a changed revision with `409`. Never trust
caller-provided XML/job ownership. The default is `503` until an adapter is
installed, and the public health reports this status.

Legacy migration is `POST /legacy/claim`, authenticated account plus body
`{deviceToken,deviceKind,deviceCSRF?}`. `Store(..., legacy_claim=callback)` receives
`(user_uuid, body, origin)`. The adapter must verify the old gateway device token
and its profile, old browser CSRF/Origin when applicable, atomically move only
that authenticated legacy owner's jobs, and revoke/rotate old owner sessions.
No client `owner`, `userId` or arbitrary job-ID list is accepted. Default is `503`.
Migration is a concrete separate authorization action: a login must not silently
import a shared machine's previous guest/paired-device data.

## Operational limits

There are 16 concurrent HTTP workers. Request/socket/body limits bound memory;
all error responses are generic and never echo passwords, bearer tokens,
recordings, file paths or upstream credentials. Session and course code hashes
are persistent, so process restart does not lose membership/history or resurrect
revoked credentials. Rate-limit windows are in-memory and reset on process
restart; retain nginx/edge limits for sustained public operation.

## Private practice analysis instructions

Optional V2 text analysis requires operator-provided instruction assets. Configure
`NOTELITE_PRACTICE_SKILL_DIR=/var/lib/notelite-accounts/practice-record-analysis`
and set `NOTELITE_DEEPSEEK_KEY_FILE` separately to the private credential file.
Keep the original eight instruction files unchanged in that private directory,
with directory permissions `0700` and file permissions `0600` for the service
account. The provider reads the exact system prompt and both schemas from this
directory. Missing or invalid optional configuration disables text analysis while
the account, history, classroom and score services remain available.

These custom instructions, examples and prompt are private deployment assets;
do not include them in GitHub, client bundles, public source offers, web roots or
logs. The retained local `skills/practice-record-analysis/` directory is ignored
by Git. A whole-directory archive can still include ignored files: build public
source archives from a clean checkout or an explicit public file manifest, and
transfer private assets separately.

`contracts/practice-record-analysis/` publishes only the two JSON schemas as
interface contracts. The public tests use an explicitly synthetic prompt and
temporary configuration directory, with no custom prompt, real API key or network
request. A clean checkout can run the full suite with Python 3.12:

```text
python -m unittest discover -s server/account-service -v
python -m unittest discover -s server/omr-gateway -v
```

Production cache fingerprints still include the exact configured prompt and
schema hashes, model settings and rule versions. Changing private assets changes
that fingerprint; it does not reuse analyses produced by different instructions.
