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
        
        # Print snippets containing @ symbol
        for line in body.split('\n'):
            line = line.strip()
            if '@' in line and len(line) < 200:
                print('LINE:', repr(line))
        
        # Try different regex patterns
        patterns = [
            r'([+-]\d+)\s*@\s*([\d,]+\.?\d*)',
            r'@\s*([\d,]+\.?\d*)',
            r'([+-]\d+)\s*@',
        ]
        for pat in patterns:
            m = re.search(pat, body)
            print(f'Pattern {pat}:', m.group(0) if m else 'None')
        
        # Check for flatten button
        flatten = await page.query_selector('button:has-text("FLATTEN ALL")')
        print('Flatten button:', bool(flatten))
        
        # Find all symbol matches in top half vs bottom half
        top = body[:len(body)//2]
        bottom = body[len(body)//2:]
        top_syms = re.findall(r'(NQ|ES|YM|RTY|CL|GC)[MFZU]\d{1,2}', top)
        bottom_syms = re.findall(r'(NQ|ES|YM|RTY|CL|GC)[MFZU]\d{1,2}', bottom)
        print('Symbols in top half:', top_syms)
        print('Symbols in bottom half:', bottom_syms)
        
        await browser.close()

asyncio.run(debug())
