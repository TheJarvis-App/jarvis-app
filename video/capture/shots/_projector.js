// Not footage: tests the 3D projector in the real Jarvis window with the real engine.
//  1. Every model builder, from checked specs (projector.sanitize), with its controls exercised: stills of each.
//  2. Real questions through the real engine and the real AI (Groq): which open the projector, which don't, follow-ups,
//     and that the planets and the globe keep their own windows.
//   SPECS=/path/to/proj-specs.json LOOK=next electron video/capture/record.js _projector
const fs = require('fs');
const { desktop, ready, ask } = require('./_lib');
const results = [];
const check = (name, ok, detail = '') => { results.push(!!ok); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  — ' + String(detail).replace(/\s+/g, ' ').slice(0, 260) : ''}`); };

module.exports = desktop({
  size: [1440, 900],
  async run(shot) {
    await ready(shot);
    const open = `!document.getElementById('projLayer').hidden`;
    const q = (js) => shot.js(js);
    const specs = JSON.parse(fs.readFileSync(process.env.SPECS, 'utf8'));
    const errors = [];
    await q(`window.__errs = []; window.addEventListener('error', (e) => window.__errs.push(String(e.message)));`);

    // ---------- 1. every builder ----------
    for (const [key, spec] of Object.entries(specs)) {
      await q(`window.showProjector(${JSON.stringify(spec)})`);
      await shot.frame(75);   // 2.5 s: the scan draws it in and the camera settles
      const info = await q(`({ open: ${open}, title: document.getElementById('projTitle').textContent, chips: [...document.querySelectorAll('#projParts .proj-chip')].map(b => b.textContent),
        labels: [...document.querySelectorAll('.proj-label')].filter(l => !l.hidden).length, loading: !document.getElementById('projLoading').hidden,
        controls: [...document.querySelectorAll('#projControls button')].filter(b => !b.hidden).map(b => b.dataset.act) })`);
      check(`${key}: opens with its parts`, info.open && info.title === spec.title && info.chips.length > 0 && !info.loading, `${info.chips.length} parts, ${info.labels} labels on screen, controls ${info.controls.join(',')}`);
      await shot.still(`proj_${key}`);
      // pick the first part from the list: the words follow it and its chip is pressed
      const first = info.chips[0];
      await q(`document.querySelector('#projParts .proj-chip').click()`);
      await shot.frame(10);
      const picked = await q(`({ name: document.getElementById('projPartName').textContent, text: document.getElementById('projPartText').textContent, pressed: document.querySelector('#projParts .proj-chip').getAttribute('aria-pressed') })`);
      check(`${key}: picking "${first}" explains it`, picked.name === first && picked.text.length > 8 && picked.pressed === 'true', picked.text);
      if (['computer', 'rose', 'engine', 'compare', 'compare_mixed'].includes(key)) await shot.still(`proj_${key}_picked`);
      await q(`document.querySelector('#projParts .proj-chip').click()`);   // and again: back to the answer
      await shot.frame(4);
      // the model-specific controls do something
      if (info.controls.includes('explode')) {
        await q(`document.querySelector('[data-act="explode"]').click()`); await shot.frame(45);
        check(`${key}: exploded view toggles`, (await q(`document.querySelector('[data-act="explode"]').getAttribute('aria-pressed')`)) === (spec.generator === 'computer' ? 'false' : 'true'));
        await shot.still(`proj_${key}_explode_toggled`);
      }
      if (info.controls.includes('cutaway')) {
        await q(`document.querySelector('[data-act="cutaway"]').click()`); await shot.frame(10);
        check(`${key}: inside view toggles`, (await q(`document.querySelector('[data-act="cutaway"]').getAttribute('aria-pressed')`)) === (spec.params.cutaway ? 'false' : 'true'));
        await q(`document.querySelector('[data-act="cutaway"]').click()`); await shot.frame(4);
      }
      if (info.controls.includes('play')) {
        await q(`document.querySelector('[data-act="play"]').click()`); await shot.frame(4);
        check(`${key}: pause works`, (await q(`document.querySelector('[data-act="play"]').textContent`)) === 'Play');
        await q(`document.querySelector('[data-act="play"]').click()`); await shot.frame(4);
      }
    }
    // controls for every model: views, zoom, labels, full screen, keyboard
    await q(`document.querySelector('[data-act="top"]').click()`); await shot.frame(40); await shot.still('proj_view_top');
    await q(`document.querySelector('[data-act="labels"]').click()`); await shot.frame(4);
    check('labels hide', await q(`document.getElementById('projLabels').hidden`));
    await q(`document.querySelector('[data-act="labels"]').click()`);
    await q(`document.querySelector('[data-act="full"]').click()`); await shot.frame(30); await shot.still('proj_fullscreen');
    check('full screen', await q(`document.getElementById('projCard').classList.contains('is-full')`));
    await q(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`); await shot.frame(4);
    check('Esc leaves full screen first', !(await q(`document.getElementById('projCard').classList.contains('is-full')`)) && (await q(open)));
    await q(`window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))`); await shot.frame(4);
    check('Esc then closes it', !(await q(open)));
    await q(`window.reopenProjector('prev')`); await shot.frame(40);
    check('reopens the previous model', await q(open), await q(`document.getElementById('projTitle').textContent`));
    await q(`window.hideProjector()`); await shot.frame(6);
    // (the page's clock only moves when frames are stepped, so compare before and after stepping, not with a timer)
    const before = await q(`document.getElementById('projCanvas').toDataURL().length`);
    await shot.frame(15);
    const loopAfterClose = before === (await q(`document.getElementById('projCanvas').toDataURL().length`));
    check('nothing draws after closing', loopAfterClose);

    // ---------- 2. real questions, the real engine and the real AI ----------
    const asks = [
      ['show me a sunflower', true], ['show me its internal structure', true], ['what\'s inside a computer', true],
      ['how does a car engine work', true], ['what does DNA look like', true], ['show me a carbon atom', true],
      ['explain a black hole', true], ['show me a rose', true], ['explain how pollination works', true],
      ['compare a rose and a sunflower', 'compare'],
      ['show me tv', true], ['show me dog', true], ['show me iron man', true], ['show me spiderman', true], ['show me a house', true], ['show me a shoe', true],
      ['compare a dog and a cat', 'compare'],
      ['what is the capital of France', false], ['tell me about Saturn', 'planet'],
    ];
    for (const [text, expect] of asks) {
      if (!/^(show me its|explain how pollination)/.test(text)) await q(`window.hideProjector?.(); window.hidePlanet?.()`);   // follow-ups keep the projector open, as a person would
      let reply = '';
      try { reply = await ask(shot, text, { filmed: false, timeout: 120000 }); } catch (e) { reply = 'TIMEOUT ' + e.message; }
      await shot.frame(60);
      const s = await q(`({ proj: ${open}, planet: !document.getElementById('planetLayer').hidden, title: document.getElementById('projTitle').textContent, chip0: document.querySelector('#projParts .proj-chip')?.textContent || '', kicker: document.getElementById('projKicker').textContent, parts: document.querySelectorAll('#projParts .proj-chip').length })`);
      const ok = expect === 'planet' ? s.planet && !s.proj : expect === 'compare' ? s.proj && s.kicker === '3D comparison' && s.chip0.includes(': ') : expect ? s.proj && s.parts > 0 : !s.proj;
      check(`asked "${text}"`, ok, `${s.proj ? `projector: ${s.title} (${s.kicker}, ${s.parts} parts)` : s.planet ? 'planet window' : 'words only'} | ${reply.slice(0, 160)}`);
      await shot.still(`proj_ask_${text.replace(/\W+/g, '_').slice(0, 32)}`);
    }
    const errs = await q(`window.__errs`);
    check('no page errors', !errs.length, errs.join(' | '));
    console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
  },
});
