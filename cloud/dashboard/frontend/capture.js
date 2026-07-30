import { chromium } from 'playwright';

(async () => {
    const browser = await chromium.launch();
    const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
    await page.goto('http://127.0.0.1:8000/static/vite/index.html');
    await page.waitForTimeout(1000);
    const selects = await page.$$('select');
    if (selects.length >= 2) {
        const options = await selects[1].$$('option');
        if (options.length > 1) {
            const val = await options[1].getAttribute('value');
            await selects[1].selectOption(val);
            await page.waitForTimeout(2000);
        }
    }
    await page.screenshot({ path: 'C:/Users/kahyuen/.gemini/antigravity/brain/a9d4dbfe-bc4f-4726-abe2-00c0bace2a23/loaded_map_preview.png' });
    await browser.close();
    console.log('Loaded map screenshot captured successfully!');
})();
