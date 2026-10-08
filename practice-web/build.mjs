import { build } from 'esbuild';
import { mkdir, copyFile, cp, stat, readFile, writeFile } from 'node:fs/promises';
const out = '../app/res/practice';
await mkdir(out, {recursive:true});
await build({entryPoints:['src/app.js'],bundle:true,minify:true,format:'iife',target:['chrome100','firefox110','safari16'],outfile:`${out}/app.js`,legalComments:'linked'});
for (const name of ['index.html','style.css','demo.musicxml']) await copyFile(`src/${name}`,`${out}/${name}`);
// Keep asset URLs identical in the desktop browser and the bundled Apple web view.
try {
  if ((await stat('src/icons')).isDirectory()) await cp('src/icons', `${out}/icons`, {recursive:true});
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}
const packages = ['opensheetmusicdisplay','pitchy','fflate','vexflow','fft.js','jszip','loglevel','typescript-collections','pako','lie','immediate','readable-stream','safe-buffer','string_decoder','core-util-is','inherits','isarray','process-nextick-args','util-deprecate','setimmediate'];
let notices = '音伴练习 · 第三方开源许可\n\n';
for (const name of packages) {
  const pkg = JSON.parse(await readFile(`node_modules/${name}/package.json`,'utf8'));
  let license;
  for (const file of ['LICENSE','LICENSE.md','LICENSE.txt','LICENSE-MIT','LICENSE-MIT.txt','LICENSE.markdown','license','license.md','COPYING']) {try {license = await readFile(`node_modules/${name}/${file}`,'utf8');break;}catch{}}
  if(!license && name==='fft.js') license=(await readFile(`node_modules/${name}/README.md`,'utf8')).split('#### LICENSE')[1];
  if(!license && name==='isarray') license=(await readFile(`node_modules/${name}/README.md`,'utf8')).split('## License')[1];
  if (!license) throw new Error(`Missing license: ${name}`);
  notices += `\n--- ${name} ${pkg.version} (${pkg.license}) ---\n${license}\n`;
}
await writeFile(`${out}/THIRD-PARTY.txt`,notices+'\n\nWindows local audio\n'+await readFile('../native/audio/THIRD_PARTY_NOTICES.md','utf8')+'\n'+await readFile('../native/audio/vendor/miniaudio/LICENSE','utf8')+'\n\nSpotify Basic Pitch 0.4.0: Apache-2.0. Local ONNX weights and dependency notices ship in tools/local-analysis/THIRD-PARTY.txt and python/site-packages (package licenses and .dist-info directories). See local-analysis/windows-lock.json for exact versions and hashes.\n');
