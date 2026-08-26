const { chromium } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

async function capture() {
  const assetsDir = path.resolve(__dirname, '../../docs/assets');
  if (!fs.existsSync(assetsDir)) {
    fs.mkdirSync(assetsDir, { recursive: true });
  }

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: { width: 1280, height: 820 },
    deviceScaleFactor: 2,
  });

  const themes = [
    { id: 'deep-ocean', filename: 'theme_deep_ocean.png' },
    { id: 'midnight-blue', filename: 'theme_midnight_blue.png' },
    { id: 'lavender-haze', filename: 'theme_lavender_haze.png' },
    { id: 'amber-warmth', filename: 'theme_amber_warmth.png' },
  ];

  console.log('Navigating to http://localhost:5173 ...');
  await page.goto('http://localhost:5173', { waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  for (const theme of themes) {
    console.log(`Capturing screenshot for theme: ${theme.id} ...`);
    await page.evaluate((themeId) => {
      localStorage.setItem('contextcortex_theme', themeId);
      document.documentElement.setAttribute('data-theme', themeId);
    }, theme.id);

    await page.waitForTimeout(600);
    const dest = path.join(assetsDir, theme.filename);
    await page.screenshot({ path: dest, fullPage: false });
    console.log(`Saved ${dest}`);
  }

  console.log('Navigating to Settings tab ...');
  await page.locator('button.nav-tab:has-text("Settings")').click();
  await page.waitForTimeout(600);

  const settingsDest = path.join(assetsDir, 'desktop_settings.png');
  await page.screenshot({ path: settingsDest, fullPage: false });
  console.log(`Saved ${settingsDest}`);

  await browser.close();
  console.log('Screenshot capture complete!');
}

capture().catch((err) => {
  console.error('Error capturing screenshots:', err);
  process.exit(1);
});
