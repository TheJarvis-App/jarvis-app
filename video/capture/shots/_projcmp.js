// Not footage: the projector's framing for two models side by side.
const fs = require('fs');
const { desktop, ready } = require('./_lib');
module.exports = desktop({
  size: [1440, 900],
  async run(shot) {
    await ready(shot);
    const specs = JSON.parse(fs.readFileSync(process.env.SPECS, 'utf8'));
    for (const key of ['compare', 'compare_mixed']) {
      await shot.js(`window.showProjector(${JSON.stringify(specs[key])})`); await shot.frame(60); await shot.still(`projc_${key}`);
    }
  },
});
