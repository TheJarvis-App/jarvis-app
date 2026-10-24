// Not footage: the Coding Mode workspace's layout at several window sizes, drawn from a sample chat handed to the
// window the way the engine hands it one (no AI). Checks that nothing spills out of the window, and takes stills.
//   LOOK=next electron video/capture/record.js _coding3s
const { desktop, ready } = require('./_lib');
const results = [];
const check = (name, ok, detail = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + detail : ''}`); };
const now = Date.now() / 1000;
const SAMPLE = {   // sample content, for the layout only
  thread: { id: 'sample', title: 'A racing website', path: '/tmp/racing-website', messages: [
    { id: 'u1', role: 'user', kind: 'text', text: 'Build me a modern website about racing: a hero section, the teams, a race calendar and a contact form.', at: now - 600 },
    { id: 'w-1', role: 'jarvis', kind: 'work', at: now - 590, job: { id: '1', action: 'create', phase: 'done', name: 'racing-website', language: 'HTML/CSS/JavaScript',
      files: [{ path: 'index.html', status: 'written', lines: 118 }, { path: 'styles/main.css', status: 'written', lines: 286 }, { path: 'scripts/main.js', status: 'written', lines: 55 }],
      checks: { ok: 3, failed: 0, skipped: 0 }, summary: 'A dark, responsive racing site with a hero, teams, calendar and contact form.' } },
    { id: 'r1', role: 'jarvis', kind: 'result', phase: 'done', at: now - 580, text: "I wrote racing-website: 3 files. 3 syntax checks passed. I haven't run it. It's in /Users/someone/Documents/Jarvis Projects/racing-website." },
    { id: 'u2', role: 'user', kind: 'text', text: 'How do I open it?', at: now - 300 },
    { id: 'a2', role: 'jarvis', kind: 'text', at: now - 290, text: 'Open it in your browser:\n\n1. Open the folder:\n   ```bash\n   cd "/Users/someone/Documents/Jarvis Projects/racing-website"\n   ```\n2. Double-click **index.html**.\n\n- No server is needed.\n- Everything works offline.' },
    { id: 'c1', role: 'jarvis', kind: 'confirm', ask: 'run', answer: '', at: now - 200, text: 'Open **index.html** in your browser? Its scripts run there, like any web page.' },
  ] },
  project: { id: 'p', name: 'racing-website', path: '/tmp/racing-website', language: 'HTML/CSS/JavaScript', phase: 'done', checks: [{ file: 'index.html', tool: 'Linked files', status: 'ok', output: '' }],
    tree: [{ path: 'index.html', mark: 'new' }, { path: 'styles/main.css', mark: 'new' }, { path: 'scripts/main.js', mark: 'changed' }, { path: 'README.md', mark: '' }],
    guide: { kind: 'web', stack: 'Website (HTML, CSS, JavaScript)', known: true, requirements: [{ name: 'A web browser', why: 'Nothing else to install.', installed: null }],
      steps: [{ text: 'Open the project folder and double-click **index.html**.' }, { text: 'Or serve it locally.', command: 'python3 -m http.server 8000', where: 'In Terminal, in the project folder.' }], expect: 'The site appears in your browser.', stop: 'Close the tab.', problems: [],
      launch: { type: 'browser', path: '/tmp/racing-website/index.html' } } },
  busy: false,
};

module.exports = desktop({
  size: [1440, 900],
  async run(shot) {
    const resize = async (w, h) => {
      await shot.wc.debugger.sendCommand('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: 1, mobile: false });
      await shot.js(`window.dispatchEvent(new Event('resize'))`);
      await shot.frame(12);
    };
    const spill = () => shot.js(`(() => { const out = []; for (const n of document.querySelectorAll('.cd-layer *')) { const r = n.getBoundingClientRect();
      if (r.width && (r.right > innerWidth + 1 || r.left < -1) && !n.closest('.cd-inspect, .cd-side, pre, .cd-cmd') && getComputedStyle(n).position !== 'fixed') out.push(n.getAttribute('class') || n.tagName); } return out.slice(0, 6); })()`);
    await ready(shot);
    await shot.click('#codeBtn');
    await shot.wait('window.codingOpen()', { timeout: 10000 });
    await shot.still('coding3s_empty');
    const send = (m) => shot.js(`window.dispatchEvent(new CustomEvent('jarvis-message', { detail: ${JSON.stringify(m)} }))`);
    await send({ type: 'coding_thread', data: { ...SAMPLE, project: null, busy: true } });   // a build in progress, then done, as the engine reports it
    await send({ type: 'coding', thread: 'sample', data: { id: '1', action: 'create', phase: 'done', name: 'racing-website', files: [], checks: [] } });
    await send({ type: 'coding_thread', data: SAMPLE });
    await shot.frame(20);
    check('When a build finishes, How to run opens by itself', await shot.js(`document.querySelector('[data-tab="run"]').getAttribute('aria-selected') === 'true'`));
    await shot.still('coding3s_run_1440');
    check('The list item with code shows a code block, not backticks', await shot.js(`!!document.querySelector('.cd-say li .cd-codeblock') && ![...document.querySelectorAll('.cd-say')].some((n) => n.textContent.includes('\\x60\\x60\\x60'))`));
    await shot.js(`document.querySelector('[data-tab="run"]').click()`);
    await shot.frame(6);
    await shot.js(`document.querySelector('.cd-cmd .cd-copy').click()`);
    await shot.frame(6);
    const copied = require('child_process').execFileSync('pbpaste', { encoding: 'utf8' });   // the computer's real clipboard
    check('A command copy button puts exactly that command on the clipboard', copied === 'python3 -m http.server 8000', copied);
    check('…and shows it was copied', await shot.js(`document.querySelector('.cd-cmd .cd-copy').classList.contains('done')`));
    await shot.js(`document.querySelector('[data-tab="files"]').click()`);
    for (const [w, h] of [[1440, 900], [1024, 720], [760, 820], [420, 860], [360, 740]]) {
      await resize(w, h);
      const out = await spill();
      check(`Nothing spills out at ${w}×${h}`, !out.length, out.join(', '));
      check(`Header actions are all on screen at ${w}`, await shot.js(`[...document.querySelectorAll('.cd-top-actions > button, .cd-menu-wrap > button')].filter((b) => b.offsetParent).every((b) => b.getBoundingClientRect().right <= innerWidth)`));
      await shot.still(`coding3s_${w}`);
    }
    console.log(`\n${results.filter(Boolean).length}/${results.length} checks passed`);
  },
});
