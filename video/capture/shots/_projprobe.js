// Not footage: measures the projector's framing for a few models.
const fs = require('fs');
const { desktop, ready } = require('./_lib');
module.exports = desktop({
  size: [1440, 900],
  async run(shot) {
    await ready(shot);
    const specs = JSON.parse(fs.readFileSync(process.env.SPECS, 'utf8'));
    for (const key of ['rose', 'carbon', 'chair']) {
      await shot.js(`window.showProjector(${JSON.stringify(specs[key])})`);
      await shot.frame(90);
      console.log('PROBE', key, JSON.stringify(await shot.js(`(() => { const d = window.projectorDebug(); const st = document.getElementById('projStage').getBoundingClientRect(); return { ...d, stage: [Math.round(st.width), Math.round(st.height)] }; })()`)));
    }
  },
});
