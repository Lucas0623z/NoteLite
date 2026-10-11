# NoteLite V2 practice fact interpretation

The account service exposes authenticated `POST /api/account/practice-analysis`.
The service aggregates only the selected owner's saved history in Python. The
DeepSeek Chat Completions request receives the V2 aggregate facts and supplied
system prompt. MusicXML, raw performance arrays, recordings, notes and private
credentials are excluded from the model input.

Install the delivered `practice_analysis.py`, two public `contracts` schemas,
and updated account service together. Install the operator's original eight
custom assets separately in the private runtime directory
`/var/lib/notelite-accounts/practice-record-analysis` (directory `0700`, files
`0600`, owned by `audiveris`). `NOTELITE_PRACTICE_SKILL_DIR` points to that private
directory. The custom skill, exact prompt, examples and notes are not public
source assets. The public tests use a separately generated synthetic prompt.
Run the full account test suite before deployment. Copy the supplied systemd
drop-in to `/etc/systemd/system/notelite-accounts.service.d/analysis.conf` only
after providing the server's private key file. The drop-in selects
`deepseek-flash`; it contains only a server-local file path, never a key.

The credential is `/var/lib/notelite-accounts/deepseek-key`, owned by the
`audiveris` service user with mode `0600`. The parent runtime directory is
`0700`. Do not include it, account databases, cache or uploaded data in source
archives or logs. The service reads it only inside the outbound request.

A successful model result must pass the full V2 schema, facts and semantics
checks before caching. Free timer data produces `investment_only`; it cannot
prove musical strength, progress or a zero-error performance. Every cache hit
reauthorizes the selected history against the current account. An unknown
outbound result blocks another call for the same input, including with a new
request ID. Known failures return program-produced fallback facts with an
explicit retry flag; a later paid attempt requires a new user action.

The production acceptance uses one synthetic timer event and one actual model
request, then validates the cached repeat and cross-account/empty-record
refusals. No user's original performance is submitted as an acceptance test.
Public corresponding source includes the AI module, necessary schema contracts
and synthetic tests. It excludes the operator's custom prompt/skill/example
assets, runtime data, private credentials and client/audio engine files.
