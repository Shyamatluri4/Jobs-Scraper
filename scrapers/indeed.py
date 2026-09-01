import asyncio
import logging

from playwright.async_api import async_playwright

from .base import BaseScraper, _fetch_description
from .browser import is_valid_job, launch_browser, normalize_query

log = logging.getLogger("job-scraper.indeed")


class IndeedScraper(BaseScraper):
    async def scrape(self, queries, location="India", remote=False):
        self.name = "Indeed"
        jobs = []
        errors = []

        try:
            async with async_playwright() as pw:
                browser, context = await launch_browser(pw)
                page = await context.new_page()

                for query in queries:
                    try:
                        q = normalize_query(query)
                        loc = location.replace(" ", "+")
                        url = f"https://in.indeed.com/jobs?q={q.replace(' ', '+')}&l={loc}&fromage=7&sort=date"
                        if remote:
                            url += "&remotejob=1"

                        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        await page.wait_for_selector("div.job_seen_beacon, h3.jobTitle, a.jcs-JobTitle", timeout=10000)
                        await page.wait_for_timeout(2000)

                        cards = await page.query_selector_all("div.job_seen_beacon")
                        for card in cards[:20]:
                            try:
                                title_el = await card.query_selector(
                                    "a.jcs-JobTitle span[title], a.jcs-JobTitle, h3.jobTitle span, h3.jobTitle a"
                                )
                                company_el = await card.query_selector(
                                    "[data-testid='company-name'], span[data-testid='company-name']"
                                )
                                location_el = await card.query_selector(
                                    "[data-testid='text-location'], div.companyLocation"
                                )
                                link_el = await card.query_selector("a.jcs-JobTitle, h3.jobTitle a")

                                title = ""
                                if title_el:
                                    title = (await title_el.get_attribute("title") or "").strip()
                                    if not title:
                                        title = (await title_el.inner_text()).strip()

                                company = (await company_el.inner_text()).strip() if company_el else ""
                                loc_text = (await location_el.inner_text()).strip() if location_el else location

                                href = await link_el.get_attribute("href") if link_el else ""
                                if href and not href.startswith("http"):
                                    href = f"https://in.indeed.com{href}"

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
                        errors.append({"portal": "Indeed", "query": query, "error": str(e)})

                    await asyncio.sleep(1.0)

                # Fetch descriptions for all collected jobs
                if jobs:
                    await fetch_descriptions_batch(context, jobs, "Indeed")

                await browser.close()

        except Exception as e:
            errors.append({"portal": "Indeed", "error": f"Browser error: {e}"})

        return jobs, errors


async def fetch_descriptions_batch(context, jobs: list[dict], portal: str, concurrency: int = 5):
    """Open job detail pages in parallel and extract descriptions."""
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(job):
        async with sem:
            p = await context.new_page()
            try:
                desc = await _fetch_description(p, job["url"], portal)
                if desc:
                    job["description"] = desc
            except Exception:
                pass
            finally:
                await p.close()

    await asyncio.gather(*[fetch_one(j) for j in jobs])
