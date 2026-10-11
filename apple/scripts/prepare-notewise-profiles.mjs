import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { INSTRUMENT_PROFILES, resolveProfile } from '../../practice-web/src/instruments.js';

const source = new URL('../../practice-web/src/instruments.js', import.meta.url);
const target = new URL('../NoteLite/NoteWiseProfiles.json', import.meta.url);
const names = ['harpsichord','english-horn','bass','organ','accordion','harmonica','piccolo','recorder','guitar','sax','erhu','guzheng','pipa','guqin','suona','strings','winds','other'];
const value = { schemaVersion: 1, source: 'practice-web/src/instruments.js', sourceSha256: createHash('sha256').update(await readFile(source)).digest('hex'), profiles: [...INSTRUMENT_PROFILES, ...names.map(resolveProfile)] };
const exact = JSON.stringify(value, null, 2) + '\n';
if (process.argv.includes('--write')) await writeFile(target, exact);
else if (await readFile(target, 'utf8') !== exact) throw new Error('Native NoteWise profiles differ from the shared resolver. Run this script with --write.');
console.log(`NoteWise shared profiles verified: ${value.profiles.length} (${fileURLToPath(target)})`);
