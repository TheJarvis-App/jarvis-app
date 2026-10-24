// Not footage: the top bar with the 3D button.
const { desktop, ready } = require('./_lib');
module.exports = desktop({ size: [1440, 900], async run(shot) { await ready(shot); await shot.frame(90); await shot.still('gal_topbar'); } });
