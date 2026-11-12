import asyncio
from playwright.async_api import async_playwright
import urllib.parse
import re

async def test_gmaps_scrape(query: str = "jogos de tabuleiro ribeirao preto"):
    print(f"[*] Iniciando extração no Google Maps para: '{query}'...")
    encoded = urllib.parse.quote(query)
    url = f"https://www.google.com/maps/search/{encoded}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="pt-BR",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("div[role='feed'], div.m6QErb", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Trata consentimento do Google se existir
        for btn_text in ["Aceitar tudo", "Concordo", "I agree", "Aceito"]:
            try:
                btn = page.locator(f"button:has-text('{btn_text}')")
                if await btn.count() > 0:
                    await btn.first.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

        # Rola o feed de resultados
        feed = page.locator("div[role='feed']")
        if await feed.count() > 0:
            print("[i] Painel de resultados encontrado. Rolando para carregar mais lojas...")
            for _ in range(3):
                await feed.evaluate("el => el.scrollBy(0, 1000)")
                await asyncio.sleep(1.5)

        # Encontra os cards de lojas
        # Geralmente os itens no feed têm links com /maps/place/
        cards = page.locator("div[role='feed'] > div > div > a[href*='/maps/place/']")
        count = await cards.count()
        print(f"[+] Encontrados {count} estabelecimentos no mapa!")

        results = []
        for i in range(min(count, 15)):
            card = cards.nth(i)
            name = await card.get_attribute("aria-label") or "Loja"
            href = await card.get_attribute("href") or ""
            
            # Tenta pegar website do botão de ação ou container pai
            parent = card.locator("..")
            website = ""
            website_btn = parent.locator("a[data-value='Website'], a[aria-label*='site'], a[href^='http']:not([href*='google'])")
            if await website_btn.count() > 0:
                website = await website_btn.first.get_attribute("href") or ""

            results.append({
                "name": name,
                "maps_url": href,
                "website": website
            })
            print(f"  {i+1}. {name} | Site: {website or 'Sem site direto'}")

        await browser.close()
        return results

if __name__ == "__main__":
    asyncio.run(test_gmaps_scrape("jogos rpg ribeirao preto"))
