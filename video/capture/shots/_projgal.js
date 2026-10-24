// Not footage: the 3D gallery in the real window: the top bar's button, the library, a filter, opening a model, Esc.
const { desktop, ready } = require('./_lib');
const results = [];
const check = (name, ok, detail = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`); };
module.exports = desktop({
  size: [1440, 900],
  async run(shot) {
    await ready(shot);
    const q = (js) => shot.js(js);
    await q(`window.__errs = []; window.addEventListener('error', (e) => window.__errs.push(String(e.message)));`);
    check('the top bar has the 3D button', await q(`!!document.getElementById('projOpenBtn') && !document.getElementById('projOpenBtn').hidden`));
    await shot.still('gal_topbar');
    await q(`document.getElementById('projOpenBtn').click()`); await shot.frame(30);
    const g = await q(`({ open: !document.getElementById('projLayer').hidden, gallery: !document.getElementById('projGallery').hidden, lib: document.querySelectorAll('#projLibrary .proj-tile').length, pics: [...document.querySelectorAll('#projLibrary .proj-tile img')].filter(i => i.complete && i.naturalWidth > 0).length })`);
    check('it opens the gallery', g.open && g.gallery && g.lib > 40, `${g.lib} library models, ${g.pics} pictures loaded`);
    await shot.still('gal_open');
    await q(`[...document.querySelectorAll('#projFilters .proj-chip')].find(b => b.textContent === 'Characters').click()`); await shot.frame(10);
    const n = await q(`document.querySelectorAll('#projLibrary .proj-tile').length`);
    check('the Characters filter', n === 10, `${n} shown`);
    await shot.still('gal_characters');
    await q(`[...document.querySelectorAll('#projLibrary .proj-tile')].find(b => b.textContent.includes('Spider-Man')).click()`); await shot.frame(80);
    const s = await q(`({ title: document.getElementById('projTitle').textContent, gallery: !document.getElementById('projGallery').hidden, picked: document.querySelectorAll('#projParts .proj-chip[aria-pressed=\"true\"]').length })`);
    check('a tile opens its model, nothing picked', s.title === 'Spider-Man' && !s.gallery && s.picked === 0, JSON.stringify(s));
    await shot.still('gal_spiderman');
    await q(`document.getElementById('projGalleryBtn').click()`); await shot.frame(10);
    const r = await q(`[...document.querySelectorAll('#projRecent .proj-tile b')].map(b => b.textContent)`);
    check('it is now in "Your models"', r[0] === 'Spider-Man', r.slice(0, 4).join(', '));
    await shot.still('gal_recent');
    await q(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`); await shot.frame(4);
    check('Esc closes the gallery first', (await q(`document.getElementById('projGallery').hidden`)) && (await q(`!document.getElementById('projLayer').hidden`)));
    await q(`document.querySelector('#projParts .proj-chip').click()`); await shot.frame(8);
    await shot.still('gal_picked');
    const saved = await q(`JSON.parse(localStorage.getItem('jarvis.projector.history') || '[]').map(s => s.title).slice(-3)`);
    check('models are saved for next time', saved.includes('Spider-Man'), saved.join(', '));
    check('no page errors', !(await q('window.__errs')).length, (await q('window.__errs')).join(' | '));
    console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
  },
});
