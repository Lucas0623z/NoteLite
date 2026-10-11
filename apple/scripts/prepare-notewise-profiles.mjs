import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { INSTRUMENT_PROFILES, resolveProfile } from '../../practice-web/src/instruments.js';

const source = new URL('../../practice-web/src/instruments.js', import.meta.url);
const target = new URL('../NoteLite/NoteWiseProfiles.json', import.meta.url);
const names = ['harpsichord','english-horn','bass','organ','accordion','harmonica','piccolo','recorder','guitar','sax','erhu','guzheng','pipa','guqin','suona','strings','winds','other'];
// Git checkouts use platform-specific line endings unless explicitly pinned.
// Hash the canonical LF source to keep the same verified profile artifact on
// Windows authoring workspaces and Apple build runners.
const canonicalSource = (await readFile(source, 'utf8')).replace(/\r\n/g, '\n');
// Exponentiation can differ by one floating-point ULP between V8 hosts. Range
// boundaries need twelve significant digits, not platform-specific binary tails.
const profiles = [...INSTRUMENT_PROFILES, ...names.map(resolveProfile)].map(p => ({...p, minHz: Number(p.minHz.toPrecision(12)), maxHz: Number(p.maxHz.toPrecision(12))}));
const value = { schemaVersion: 1, source: 'practice-web/src/instruments.js', sourceSha256: createHash('sha256').update(canonicalSource).digest('hex'), profiles };
const exact = JSON.stringify(value, null, 2) + '\n';
if (process.argv.includes('--write')) await writeFile(target, exact);
else if (await readFile(target, 'utf8') !== exact) {
  const committed = JSON.parse(await readFile(target, 'utf8'));
  const mismatches = profiles.filter((p, index) => JSON.stringify(p) !== JSON.stringify(committed.profiles?.[index])).map(p => p.id);
  throw new Error(`Native NoteWise profiles differ from the shared resolver (source=${committed.sourceSha256 === value.sourceSha256}, profiles=${mismatches.join(',')}). Run this script with --write.`);
}
console.log(`NoteWise shared profiles verified: ${value.profiles.length} (${fileURLToPath(target)})`);
