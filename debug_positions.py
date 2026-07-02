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
        
        # Check order card
        card_match = re.search(r'([+-]\d+)\s*@\s*([\d,]+\.?\d*)', body)
        print('Card match:', card_match.group(0) if card_match else 'None')
        
        # Check active symbol from order card
        order_card = await page.query_selector('.ordercard-module__order___uXu3d, .ordercard-module__cardWrapper___vMvQ7, [class*="orderCard"], [data-testid*="order"]')
        if order_card:
            card_text = await order_card.inner_text()
            print('Order card text (first 300 chars):', card_text[:300])
            sym_match = re.search(r'(NQ|ES|YM|RTY|CL|GC)[MFZU]\d{1,2}', card_text)
            print('Symbol from order card:', sym_match.group(0) if sym_match else 'None')
        else:
            print('Order card NOT FOUND')
        
        # Check positions tab
        pos_tab = await page.query_selector('button:has-text("Positions")')
        print('Positions tab found:', bool(pos_tab))
        if pos_tab:
            await pos_tab.click()
            await asyncio.sleep(2)
            rows = await page.query_selector_all('table tbody tr, [class*="position"] tr')
            print('Position rows found:', len(rows))
            for i, row in enumerate(rows[:3]):
                cells = await row.query_selector_all('td')
                texts = [await c.inner_text() for c in cells]
                print(f'Row {i}:', texts)
        
        await browser.close()

asyncio.run(debug())
