import asyncio
import os
import re
from playwright.async_api import async_playwright

async def debug():
    username = os.getenv('TOPSTEP_USERNAME')
    password = os.getenv('TOPSTEP_PASSWORD')
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1920, 'height': 1080})
        
        await page.goto('https://topstepx.com/login', wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_load_state('networkidle')
        
        inputs = await page.query_selector_all('input')
        for inp in inputs:
            name = await inp.get_attribute('name') or ''
            typ = await inp.get_attribute('type') or ''
            if 'user' in name.lower() or typ == 'email':
                await inp.fill(username)
            elif typ == 'password':
                await inp.fill(password)
        
        btn = await page.query_selector('button:has-text("PLATFORM LOGIN")')
        if btn:
            await btn.click()
        
        await page.wait_for_url('**/trade', timeout=30000)
        await asyncio.sleep(10)
        
        body = await page.inner_text('body')
        
        # Find all @ patterns
        all_matches = re.findall(r'([+-]\d+)\s*@\s*([\d,]+\.?\d*)', body)
        print('All @ matches:', all_matches)
        
        # Check surrounding context for each match
        for m in re.finditer(r'([+-]\d+)\s*@\s*([\d,]+\.?\d*)', body):
            start = max(0, m.start() - 50)
            end = min(len(body), m.end() + 50)
            context = body[start:end]
            print(f'Match {m.group(0)} context: {repr(context)}')
        
        await browser.close()

asyncio.run(debug())
