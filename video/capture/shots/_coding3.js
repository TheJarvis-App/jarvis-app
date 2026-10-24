// Not footage: drives the new Coding Mode workspace through the real window and the real engine with the real AI
// (Groq), checks what it shows against the files on disk, and takes stills at several window sizes.
// The demo engine is sandboxed (backend.py): programs are not really started and outside tools are stand-ins, so
// this proves the window, the chat, the wiring and the AI's real work; running generated code is tested outside.
//   LOOK=next electron video/capture/record.js _coding3
const fs = require('fs');
const path = require('path');
const { desktop, ready } = require('./_lib');
const results = [];
const check = (name, ok, detail = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + String(detail).replace(/\s+/g, ' ').slice(0, 300) : ''}`); };
const PROJECTS = path.join(__dirname, '..', '..', 'cache.nosync', 'data', 'projects');
const listFiles = (dir) => fs.readdirSync(dir, { recursive: true }).map(String).filter((p) => fs.statSync(path.join(dir, p)).isFile()).sort();

module.exports = desktop({
  size: [1440, 900],
  async run(shot) {
    const text = (sel) => shot.js(`(document.querySelector(${JSON.stringify(sel)})?.textContent || '').trim()`);
    const idle = `document.querySelector('.cd-stop').hidden && !document.querySelector('.cd-composer').classList.contains('busy')`;
    const lastJarvis = `[...document.querySelectorAll('.cd-msg.cd-jarvis')].pop()`;
    const sendText = async (t) => {
      await shot.js(`(() => { const i = document.querySelector('.cd-compose textarea'); i.value = ${JSON.stringify(t)}; i.dispatchEvent(new Event('input', { bubbles: true })); })()`);
      await shot.frame(3);
      await shot.js(`document.querySelector('.cd-composer').requestSubmit()`);
    };
    const resize = async (w, h) => {
      await shot.wc.debugger.sendCommand('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
      await shot.js(`window.dispatchEvent(new Event('resize'))`);
      await shot.frame(12);
    };
    const overflow = () => shot.js(`(() => { const out = []; for (const n of document.querySelectorAll('.cd-layer *')) { const r = n.getBoundingClientRect();
      if (r.width && (r.right > innerWidth + 1 || r.left < -1) && !n.closest('.cd-inspect, .cd-side') && getComputedStyle(n).position !== 'fixed') out.push(n.getAttribute('class') || n.tagName); } return out.slice(0, 5); })()`);
    await ready(shot);

    // open it
    await shot.click('#codeBtn');
    await shot.wait('window.codingOpen()', { timeout: 10000 });
    await shot.wait(`/gpt-oss/.test(document.querySelector('.cd-compose-model').textContent)`, { timeout: 15000 });
    await shot.frame(20);
    check('The top-bar button opens the workspace with one composer and no pickers', await shot.js(`document.querySelectorAll('.cd-layer select').length === 0 && !!document.querySelector('.cd-compose textarea')`));
    check('The empty chat teaches: heading and five ideas', (await text('.cd-hello h3')) === 'What should we build?' && (await shot.js(`document.querySelectorAll('.cd-idea').length`)) === 5);
    check('Model shown truthfully, in the composer', /gpt-oss-120b/.test(await text('.cd-compose-model')), await text('.cd-compose-model'));
    await shot.still('coding3_1_empty_1440');

    // a real website from one message
    await sendText('Build me a modern website about racing: a hero section, the teams, a race calendar and a contact form. Dark, responsive, with subtle animations.');
    await shot.wait(`document.querySelector('.cd-msg.cd-user') && document.querySelector('.cd-work')`, { timeout: 60000 });
    check('The message appears in the chat, and a live work card follows', (await text('.cd-msg.cd-user .cd-bubble')).startsWith('Build me a modern website'));
    await shot.wait(`document.querySelectorAll('.cd-work-file').length > 0`, { timeout: 240000 });
    await shot.frame(10);
    check('While working: Stop replaces Send and the header says Building', await shot.js(`!document.querySelector('.cd-stop').hidden && document.querySelector('.cd-send').hidden`) && /Building/.test(await text('.cd-state')), await text('.cd-state'));
    await shot.still('coding3_2_working_1440');
    await shot.wait(`${idle} && document.querySelector('.cd-work')?.dataset.phase === 'done'`, { timeout: 480000 });
    await shot.wait(`document.querySelector('.cd-msg[data-kind="result"]')`, { timeout: 30000 });
    await shot.frame(20);
    const folder = path.join(PROJECTS, fs.readdirSync(PROJECTS)[0]);
    const onDisk = listFiles(folder);
    check('A website, not Python: HTML, CSS and JS files exist on disk', onDisk.some((f) => f.endsWith('.html')) && onDisk.some((f) => f.endsWith('.css')) && !onDisk.some((f) => f.endsWith('.py')), onDisk.join(', '));
    const treeFiles = await shot.js(`[...document.querySelectorAll('.cd-tree .cd-row:not([aria-expanded]) .cd-row-name')].length`);
    const shownCount = Number(await text('.cd-tab-count'));
    check('The explorer shows every real file', shownCount === onDisk.length, `${shownCount} shown / ${onDisk.length} on disk (top-level rows ${treeFiles})`);
    check('New files are marked', (await shot.js(`document.querySelectorAll('.cd-mark-dot[data-mark="new"]').length`)) > 0);
    check('The header names the project and its stack', (await text('.cd-title')) === path.basename(folder) && /Website/.test(await text('.cd-stack')), `${await text('.cd-title')} · ${await text('.cd-stack')}`);
    const result = await shot.js(`document.querySelector('.cd-msg[data-kind="result"]').innerText`);
    check('Jarvis says what was written, what was checked, and that it did not run it', /I wrote/.test(result) && /haven't run it/.test(result), result);
    await shot.still('coding3_3_built_1440');

    // a file, from the explorer
    await shot.js(`document.querySelector('[data-tab="files"]').click(); [...document.querySelectorAll('.cd-tree .cd-row-main')].find((b) => /\\.html$/.test(b.querySelector('.cd-row-name').textContent)).click()`);
    await shot.wait(`document.querySelector('.cd-code')`, { timeout: 10000 });
    await shot.frame(8);
    const viewed = await text('.cd-viewer-path');
    const shownText = await shot.js(`[...document.querySelectorAll('.cd-code .cd-ln')].map((l) => l.textContent).join('\\n')`);
    check('The file shown is the file on disk, with syntax colours', shownText.trim() === fs.readFileSync(path.join(folder, viewed), 'utf8').trim() && (await shot.js(`document.querySelectorAll('.cd-code .t-t').length`)) > 0, viewed);
    await shot.still('coding3_4_file_1440');
    await shot.click('.cd-viewer-back');

    // how to run
    await shot.js(`document.querySelector('[data-tab="run"]').click()`);
    await shot.frame(10);
    const steps = await shot.js(`[...document.querySelectorAll('.cd-steps li')].map((l) => l.innerText).join(' | ')`);
    check('How to run matches the project: open index.html in a browser', /index\.html/.test(steps) && /browser/i.test(steps), steps);
    check('It separates what was checked from what was not', /Checked/.test(await text('.cd-verified')) && /hasn’t run the program/.test(await text('.cd-verified')));
    await shot.still('coding3_5_run_1440');

    // a follow-up changes the same project
    await sendText('Add a lap-time leaderboard section that sorts the drivers by their best time');
    await shot.wait(`document.querySelectorAll('.cd-work').length === 2`, { timeout: 60000 });
    await shot.wait(`${idle} && [...document.querySelectorAll('.cd-work')].pop().dataset.phase !== 'planning' && [...document.querySelectorAll('.cd-work')].pop().dataset.phase !== 'writing' && [...document.querySelectorAll('.cd-work')].pop().dataset.phase !== 'checking'`, { timeout: 480000 });
    await shot.frame(20);
    check('Still one project folder', fs.readdirSync(PROJECTS).length === 1, fs.readdirSync(PROJECTS).join(', '));
    const phase2 = await shot.js(`[...document.querySelectorAll('.cd-work')].pop().dataset.phase`);
    check('The change finished', phase2 === 'done', `${phase2}: ${await shot.js(`${lastJarvis}.innerText`)}`);
    check('Changed files are marked in the explorer', (await shot.js(`document.querySelectorAll('.cd-mark-dot[data-mark="changed"]').length`)) > 0);
    await shot.js(`document.querySelector('[data-tab="files"]').click()`);
    const changedRow = await shot.js(`(() => { const d = document.querySelector('.cd-row:not([aria-expanded]) .cd-mark-dot[data-mark="changed"]'); return d ? d.closest('.cd-row').querySelector('.cd-row-name').textContent : ''; })()`);
    if (changedRow) {
      await shot.js(`document.querySelector('.cd-row:not([aria-expanded]) .cd-mark-dot[data-mark="changed"]').closest('.cd-row').querySelector('.cd-row-main').click()`);
      await shot.wait(`document.querySelector('.cd-diff, .cd-code')`, { timeout: 10000 });
      await shot.frame(6);
      check('A changed file opens on its changes', await shot.js(`!!document.querySelector('.cd-diff .cd-d-add')`), changedRow);
      await shot.still('coding3_6_diff_1440');
      await shot.click('.cd-viewer-back');
    }

    // a question is answered, nothing is changed
    const before = listFiles(folder).map((f) => f + fs.statSync(path.join(folder, f)).mtimeMs).join();
    await sendText('How do I open this website on my computer?');
    await shot.wait(`${idle} && ${lastJarvis}?.dataset.kind === 'text'`, { timeout: 180000 });
    await shot.frame(10);
    check('A question gets an answer, and no file changes', listFiles(folder).map((f) => f + fs.statSync(path.join(folder, f)).mtimeMs).join() === before, await shot.js(`${lastJarvis}.innerText`));
    await shot.still('coding3_7_answer_1440');

    check('Code inside a list item is drawn as a code block, never as raw backticks', !(await shot.js(`[...document.querySelectorAll('.cd-say')].some((n) => n.textContent.includes('\\x60\\x60\\x60'))`)));

    // run it: asks first
    await shot.click('.cd-run');
    await shot.wait(`${lastJarvis}?.dataset.kind === 'confirm'`, { timeout: 20000 });
    await shot.frame(8);
    check('Run asks first, naming the file', /index\.html/.test(await shot.js(`${lastJarvis}.innerText`)));
    await shot.still('coding3_8_confirm_1440');
    await shot.js(`[...document.querySelectorAll('.cd-msg[data-kind="confirm"] .cd-btn')].find((b) => /Start it/.test(b.textContent)).click()`);
    await shot.wait(`${lastJarvis}?.dataset.kind === 'text' && /browser/.test(${lastJarvis}.innerText)`, { timeout: 20000 });
    check('Yes starts it (here: the browser open is recorded by the sandbox)', /Opened .*index\.html in your browser/.test(await shot.js(`${lastJarvis}.innerText`)), await shot.js(`${lastJarvis}.innerText`));

    // the explorer's own file operations, on the real folder
    await shot.js(`document.querySelector('[data-fs="newfile"]').click()`);
    await shot.wait(`document.querySelector('.cd-row-input input')`);
    await shot.js(`(() => { const i = document.querySelector('.cd-row-input input'); i.value = 'notes/todo.md'; i.closest('form').requestSubmit(); })()`);
    await shot.wait(`[...document.querySelectorAll('.cd-row-name')].some((n) => n.textContent === 'todo.md') || [...document.querySelectorAll('.cd-row-name')].some((n) => n.textContent === 'notes')`, { timeout: 10000 });
    check('New file: created on disk and shown', fs.existsSync(path.join(folder, 'notes', 'todo.md')));
    await shot.js(`(() => { const r = [...document.querySelectorAll('.cd-row')].find((x) => x.querySelector('.cd-row-name')?.textContent === 'notes'); if (r && r.getAttribute('aria-expanded') === 'false') r.querySelector('.cd-row-main').click(); })()`);
    await shot.frame(4);
    await shot.js(`[...document.querySelectorAll('.cd-row')].find((x) => x.querySelector('.cd-row-name')?.textContent === 'todo.md').querySelector('[aria-label^="Delete"]').click()`);
    await shot.wait(`document.querySelector('.cd-row-confirm')`);
    await shot.still('coding3_9_delete_confirm_1440');
    await shot.js(`document.querySelector('.cd-row-confirm .danger').click()`);
    await shot.wait(`![...document.querySelectorAll('.cd-row-name')].some((n) => n.textContent === 'todo.md')`, { timeout: 10000 });
    check('Delete asks inline, then removes the real file', !fs.existsSync(path.join(folder, 'notes', 'todo.md')));

    // Stop
    await sendText('Add a gallery page with six photos of race cars');
    await shot.wait(`!document.querySelector('.cd-stop').hidden`, { timeout: 20000 });
    await shot.frame(30);
    await shot.click('.cd-stop');
    await shot.wait(`${idle}`, { timeout: 240000 });
    await shot.wait(`${lastJarvis}?.dataset.kind === 'result' || ${lastJarvis}?.dataset.kind === 'text' || ${lastJarvis}?.dataset.kind === 'error'`, { timeout: 30000 });
    const stopped = await shot.js(`${lastJarvis}.innerText`);
    check('Stop ends the work and says so', /Stopped/.test(stopped), stopped);

    // a new project, and back
    await shot.click('.cd-new');
    await shot.wait(`document.querySelector('.cd-hello')`, { timeout: 10000 });
    check('New project: an empty chat; the old one is in the sidebar', (await shot.js(`document.querySelectorAll('.cd-thread').length`)) >= 1);
    await shot.js(`document.querySelector('.cd-thread').click()`);
    await shot.wait(`document.querySelectorAll('.cd-work').length >= 2`, { timeout: 10000 });
    check('Reopening the project restores its whole conversation', (await shot.js(`document.querySelectorAll('.cd-msg.cd-user').length`)) >= 4);
    await shot.frame(10);

    // window sizes
    for (const [w, h] of [[1280, 800], [1024, 720], [760, 820], [420, 860]]) {
      await resize(w, h);
      const spill = await overflow();
      check(`No content spills out at ${w}×${h}`, !spill.length, spill.join(', '));
      await shot.still(`coding3_size_${w}`);
    }
    await resize(1024, 720);
    check('Narrowing the window closes the project panel, so it never covers the chat', await shot.js(`document.querySelector('.cd-app').dataset.panel === 'closed'`));
    await shot.click('.cd-panel-toggle');
    await shot.frame(12);
    check('At 1024 the project panel opens as a drawer over the chat', await shot.js(`getComputedStyle(document.querySelector('.cd-inspect')).position === 'absolute' && document.querySelector('.cd-app').dataset.panel === 'open'`));
    await shot.still('coding3_size_1024_drawer');
    await resize(420, 860);
    await shot.click('.cd-side-toggle');
    await shot.frame(12);
    check('At phone width the projects slide in as a drawer', await shot.js(`document.querySelector('.cd-app').dataset.drawer === 'side'`));
    await shot.still('coding3_size_420_side');

    const passed = results.filter(Boolean).length;
    console.log(`\n${passed}/${results.length} checks passed`);
  },
});
