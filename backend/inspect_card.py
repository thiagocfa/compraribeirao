import asyncio
from playwright.async_api import async_playwright
import urllib.parse

async def inspect():
    url = "https://www.google.com/maps/search/" + urllib.parse.quote("Deckmaster Games ribeirao preto")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale="pt-BR")
        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(4)
        
        authority = page.locator("a[data-item-id='authority']")
        phone = page.locator("button[data-item-id*='phone']")
        address = page.locator("button[data-item-id='address']")
        
        website = await authority.first.get_attribute("href") if await authority.count() > 0 else ""
        tel = await phone.first.inner_text() if await phone.count() > 0 else ""
        addr = await address.first.inner_text() if await address.count() > 0 else ""
        
        print("=== DECKMASTER GAMES DETALHES ===")
        print("Website:", website)
        print("Telefone:", tel)
        print("Endereço:", addr)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(inspect())
