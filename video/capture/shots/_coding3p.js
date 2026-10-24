// Not footage: Coding Mode's project sidebar in the real window with the real engine (backend.py, sandboxed: programs
// such as the Finder are recorded, not run). Three sample projects are put in the demo engine's own data folder
// (wiped at every start), then: sort, hide and show, the earlier-projects setting, rename, remove from the list
// (files kept), and moving to the Trash (here the sandbox stops the Finder, so it must fail honestly, removing nothing).
//   LOOK=next electron video/capture/record.js _coding3p
const fs = require('fs');
const path = require('path');
const { desktop, ready } = require('./_lib');
const DATA = path.join(__dirname, '..', '..', 'cache.nosync', 'data');
const PROJECTS = path.join(DATA, 'projects');
const results = [];
const check = (name, ok, detail = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + String(detail).slice(0, 240) : ''}`); };

function seed() {   // sample projects (labelled as such), written the way the engine writes its own records
  const now = Date.now() / 1000;
  const history = [];
  fs.mkdirSync(path.join(DATA, 'coding_chats'), { recursive: true });
  [['alpha-shop', 'Alpha shop', 3000, 9000], ['zebra-game', 'Zebra game', 100, 5000], ['mango-api', 'Mango API', 2000, 100]].forEach(([dir, title, ageUpdated, ageCreated], i) => {
    const folder = path.join(PROJECTS, dir);
    fs.mkdirSync(folder, { recursive: true });
    fs.writeFileSync(path.join(folder, 'index.html'), '<!doctype html><title>sample</title>\n');
    history.push({ id: `p${i}`, request: title, name: dir, path: folder, language: 'HTML', phase: 'done', files: [{ path: 'index.html', status: 'written' }], checks: [], created: now - ageCreated, updated: now - ageUpdated });
    fs.writeFileSync(path.join(DATA, 'coding_chats', `t${i}.json`), JSON.stringify({ id: `t${i}`, title, path: folder, created: now - ageCreated, updated: now - ageUpdated,
      messages: [{ id: 'u', role: 'user', kind: 'text', text: `Build ${title} (sample)`, at: now - ageCreated }] }));
  });
  fs.writeFileSync(path.join(DATA, 'coding_history.json'), JSON.stringify(history));
}

module.exports = desktop({
  size: [1440, 900],
  async run(shot) {
    const names = () => shot.js(`[...document.querySelectorAll('.cd-thread-list .cd-thread b')].map((b) => b.textContent)`);
    const toast = () => shot.js(`document.querySelector('.cd-toast').textContent`);
    await ready(shot);
    seed();
    await shot.click('#codeBtn');
    await shot.wait('window.codingOpen()', { timeout: 10000 });
    await shot.wait(`document.querySelectorAll('.cd-thread-list .cd-thread').length === 3`, { timeout: 10000 });
    check('The three projects are listed, most recent first', JSON.stringify(await names()) === '["Zebra game","Mango API","Alpha shop"]', await names());

    // sort
    for (const [label, want] of [['Name', '["Alpha shop","Mango API","Zebra game"]'], ['Date created', '["Mango API","Zebra game","Alpha shop"]']]) {
      await shot.click('.cd-sort');
      await shot.js(`[...document.querySelectorAll('.cd-sort-menu .cd-menu-item')].find((b) => b.textContent === ${JSON.stringify(label)}).click()`);
      await shot.wait(`document.querySelectorAll('.cd-thread-list .cd-thread').length === 3`);
      await shot.frame(4);
      check(`Sort by ${label}`, JSON.stringify(await names()) === want, await names());
    }
    const prefsFile = path.join(DATA, 'coding_prefs.json');
    await shot.frame(10);
    check('The sort order is saved on disk', JSON.parse(fs.readFileSync(prefsFile, 'utf8')).sort === 'created');

    // hide one: through the ⋯ menu, from the keyboard
    await shot.js(`[...document.querySelectorAll('.cd-thread-item')].find((li) => li.textContent.includes('Mango')).querySelector('.cd-thread').focus()`);
    await shot.js(`document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'ContextMenu', bubbles: true }))`);
    await shot.wait(`!document.querySelector('.cd-row-menu').hidden`);
    check('The context menu opens from the keyboard, focused', await shot.js(`document.activeElement.closest('.cd-row-menu') !== null`));
    await shot.hold(400);
    const box = await shot.js(`(() => { const m = document.querySelector('.cd-row-menu'); const r = m.getBoundingClientRect(); const cs = getComputedStyle(m); return [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height), cs.display, cs.visibility, cs.opacity, m.parentElement.className]; })()`);
    check('The menu is on screen, beside its project', box[0] >= 0 && box[1] > 0 && box[2] < 400 && box[3] > 60 && box[0] + box[2] <= 1440 && box[6] === '1', JSON.stringify(box));
    await shot.still('coding3p_menu');
    await shot.js(`[...document.querySelectorAll('.cd-row-menu .cd-menu-item')].find((b) => /Hide/.test(b.textContent)).click()`);
    await shot.wait(`document.querySelectorAll('.cd-thread-list .cd-thread').length === 2`, { timeout: 10000 });
    check('Hidden: gone from the list, counted below, files untouched', (await shot.js(`document.querySelector('.cd-hidden-toggle').textContent`)).includes('(1)') && fs.existsSync(path.join(PROJECTS, 'mango-api', 'index.html')));
    await shot.click('.cd-hidden-toggle');
    await shot.frame(4);
    check('Hidden projects can be shown', (await shot.js(`document.querySelector('.cd-hidden-list').textContent`)).includes('Mango API'));
    await shot.still('coding3p_hidden');
    await shot.js(`[...document.querySelectorAll('.cd-hidden-list .cd-thread-item')][0].querySelector('.cd-thread-more').click()`);
    await shot.js(`[...document.querySelectorAll('.cd-row-menu .cd-menu-item')].find((b) => /Show in the list/.test(b.textContent)).click()`);
    await shot.wait(`document.querySelectorAll('.cd-thread-list .cd-thread').length === 3`, { timeout: 10000 });
    check('…and restored', JSON.parse(fs.readFileSync(prefsFile, 'utf8')).hidden.length === 0);

    // the earlier-projects setting
    await shot.js(`document.querySelectorAll('.cd-thread-list .cd-thread')[0].click()`);   // open one: it stays listed
    await shot.wait(`document.querySelector('.cd-thread[aria-current="true"]')`, { timeout: 10000 });
    await shot.click('.cd-earlier');
    await shot.frame(6);
    check('Hiding earlier projects keeps only the open one, and says how many are tucked away', (await names()).length === 1 && /2 earlier projects are tucked away/.test(await shot.js(`document.querySelector('.cd-threads-empty').textContent`)), await names());
    check('That setting is saved', JSON.parse(fs.readFileSync(prefsFile, 'utf8')).showEarlier === false);
    await shot.still('coding3p_earlier');
    await shot.js(`document.querySelector('.cd-threads-empty .cd-linklike').click()`);
    await shot.wait(`document.querySelectorAll('.cd-thread-list .cd-thread').length === 3`);

    // rename: the name, never the folder
    await shot.js(`[...document.querySelectorAll('.cd-thread-item')].find((li) => li.textContent.includes('Zebra')).querySelector('.cd-thread-more').click()`);
    await shot.js(`[...document.querySelectorAll('.cd-row-menu .cd-menu-item')].find((b) => b.textContent === 'Rename').click()`);
    await shot.wait(`document.querySelector('.cd-thread-rename input')`);
    await shot.js(`(() => { const i = document.querySelector('.cd-thread-rename input'); i.value = 'Zebra runner'; i.closest('form').requestSubmit(); })()`);
    await shot.wait(`[...document.querySelectorAll('.cd-thread b')].some((b) => b.textContent === 'Zebra runner')`, { timeout: 10000 });
    check('Rename changes the name, and the folder keeps its own', fs.existsSync(path.join(PROJECTS, 'zebra-game')));

    // remove from the list (the default): files stay
    const openRemove = async (who) => {
      await shot.js(`[...document.querySelectorAll('.cd-thread-item')].find((li) => li.textContent.includes(${JSON.stringify(who)})).querySelector('.cd-thread-more').click()`);
      await shot.js(`[...document.querySelectorAll('.cd-row-menu .cd-menu-item')].find((b) => /Remove/.test(b.textContent)).click()`);
      await shot.wait(`!document.querySelector('.cd-dialog-scrim').hidden`);
    };
    await openRemove('Alpha');
    const dialogText = await shot.js(`document.querySelector('.cd-dialog').innerText`);
    check('The confirmation names the project and says the files stay', /Remove “Alpha shop”\?/.test(dialogText) && /files stay on your computer/.test(dialogText), dialogText);
    check('The safe choice is the default: Remove from list, Trash unticked, focus on Cancel',
      (await shot.js(`document.querySelector('.cd-dialog-ok').textContent`)) === 'Remove from list' && !(await shot.js(`document.querySelector('.cd-dialog-check input').checked`)) && (await shot.js(`document.activeElement.classList.contains('cd-dialog-cancel')`)));
    await shot.still('coding3p_confirm');
    await shot.click('.cd-dialog-ok');
    await shot.wait(`document.querySelectorAll('.cd-thread-list .cd-thread').length === 2`, { timeout: 10000 });
    await shot.frame(4);
    check('Removed from the list; its folder and files are still there', fs.existsSync(path.join(PROJECTS, 'alpha-shop', 'index.html')) && /files are still in/.test(await toast()), await toast());
    check('Its chat is set aside, not destroyed', fs.readdirSync(path.join(DATA, 'coding_chats', 'removed')).length === 1);

    // move to the Trash: a separate, explicit choice. The sandbox stops the Finder, so it must fail without removing anything.
    await openRemove('Mango');
    await shot.js(`(() => { const c = document.querySelector('.cd-dialog-check input'); c.checked = true; c.dispatchEvent(new Event('change')); })()`);
    await shot.frame(4);
    check('Ticking the Trash box shows the folder and changes the button', (await shot.js(`document.querySelector('.cd-dialog-ok').textContent`)) === 'Remove and move folder to Trash'
      && (await shot.js(`document.querySelector('.cd-dialog-path').textContent`)).endsWith('mango-api'));
    await shot.still('coding3p_trash');
    await shot.click('.cd-dialog-ok');
    await shot.wait(`/Trash/.test(document.querySelector('.cd-toast').textContent)`, { timeout: 15000 });
    check('When the Trash can\'t take it, nothing is removed and it says so', fs.existsSync(path.join(PROJECTS, 'mango-api', 'index.html')) && (await names()).includes('Mango API') && /couldn't move the folder to the Trash/.test(await toast()), await toast());
    const audit = fs.readFileSync(path.join(DATA, 'coding_audit.log'), 'utf8');
    check('The audit log records the removal and the failed Trash', /"action": "remove"/.test(audit) && /"action": "trash_failed"/.test(audit));
    console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
  },
});
