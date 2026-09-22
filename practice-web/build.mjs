import { build } from 'esbuild';
import { mkdir, copyFile, readFile, writeFile } from 'node:fs/promises';
const out = '../app/res/practice';
await mkdir(out, {recursive:true});
await build({entryPoints:['src/app.js'],bundle:true,minify:true,format:'iife',target:['chrome100','firefox110'],outfile:`${out}/app.js`,legalComments:'linked'});
for (const name of ['index.html','style.css','demo.musicxml']) await copyFile(`src/${name}`,`${out}/${name}`);
const packages = ['opensheetmusicdisplay','pitchy','fflate','vexflow','fft.js','jszip','loglevel','typescript-collections','pako','lie','immediate','readable-stream','safe-buffer','string_decoder','core-util-is','inherits','isarray','process-nextick-args','util-deprecate','setimmediate'];
let notices = 'NoteLite practice third-party notices\n\n';
for (const name of packages) {
  const pkg = JSON.parse(await readFile(`node_modules/${name}/package.json`,'utf8'));
  let license;
  for (const file of ['LICENSE','LICENSE.md','LICENSE.txt','LICENSE-MIT','LICENSE-MIT.txt','LICENSE.markdown','license','license.md','COPYING']) {try {license = await readFile(`node_modules/${name}/${file}`,'utf8');break;}catch{}}
  if(!license && name==='fft.js') license=(await readFile(`node_modules/${name}/README.md`,'utf8')).split('#### LICENSE')[1];
  if(!license && name==='isarray') license=(await readFile(`node_modules/${name}/README.md`,'utf8')).split('## License')[1];
  if (!license) throw new Error(`Missing license: ${name}`);
  notices += `\n--- ${name} ${pkg.version} (${pkg.license}) ---\n${license}\n`;
}
await writeFile(`${out}/THIRD-PARTY.txt`,notices);
