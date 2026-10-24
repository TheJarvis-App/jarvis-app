// Not footage: every library model in the real projector, a still of each (and, with THUMBS=1, the gallery pictures
// shipped in projector/thumbs). ONLY=dog,house limits it to some.
const fs = require('fs'), path = require('path');
const { desktop, ready } = require('./_lib');
const slug = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
module.exports = desktop({
  size: [1440, 900],
  async run(shot) {
    await ready(shot);
    const lib = JSON.parse(fs.readFileSync(path.join(__dirname, '../../../projector/library.json'), 'utf8'));
    const only = (process.env.ONLY || '').split(',').filter(Boolean);
    await shot.js(`window.__errs = []; window.addEventListener('error', (e) => window.__errs.push(String(e.message)));`);
    for (const spec of lib.filter((s) => !only.length || only.includes(slug(s.title)))) {
      await shot.js(`window.showProjector(${JSON.stringify(spec)})`);
      await shot.frame(80);
      await shot.still(`lib_${slug(spec.title)}`);
      if (process.env.THUMBS) {
        await shot.js(`window.projectorThumbNext()`); await shot.frame(2);
        const data = await shot.js(`window.__thumb`);
        if (data) fs.writeFileSync(path.join(__dirname, '../../../projector/thumbs', `${slug(spec.title)}.webp`), Buffer.from(data.split(',')[1], 'base64'));
      }
      if (process.env.PICK) { await shot.js(`document.querySelector('#projParts .proj-chip')?.click()`); await shot.frame(8); await shot.still(`lib_${slug(spec.title)}_picked`); await shot.js(`document.querySelector('#projParts .proj-chip')?.click()`); }
    }
    console.log('errors:', JSON.stringify(await shot.js('window.__errs')));
  },
});
