import asyncio
import logging

from playwright.async_api import async_playwright

from .base import BaseScraper
from .browser import is_valid_job, launch_browser, normalize_query

log = logging.getLogger("job-scraper.naukri")


class NaukriScraper(BaseScraper):
    async def scrape(self, queries, location="India", remote=False):
        self.name = "Naukri"
        jobs = []
        errors = []

        try:
            async with async_playwright() as pw:
                browser, context = await launch_browser(pw)
                page = await context.new_page()

                loc_slug = location.lower().replace(" ", "-")

                for query in queries:
                    try:
                        q_slug = normalize_query(query).replace(" ", "-")
                        url = f"https://www.naukri.com/{q_slug}-jobs-in-{loc_slug}"

                        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        await page.wait_for_selector(".srp-jobtuple-wrapper, .cust-job-tuple", timeout=10000)
                        await page.wait_for_timeout(2000)

                        cards = await page.query_selector_all(".srp-jobtuple-wrapper")
                        if not cards:
                            cards = await page.query_selector_all(".cust-job-tuple")

                        for card in cards[:20]:
                            try:
                                title_el = await card.query_selector("a.title, .title, .jdTitle")
                                company_el = await card.query_selector(".comp-name, .compName, a.comp-name")
                                location_el = await card.query_selector(".loc, .locWdth, .loc-wrap")
                                exp_el = await card.query_selector(".exp, .expwdth")
                                desc_el = await card.query_selector(".job-desc, .row4")
                                link_el = title_el or await card.query_selector("a[href*='job-listings']")

                                title = (await title_el.inner_text()).strip() if title_el else ""
                                company = (await company_el.inner_text()).strip() if company_el else ""
                                loc_text = (await location_el.inner_text()).strip() if location_el else location
                                desc = (await desc_el.inner_text()).strip() if desc_el else ""
                                exp_text = (await exp_el.inner_text()).strip() if exp_el else ""
                                if exp_text:
                                    loc_text = f"{loc_text} | {exp_text}" if loc_text else exp_text

                                href = await link_el.get_attribute("href") if link_el else ""
                                if href and "?" in href:
                                    href = href.split("?")[0]

                                if not is_valid_job(title, href):
                                    continue

                                jobs.append(self._make_job(
                                    title=title,
                                    company=company or "Not mentioned",
                                    location=loc_text,
                                    description=desc,
                                    url=href,
                                ))
                            except Exception:
                                continue

                    except Exception as e:
                        errors.append({"portal": "Naukri", "query": query, "error": str(e)})

                    await asyncio.sleep(1.0)

                await browser.close()

        except Exception as e:
            errors.append({"portal": "Naukri", "error": f"Browser error: {e}"})

        return jobs, errors
