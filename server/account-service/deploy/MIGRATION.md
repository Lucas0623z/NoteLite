# Private offline data backup and restore

`tools/backup-account-data.py` backs up three complete runtime roots as one private
directory bundle. It does not deploy, stop/start services, upload a backup, change
accounts, merge libraries, or overwrite existing data. The tool and its source are
public; the produced backup is private and must never enter the public source
offer, Git, browser assets, logs, or an unencrypted public bucket.

The production layout described by the checked-in service files is:

| Label | Full root | Contents preserved |
| --- | --- | --- |
| accounts | `/var/lib/notelite-accounts` | Account UUIDs and credential hashes, sessions, profiles and idempotency receipts, personal XML, immutable history XML and analysis versions, AI request/cache rows, classrooms/submissions, existing explicit classroom recordings, internal key and operator-provided private AI configuration/assets |
| gateway | `/var/lib/notelite-gateway` | Job-to-owner UUID index, device/pair records, migration claims and deleted-owner fences |
| omr | `/var/lib/audiveris` | `jobs/` including original PDFs/images, job metadata, MusicXML/MIDI/project artifacts, worker access token and any other files actually present in this runtime root |

Use the full OMR root, not only `jobs/`, so its private worker credential remains
consistent with the account/gateway configuration. The bundle includes all regular
files and empty directories in these roots. Local-only personal practice WAVs on
an iPhone/iPad/Mac are not uploaded or manufactured by this server backup. Existing
explicitly submitted classroom audio is preserved.

Before backup or restore, an operator must put clients into maintenance, stop the
three services and prevent every other writer. `--quiesced` is mandatory. On Linux
the tool also asks `systemctl show` and rejects missing/unloaded/active services:
all three named units must exist, be loaded, and report `ActiveState=inactive`.
The tool never stops services itself. On Windows, `--quiesced` is a manual offline
assertion, and no Linux service state can be verified. Linux permission assertions
and real systemd state checks cannot be claimed from Windows fixture tests.

## Backup

The parent backup directory must already exist and be private. The chosen bundle
must be new and must not be inside or contain any source root. For example, after
the explicit maintenance/stop step:

```sh
python3 /opt/notelite-accounts/tools/backup-account-data.py backup \
  --quiesced --bundle /root/private-notelite-backups/snapshot-2026-10-12 \
  --accounts-root /var/lib/notelite-accounts \
  --gateway-root /var/lib/notelite-gateway \
  --omr-root /var/lib/audiveris
```

Every SQLite file is identified by its actual header and copied with SQLite's
backup API, including committed WAL data. The resulting snapshot uses DELETE
journaling so WAL/SHM/journal sidecars are not mistaken for separate required
files. Other files are copied unchanged. Each file is hashed with SHA256; SQLite
snapshots additionally pass `quick_check`, foreign-key checks, and necessary
account/gateway table checks. A private manifest binds all three roots and file
sizes/digests, and its own checksum detects damage. Checksums are not signatures
or encryption: retain the bundle only on trusted, encrypted/private storage.

Linux backup directories are mode `0700`, files `0600`, including keys and manifest.
Windows operators must configure restrictive filesystem ACLs; numeric POSIX modes
do not establish Windows ACL privacy. Console output contains only operation status,
counts and byte totals, never data, tokens, passwords, keys or manifest contents.

An independent read-only verification does not require stopped services because
it reads only a previously produced bundle:

```sh
python3 /opt/notelite-accounts/tools/backup-account-data.py verify \
  --bundle /root/private-notelite-backups/snapshot-2026-10-12
```

## Restore into new storage

Install compatible application code/service units first, but leave the three units
inactive. Prepare target parent directories privately. Each target below must not
exist or must be completely empty. Targets cannot overlap each other or the bundle.

```sh
python3 /opt/notelite-accounts/tools/backup-account-data.py restore \
  --quiesced --bundle /root/private-notelite-backups/snapshot-2026-10-12 \
  --accounts-root /var/lib/notelite-accounts \
  --gateway-root /var/lib/notelite-gateway \
  --omr-root /var/lib/audiveris
```

The entire bundle, paths, hashes and databases are verified before any destination
write. No traversal, symbolic links, Windows junctions, duplicate/colliding paths,
extra/missing files, corrupt databases or nonempty targets are accepted. Validated
files are copied into private sibling staging directories and checked again, then
installed into empty targets. Installation is atomic per root, not across three
filesystems; an I/O failure during final installation is reported as failed. Keep
all services stopped, inspect the new directories, and repeat a fresh empty-target
restore if necessary. The tool never deletes an existing live library to retry.

Restored files belong to the operator who ran the tool. Assign the restored roots
to the configured service identity (currently `audiveris`) before starting services;
otherwise `0600/0700` prevents that service from reading them. Preserve the original
UUIDs, DB contents and gateway index: never register replacement accounts or remap
owners. Check own and foreign-account isolation before reopening clients.

Engine binaries, application source, systemd/nginx configurations and HTTPS
certificates outside these runtime roots must be provisioned separately. Certificates
and private keys outside these roots also require a separate private operational
backup. Source archives and the bounded `/account/export` download are not substitutes
for this runtime bundle, and this tool has no JSON import endpoint.

## Local disposable restoration drill

```sh
python3 -m unittest test_account_migration -v
```

The drill uses generated temporary accounts, actual SQLite, synthetic original-score
files and a generated tiny WAV. It restores the same UUID, profile, current XML,
original history XML, detection analysis version, AI cache, job ownership and
explicit classroom recording into new storage. It exercises committed WAL data,
corruption/traversal/extra files, nonempty targets, symlinks and the CLI's private
output boundary. Linux service responses in unit tests are mocked; no production
services/accounts/keys are read or changed. The POSIX permission test is explicitly
skipped on Windows and runs on Linux.
