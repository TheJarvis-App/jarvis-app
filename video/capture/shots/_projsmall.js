// Not footage: the projector's framing for the atom, and its layout in a narrow window.
const fs = require('fs');
const { desktop, ready } = require('./_lib');
module.exports = desktop({
  size: [1440, 900],
  async run(shot) {
    await ready(shot);
    const specs = JSON.parse(fs.readFileSync(process.env.SPECS, 'utf8'));
    await shot.js(`window.showProjector(${JSON.stringify(specs.carbon)})`); await shot.frame(80); await shot.still('projs_carbon_1440');
    await shot.js(`window.showProjector(${JSON.stringify(specs.computer)})`); await shot.frame(80);
    await shot.resize?.(700, 900);
    await shot.js(`document.getElementById('projCard').style.width = '700px'`); await shot.frame(30);
    await shot.still('projs_computer_narrow');
  },
});
