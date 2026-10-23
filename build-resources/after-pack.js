// After the app is assembled, before the installer is made.
// macOS: Jarvis isn't signed with a paid Apple Developer ID. It's signed with Jarvis's own certificate when the build
// has it (JARVIS_MAC_IDENTITY, set up by the GitHub workflow): every version then has the same signing identity, so
// macOS keeps the permissions people gave Jarvis (Accessibility, microphone) across updates. Without the certificate
// (a local build) it gets an ad-hoc signature, which Apple Silicon needs, but which changes with every build.
// Every platform: the engine must be inside the app. Without it the app only says "spawn ... ENOENT" on every start
// (a build made before `npm run backend`, or after a rename, packs an empty folder without complaint).
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

exports.default = async function afterPack(context) {
  const resources = context.electronPlatformName === 'darwin'
    ? path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`, 'Contents', 'Resources')
    : path.join(context.appOutDir, 'resources');
  const engine = path.join(resources, 'backend', context.electronPlatformName === 'win32' ? 'jarvis-backend.exe' : 'jarvis-backend');
  if (!fs.existsSync(engine)) {
    throw new Error(`Jarvis's engine is missing from the app (${engine}). Run "npm run backend" first.`);
  }
  if (context.electronPlatformName !== 'darwin') return;
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const identity = process.env.JARVIS_MAC_IDENTITY || '-';
  execFileSync('xattr', ['-cr', app]);   // Finder info and download marks on copied files make codesign refuse
  execFileSync('codesign', ['--force', '--deep', '--sign', identity, app], { stdio: 'inherit' });
  execFileSync('codesign', ['--verify', '--deep', '--strict', app], { stdio: 'inherit' });
  const requirement = execFileSync('codesign', ['-d', '-r-', app], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  console.log(`  • signed with ${identity === '-' ? 'an ad-hoc signature' : identity}: ${requirement.trim().split('\n').pop()}`);
  if (identity !== '-' && !/certificate (leaf|root) = H/.test(requirement)) {
    throw new Error('The app was not signed with Jarvis’s certificate, so macOS would drop permissions on update.');
  }
};
