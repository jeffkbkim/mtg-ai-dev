// Smoke test of a Playmat build on the test server (test_server.sh, web client via Vite on 4180): signs in, sets the
// AI to the Claude AI (or Claude vs Playmat AI to watch, or the Playmat AI) with the given model and effort, starts a game, keeps and
// passes for about 40 seconds, then exits. The game's recording is the newest folder under ~/playmat-run/test/rec.
//
//   NODE_PATH=$(npm root -g) node engine/playmat/smoke.js claude|watch|mad ["Sonnet 5.5"|"Opus 5.5"] [Low|Medium|High]
const { chromium } = require('playwright');
const mode = process.argv[2] || 'claude';
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
  await p.goto('http://localhost:4180/'); await p.waitForTimeout(3000);
  await p.getByLabel(/name/i).first().fill('tester' + mode.slice(0,3));
  await p.getByRole('button', { name: /sit down/i }).click();
  await p.waitForTimeout(5000);
  await p.getByRole('button', { name: /change/i }).click(); await p.waitForTimeout(1000);
  await p.getByRole('radio', { name: mode === 'watch' ? 'Claude vs Playmat AI' : mode === 'mad' ? 'Playmat AI' : 'Claude AI', exact: true }).click();
  if (mode !== 'mad') {
    await p.getByRole('radio', { name: process.argv[3] || 'Sonnet 5.5' }).click();
    await p.getByRole('radio', { name: process.argv[4] || 'Low' }).click();
  }
  await p.getByRole('button', { name: /^done$/i }).click(); await p.waitForTimeout(800);
  console.log('table', Date.now());
  await p.getByRole('button', { name: /^play$/i }).click();
  for (let i = 0; i < 13; i++) {
    await p.waitForTimeout(3000);
    for (const name of [/draw first/i, /^keep/i]) {
      const btn = p.getByRole('button', { name });
      if (await btn.count() > 0 && await btn.first().isVisible()) { console.log('click', name, Date.now()); await btn.first().click().catch(()=>{}); }
    }
    if (mode !== 'watch') await p.keyboard.press('Space').catch(()=>{});
  }
  await b.close(); process.exit(0);
})();
