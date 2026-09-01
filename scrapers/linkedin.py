import asyncio
import logging

from playwright.async_api import async_playwright

from .base import BaseScraper, _fetch_description
from .browser import is_valid_job, launch_browser, normalize_query

log = logging.getLogger("job-scraper.linkedin")

DESC_SEM = asyncio.Semaphore(5)


class LinkedInScraper(BaseScraper):
    def __init__(self):
        super().__init__(timeout=120)

    async def scrape(self, queries, location="India", remote=False):
        self.name = "LinkedIn"
        jobs = []
        errors = []

        try:
            async with async_playwright() as pw:
                browser, context = await launch_browser(pw)
                page = await context.new_page()

                for query in queries:
                    try:
                        q = normalize_query(query)
                        url = (
                            f"https://www.linkedin.com/jobs/search/"
                            f"?keywords={q.replace(' ', '%20')}&location={location.replace(' ', '%20')}"
                            f"&f_TPR=r604800&f_E=2"
                        )
                        if remote:
                            url += "&f_WT=2"

                        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                        await page.wait_for_selector("div.base-card, ul.jobs-search__results-list li", timeout=10000)
                        await page.wait_for_timeout(2000)

                        cards = await page.query_selector_all("div.base-card")
                        if not cards:
                            cards = await page.query_selector_all("ul.jobs-search__results-list li")

                        for card in cards[:15]:
                            try:
                                title_el = await card.query_selector(
                                    "h3.base-search-card__title, .base-search-card__title"
                                )
                                company_el = await card.query_selector(
                                    "h4.base-search-card__subtitle, .base-search-card__subtitle"
                                )
                                location_el = await card.query_selector(
                                    ".job-search-card__location, .base-search-card__metadata span"
                                )
                                link_el = await card.query_selector(
                                    "a.base-card__full-link, a[href*='/jobs/view']"
                                )

                                title = (await title_el.inner_text()).strip() if title_el else ""
                                company = (await company_el.inner_text()).strip() if company_el else ""
                                loc_text = (await location_el.inner_text()).strip() if location_el else location
                                href = await link_el.get_attribute("href") if link_el else ""
                                if href and "?" in href:
                                    href = href.split("?")[0]

                                if not is_valid_job(title, href):
                                    continue

                                jobs.append(self._make_job(
                                    title=title,
                                    company=company or "Not mentioned",
                                    location=loc_text,
                                    description="",
                                    url=href,
                                ))
                            except Exception:
                                continue

                    except Exception as e:
                        errors.append({"portal": "LinkedIn", "query": query, "error": str(e)})

                    await asyncio.sleep(1.0)

                # Fetch descriptions for all jobs by navigating to each URL
                if jobs:
                    await fetch_linkedin_descriptions(context, jobs)

                await browser.close()

        except Exception as e:
            errors.append({"portal": "LinkedIn", "error": f"Browser error: {e}"})

        return jobs, errors


async def fetch_linkedin_descriptions(context, jobs: list[dict]):
    """Open each LinkedIn job URL in new pages and extract descriptions."""

    async def fetch_one(job):
        async with DESC_SEM:
            p = await context.new_page()
            try:
                desc = await _fetch_description(p, job["url"], "LinkedIn")
                if desc:
                    job["description"] = desc
            except Exception:
                pass
            finally:
                await p.close()

    await asyncio.gather(*[fetch_one(j) for j in jobs])
