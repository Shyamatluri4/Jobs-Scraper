from __future__ import annotations

import asyncio
import json
import logging
import re

from playwright.async_api import async_playwright

from .base import BaseScraper, _fetch_description
from .browser import is_valid_job, launch_browser, normalize_query

log = logging.getLogger("job-scraper.wellfound")

WELLFOUND_URLS = [
    "https://wellfound.com/jobs?remote=true",
    "https://wellfound.com/jobs?location=India",
    "https://wellfound.com/jobs",
]

DESC_SEM = asyncio.Semaphore(5)


class WellfoundScraper(BaseScraper):
    def __init__(self):
        super().__init__(timeout=120)

    async def scrape(self, queries, location="India", remote=False):
        self.name = "Wellfound"
        jobs = []
        errors = []
        seen_urls = set()

        try:
            async with async_playwright() as pw:
                browser, context = await launch_browser(pw)
                page = await context.new_page()

                for query in queries:
                    if len(jobs) >= 20:
                        break

                    query_terms = set(normalize_query(query).lower().split())
                    query_jobs = await self._scrape_direct(page, query_terms, seen_urls)
                    if not query_jobs:
                        query_jobs = await self._scrape_via_google(
                            page, query, location, remote, query_terms, seen_urls
                        )

                    if query_jobs:
                        jobs.extend(query_jobs)
                    else:
                        errors.append({
                            "portal": "Wellfound",
                            "query": query,
                            "error": "No listings found via Wellfound or Google fallback",
                        })

                    await asyncio.sleep(1.0)

                # Fetch descriptions for jobs missing them
                missing_desc = [j for j in jobs if not j.get("description")]
                if missing_desc:
                    await fetch_wellfound_descriptions(context, missing_desc)

                await browser.close()

        except Exception as e:
            errors.append({"portal": "Wellfound", "error": f"Browser error: {e}"})

        return jobs[:50], errors

    async def _scrape_direct(self, page, query_terms: set[str], seen_urls: set) -> list[dict]:
        for base_url in WELLFOUND_URLS:
            try:
                await page.goto(base_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(5000)

                jobs = await self._extract_from_dom(page, query_terms, seen_urls)
                if not jobs:
                    content = await page.content()
                    jobs = self._extract_from_html(content, query_terms, seen_urls)
                if jobs:
                    return jobs
            except Exception:
                continue
        return []

    async def _scrape_via_google(
        self, page, query: str, location: str, remote: bool, query_terms: set[str], seen_urls: set
    ) -> list[dict]:
        q = normalize_query(query)
        search = f"site:wellfound.com/jobs {q}"
        if remote:
            search += " remote"
        if location:
            search += f" {location}"

        url = f"https://www.google.com/search?q={search.replace(' ', '+')}&num=20"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
            content = await page.content()
        except Exception as exc:
            log.warning("Google fallback failed for Wellfound: %s", exc)
            return []

        return self._extract_from_google_html(content, query_terms, seen_urls)

    async def _extract_from_dom(self, page, query_terms: set[str], seen_urls: set) -> list[dict]:
        jobs = []
        links = await page.query_selector_all("a[href*='/jobs/']")

        for link in links:
            if len(jobs) >= 20:
                break
            try:
                href = await link.get_attribute("href") or ""
                if not href or href in seen_urls:
                    continue

                text = (await link.inner_text()).strip()
                if len(text) < 5:
                    continue

                lines = [line.strip() for line in text.split("\n") if line.strip()]
                title = lines[0]
                company = lines[1] if len(lines) > 1 else "Not mentioned"

                if query_terms and not any(term in title.lower() for term in query_terms):
                    continue

                if not href.startswith("http"):
                    href = f"https://wellfound.com{href}"

                if not is_valid_job(title, href):
                    continue

                seen_urls.add(href)
                jobs.append(self._make_job(
                    title=title,
                    company=company,
                    location="Remote",
                    description="",
                    url=href.split("#")[0],
                ))
            except Exception:
                continue

        # Enrich descriptions from inline JSON data
        if jobs:
            try:
                contents = await page.content()
                enrich_from_json(contents, jobs)
            except Exception:
                pass

        return jobs

    def _extract_from_html(self, content: str, query_terms: set[str], seen_urls: set) -> list[dict]:
        jobs = []
        titles = re.findall(r'"title"\s*:\s*"([^"]{5,120})"', content)
        companies = re.findall(r'"(?:startupName|companyName)"\s*:\s*"([^"]+)"', content)
        urls = re.findall(r'"(?:absolute_url|jobUrl)"\s*:\s*"([^"]+)"', content)

        for i, title in enumerate(titles):
            if len(jobs) >= 20:
                break
            if query_terms and not any(term in title.lower() for term in query_terms):
                continue

            company = companies[i] if i < len(companies) else "Not mentioned"
            href = urls[i] if i < len(urls) else ""
            if href and not href.startswith("http"):
                href = f"https://wellfound.com{href}"

            if href in seen_urls or not is_valid_job(title, href):
                continue

            seen_urls.add(href)
            jobs.append(self._make_job(
                title=title,
                company=company,
                location="Remote",
                description="",
                url=href.split("#")[0],
            ))

        if jobs:
            enrich_from_json(content, jobs)

        return jobs

    def _extract_from_google_html(self, content: str, query_terms: set[str], seen_urls: set) -> list[dict]:
        jobs = []
        urls = re.findall(r"https://wellfound\.com/jobs/\d+-[a-z0-9-]+", content)
        unique_urls = list(dict.fromkeys(urls))

        for href in unique_urls:
            if len(jobs) >= 20:
                break
            if href in seen_urls:
                continue

            title, company = self._parse_wellfound_slug(href)
            if query_terms and not any(term in title.lower() for term in query_terms):
                continue

            clean_url = href.split("#")[0]
            if not is_valid_job(title, clean_url):
                continue

            seen_urls.add(href)
            jobs.append(self._make_job(
                title=title,
                company=company,
                location="Remote",
                description="",
                url=clean_url,
            ))

        return jobs

    @staticmethod
    def _parse_wellfound_slug(url: str) -> tuple[str, str]:
        slug = url.rstrip("/").split("/")[-1]
        slug = re.sub(r"^\d+-", "", slug)

        company = "Not mentioned"
        if "-at-" in slug:
            role_part, company_part = slug.rsplit("-at-", 1)
            company = company_part.replace("-", " ").title()
            slug = role_part

        title = slug.replace("-", " ").title()
        return title, company


def enrich_from_json(content: str, jobs: list[dict]):
    """Extract descriptions from inline JSON blobs in page content."""
    try:
        descs = re.findall(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
        urls = re.findall(r'"(?:absolute_url|jobUrl)"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
    except Exception:
        return
    url_to_desc = {}
    for i, u in enumerate(urls):
        if i < len(descs) and descs[i] and len(descs[i]) > 50:
            clean = f"https://wellfound.com{u}" if not u.startswith("http") else u
            url_to_desc[clean.rstrip("/")] = descs[i]
    for job in jobs:
        job_url = job["url"].rstrip("/")
        if job_url in url_to_desc:
            job["description"] = url_to_desc[job_url]


async def fetch_wellfound_descriptions(context, jobs: list[dict]):
    """Open each Wellfound job URL and extract descriptions."""

    async def fetch_one(job):
        async with DESC_SEM:
            p = await context.new_page()
            try:
                desc = await _fetch_description(p, job["url"], "Wellfound")
                if desc:
                    job["description"] = desc
            except Exception:
                pass
            finally:
                await p.close()

    await asyncio.gather(*[fetch_one(j) for j in jobs])
