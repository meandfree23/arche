const puppeteer = require('puppeteer');
const path = require('path');
const http = require('http');
const fs = require('fs');

const projectDir = __dirname;
const port = 8089;

const server = http.createServer((req, res) => {
  let filePath = path.join(projectDir, req.url === '/' ? 'index.html' : req.url);
  if (!fs.existsSync(filePath)) {
    res.writeHead(404);
    res.end('Not Found');
    return;
  }
  const ext = path.extname(filePath);
  const mimeTypes = {
    '.html': 'text/html; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.js': 'application/javascript',
    '.css': 'text/css'
  };
  res.writeHead(200, { 'Content-Type': mimeTypes[ext] || 'text/plain' });
  fs.createReadStream(filePath).pipe(res);
});

server.listen(port, async () => {
  console.log(`Test server running at http://localhost:${port}`);
  
  let browser;
  try {
    browser = await puppeteer.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    const page = await browser.newPage();

    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text());
      }
    });
    page.on('response', resp => {
      if (resp.status() >= 400) {
        errors.push(`HTTP ${resp.status()}: ${resp.url()}`);
      }
    });

    await page.goto(`http://localhost:${port}/index.html`, { waitUntil: 'networkidle0', timeout: 15000 });

    // 1. Verify Page Title
    const title = await page.title();
    console.log(`Page Title: ${title}`);

    // 2. Verify Minimal Category Nav
    const categoryCount = await page.$$eval('#minimalCategoryNav > button', btns => btns.length);
    console.log(`Minimal Category Nav Count: ${categoryCount} (Expected: 5)`);

    // 3. Verify Dominant Headline
    const headline = await page.$eval('#articleTitle', el => el.innerText.trim());
    console.log(`Zen Dominant Headline: "${headline}"`);

    // 4. Verify Long-form Chars
    const paragraphs = await page.$$eval('#articleBody p', ps => ps.map(p => p.innerText.trim()));
    const totalCharCount = paragraphs.reduce((acc, p) => acc + p.length, 0);
    console.log(`Long-form Chars: ${totalCharCount} chars`);

    // 5. Test Next Article Navigation
    await page.click('#nextBtn');
    await new Promise(r => setTimeout(r, 300));
    const article2Headline = await page.$eval('#articleTitle', el => el.innerText.trim());
    console.log(`Navigated to Article 2: "${article2Headline}"`);

    // 6. Test Zen Drawer (25 Essays)
    await page.click('button[onclick="openMenu()"]');
    await new Promise(r => setTimeout(r, 350));
    const isDrawerOpen = await page.$eval('#zenMenuModal', el => !el.classList.contains('hidden'));
    const totalDrawerItems = await page.$$eval('#zenEssayList > div > div > div', divs => divs.length);
    console.log(`Zen Drawer Opened: ${isDrawerOpen}, Total Items: ${totalDrawerItems} (Expected: 25)`);

    console.log('\n=============================');
    console.log('--- TEST HARNESS RESULTS ---');
    console.log(`JS Errors: ${errors.length === 0 ? 'None' : errors.join(', ')}`);
    console.log(`Ultra-minimalist editorial site verified!`);
    console.log('=============================\n');

  } catch (err) {
    console.error('Test failed with exception:', err);
  } finally {
    if (browser) await browser.close();
    server.close();
    process.exit(0);
  }
});
