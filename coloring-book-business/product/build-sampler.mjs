// Builds the free 5-page "Inky & Me" sampler: sampler.html -> sampler.pdf
// Run: node build-sampler.mjs   (needs Playwright + Chromium)
import { writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const S = 'stroke="#000" stroke-width="5" stroke-linejoin="round" stroke-linecap="round"';

// Inky: a friendly ink-blob buddy. Drawn on a 200x200 grid, then placed with x/y/scale.
// arms: 'wave' (right arm up), 'up' (both up), 'down'
function inky({ x = 0, y = 0, scale = 1, arms = 'wave' } = {}) {
  const left = arms === 'up'
    ? '<ellipse cx="22" cy="78" rx="12" ry="26" transform="rotate(-35 22 78)" fill="#fff" ' + S + '/>'
    : '<ellipse cx="22" cy="125" rx="12" ry="24" transform="rotate(25 22 125)" fill="#fff" ' + S + '/>';
  const right = arms === 'down'
    ? '<ellipse cx="178" cy="125" rx="12" ry="24" transform="rotate(-25 178 125)" fill="#fff" ' + S + '/>'
    : '<ellipse cx="178" cy="78" rx="12" ry="26" transform="rotate(35 178 78)" fill="#fff" ' + S + '/>';
  return `<g transform="translate(${x} ${y}) scale(${scale})">
    ${left}${right}
    <path d="M100 22 C152 22 172 62 172 104 C172 140 168 160 162 172 Q152 186 140 174 Q130 166 120 178 Q110 190 100 178 Q90 166 80 178 Q70 190 60 176 Q50 166 40 174 Q30 182 30 160 C26 132 28 112 28 104 C28 60 50 22 100 22 Z" fill="#fff" ${S}/>
    <ellipse cx="74" cy="84" rx="19" ry="25" fill="#fff" ${S}/>
    <ellipse cx="126" cy="84" rx="19" ry="25" fill="#fff" ${S}/>
    <circle cx="78" cy="92" r="9"/><circle cx="122" cy="92" r="9"/>
    <circle cx="81" cy="88" r="3" fill="#fff"/><circle cx="125" cy="88" r="3" fill="#fff"/>
    <path d="M62 122 Q100 168 138 122 Q100 134 62 122 Z" fill="#fff" ${S}/>
    <path d="M88 142 Q100 166 112 142" fill="#fff" ${S}/>
    <path d="M58 52 Q66 44 76 48" fill="none" ${S}/>
  </g>`;
}

const star = (cx, cy, r) => {
  const pts = [];
  for (let i = 0; i < 10; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / 5, rr = i % 2 ? r * 0.45 : r;
    pts.push(`${(cx + rr * Math.cos(a)).toFixed(1)},${(cy + rr * Math.sin(a)).toFixed(1)}`);
  }
  return `<polygon points="${pts.join(' ')}" fill="#fff" ${S}/>`;
};
const balloon = (cx, cy, tx, ty) => `<path d="M${cx} ${cy + 46} Q${(cx + tx) / 2 + 20} ${(cy + ty) / 2} ${tx} ${ty}" fill="none" stroke="#000" stroke-width="3"/>
  <ellipse cx="${cx}" cy="${cy}" rx="38" ry="46" fill="#fff" ${S}/><path d="M${cx - 8} ${cy + 54} L${cx} ${cy + 44} L${cx + 8} ${cy + 54} Z" fill="#fff" ${S}/>`;

const page = (title, art, note = '') => `<section class="page">
  <h1>${title}</h1>
  <svg viewBox="0 0 700 760" class="art">${art}</svg>
  ${note ? `<p class="note">${note}</p>` : ''}
  <footer>© 2026 Inky &amp; Me Coloring Club · Free sampler · For personal &amp; classroom use</footer>
</section>`;

const pages = [
  // Cover
  `<section class="page cover">
    <h1 class="big">Inky &amp; Me</h1>
    <h2>We color together!</h2>
    <svg viewBox="0 0 700 600" class="art">${inky({ x: 150, y: 60, scale: 2, arms: 'up' })}
      ${star(90, 120, 40)}${star(610, 140, 34)}${star(600, 470, 28)}${star(100, 480, 30)}</svg>
    <h2>5 free coloring pages</h2>
    <footer>© 2026 Inky &amp; Me Coloring Club</footer>
  </section>`,
  page('Hi! I’m Inky!', `${inky({ x: 100, y: 120, scale: 2.5 })}${star(90, 90, 46)}${star(620, 110, 38)}${star(600, 650, 30)}`,
    'Inky can be any color you like!'),
  page('Count the balloons!', `${balloon(470, 110, 515, 430)}${balloon(600, 170, 520, 430)}${balloon(370, 210, 510, 435)}
    ${inky({ x: 80, y: 280, scale: 2.4, arms: 'wave' })}`, 'How many balloons does Inky have? ______'),
  page('Beach day!', `<circle cx="590" cy="110" r="60" fill="#fff" ${S}/>
    ${[0, 45, 90, 135, 180, 225, 270, 315].map(a => { const r = a * Math.PI / 180; return `<line x1="${590 + 78 * Math.cos(r)}" y1="${110 + 78 * Math.sin(r)}" x2="${590 + 105 * Math.cos(r)}" y2="${110 + 105 * Math.sin(r)}" ${S}/>`; }).join('')}
    <path d="M0 560 Q60 530 120 560 T240 560 T360 560 T480 560 T600 560 T720 560 L720 760 L0 760 Z" fill="#fff" ${S}/>
    <path d="M0 620 Q60 590 120 620 T240 620 T360 620 T480 620 T600 620 T720 620" fill="none" ${S}/>
    ${inky({ x: 120, y: 150, scale: 2, arms: 'up' })}
    <path d="M520 470 L540 560 L620 560 L640 470 Z" fill="#fff" ${S}/><path d="M530 470 Q580 400 630 470" fill="none" ${S}/>
    ${star(110, 690, 40)}${star(420, 700, 32)}`, 'Color the sun, the sea, and Inky’s bucket!'),
  page('Happy birthday, Inky!', `${inky({ x: 20, y: 240, scale: 1.9, arms: 'up' })}
    <rect x="410" y="470" width="260" height="110" rx="12" fill="#fff" ${S}/>
    <rect x="440" y="380" width="200" height="90" rx="12" fill="#fff" ${S}/>
    <path d="M440 420 Q465 445 490 420 Q515 445 540 420 Q565 445 590 420 Q615 445 640 420" fill="none" ${S}/>
    ${[490, 540, 590].map(cx => `<rect x="${cx - 9}" y="310" width="18" height="70" rx="4" fill="#fff" ${S}/><path d="M${cx} 268 Q${cx + 16} 292 ${cx} 302 Q${cx - 16} 292 ${cx} 268 Z" fill="#fff" ${S}/>`).join('')}
    <line x1="380" y1="580" x2="700" y2="580" ${S}/>
    ${star(120, 120, 40)}${star(600, 130, 36)}`, 'How many candles are on the cake? ______'),
  page('Inky &amp; Me', `${inky({ x: 0, y: 220, scale: 1.7, arms: 'wave' })}
    <rect x="380" y="140" width="300" height="480" rx="30" fill="#fff" stroke="#000" stroke-width="5" stroke-dasharray="18 14"/>
    <text x="530" y="390" text-anchor="middle" font-size="32" font-weight="900" font-family="sans-serif">Draw YOU here!</text>
    ${star(90, 110, 40)}`, 'Draw yourself next to your new buddy Inky.'),
  // Certificate + upsell
  `<section class="page cert">
    <div class="frame">
      <h1>Super Colorer!</h1>
      <p class="line">This certificate goes to</p>
      <div class="name"></div>
      <p class="line">for finishing the Inky &amp; Me sampler!</p>
      <svg viewBox="0 0 700 330" class="art small">${inky({ x: 250, y: 10, scale: 1.5, arms: 'up' })}${star(130, 160, 50)}${star(570, 160, 50)}</svg>
      <p class="line">Signed: <b>Inky</b> &nbsp;&nbsp; Date: __________</p>
    </div>
    <p class="note">Want more? Join the Inky &amp; Me Coloring Club for new pages every week.</p>
    <footer>© 2026 Inky &amp; Me Coloring Club</footer>
  </section>`,
];

const html = `<!doctype html><html><head><meta charset="utf-8"><title>Inky &amp; Me Sampler</title><style>
@page { size: Letter; margin: 0; }
* { box-sizing: border-box; margin: 0; }
body { font-family: "Arial Rounded MT Bold", "Nunito", "Helvetica", sans-serif; background: #fff; color: #000; }
.page { width: 8.5in; height: 11in; padding: 0.5in; display: flex; flex-direction: column; align-items: center; page-break-after: always; position: relative; }
h1 { font-size: 64px; font-weight: 900; color: #fff; -webkit-text-stroke: 3px #000; text-align: center; letter-spacing: 1px; }
h1.big { font-size: 110px; margin-top: 0.2in; }
h2 { font-size: 36px; font-weight: 900; margin: 0.15in 0; }
.art { width: 100%; flex: 1; }
.art.small { flex: none; height: 2.6in; }
.note { font-size: 26px; font-weight: 700; margin-bottom: 0.35in; text-align: center; }
footer { position: absolute; bottom: 0.3in; font-size: 12px; color: #444; }
.cert .frame { border: 10px double #000; border-radius: 30px; width: 100%; flex: 1; margin-bottom: 0.3in; padding: 0.4in; display: flex; flex-direction: column; align-items: center; gap: 0.2in; }
.cert .line { font-size: 28px; font-weight: 700; }
.cert .name { width: 80%; border-bottom: 4px solid #000; height: 0.7in; }
</style></head><body>${pages.join('\n')}</body></html>`;

writeFileSync(join(here, 'sampler.html'), html);

// require() honours NODE_PATH, so a globally installed Playwright works too
const { chromium } = createRequire(import.meta.url)('playwright');
const browser = await chromium.launch();
const tab = await browser.newPage();
await tab.goto('file://' + join(here, 'sampler.html'));
await tab.pdf({ path: join(here, 'sampler.pdf'), format: 'Letter', printBackground: true });
if (process.argv.includes('--previews')) {
  await tab.setViewportSize({ width: 816, height: 1056 });
  const n = await tab.locator('.page').count();
  for (let i = 0; i < n; i++) await tab.locator('.page').nth(i).screenshot({ path: join(process.argv.at(-1), `page-${i + 1}.png`) });
}
await browser.close();
console.log('Wrote sampler.html and sampler.pdf');
