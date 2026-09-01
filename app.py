import asyncio
import logging
import re
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from playwright.async_api import async_playwright
from pydantic import BaseModel

from scrapers.browser import launch_browser
from scrapers.indeed import IndeedScraper
from scrapers.wellfound import WellfoundScraper
from scrapers.linkedin import LinkedInScraper
from scrapers.naukri import NaukriScraper
from scrapers.base import (
    DESCRIPTION_SELECTORS_BY_PORTAL,
    GENERIC_DESCRIPTION_SELECTORS,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("job-scraper")

DEFAULT_QUERIES = [
    "software-engineer",
    "ai-engineer",
    "fullstack",
    "backend-engineer",
    "sde",
]

MAX_JOBS_PER_PORTAL = 20
TARGET_TOTAL_JOBS = 60


class ScrapeRequest(BaseModel):
    queries: list[str] = DEFAULT_QUERIES
    location: str = "India"
    remote: bool = True


class JobDescriptionRequest(BaseModel):
    url: str
    portal: Optional[str] = None


scrapers: list = []


def detect_portal(url: str) -> str:
    if "indeed" in url:
        return "Indeed"
    if "linkedin" in url:
        return "LinkedIn"
    if "wellfound" in url or "angellist" in url:
        return "Wellfound"
    if "naukri" in url:
        return "Naukri"
    return ""


def dedupe_jobs(jobs: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique = []
    for job in jobs:
        key = job.get("url") or f"{job.get('title', '')}|{job.get('company', '')}|{job.get('portal', '')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def cap_jobs_by_portal(jobs: list[dict], max_per_portal: int) -> list[dict]:
    counts: dict[str, int] = {}
    capped = []
    for job in jobs:
        portal = job.get("portal", "Unknown")
        if counts.get(portal, 0) >= max_per_portal:
            continue
        counts[portal] = counts.get(portal, 0) + 1
        capped.append(job)
    return capped


@asynccontextmanager
async def lifespan(app: FastAPI):
    scrapers.extend([
        IndeedScraper(),
        WellfoundScraper(),
        LinkedInScraper(),
        NaukriScraper(),
    ])
    yield


app = FastAPI(title="Job Scraper Service", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/scrape-indeed")
async def scrape_indeed(req: ScrapeRequest):
    indeed = scrapers[0]
    try:
        jobs, errors = await asyncio.wait_for(
            indeed.scrape(req.queries, req.location, req.remote),
            timeout=indeed.timeout + 10,
        )
    except asyncio.TimeoutError:
        return {"count": 0, "jobs": [], "errors": [{"portal": "Indeed", "error": "Timeout"}]}
    except Exception as e:
        return {"count": 0, "jobs": [], "errors": [{"portal": "Indeed", "error": str(e)}]}

    log.info("Indeed scraper returned %d jobs", len(jobs))
    valid = [j for j in jobs if j.get("title") and j.get("url")][:30]
    return {"count": len(valid), "jobs": valid, "errors": errors}


@app.post("/scrape")
async def scrape(req: ScrapeRequest):
    all_jobs = []
    all_errors = []

    async def run_scraper(scraper):
        try:
            jobs, errors = await asyncio.wait_for(
                scraper.scrape(req.queries, req.location, req.remote),
                timeout=scraper.timeout + 10,
            )
            all_jobs.extend(jobs)
            all_errors.extend(errors)
        except asyncio.TimeoutError:
            all_errors.append({"portal": scraper.name, "error": "Timeout"})
        except Exception as e:
            all_errors.append({"portal": scraper.name, "error": str(e)})

    await asyncio.gather(*[run_scraper(s) for s in scrapers])

    raw_counts = {}
    for job in all_jobs:
        p = job.get("portal", "Unknown")
        raw_counts[p] = raw_counts.get(p, 0) + 1
    log.info("Raw scraped per portal: %s", raw_counts)

    no_desc_counts = {}
    for job in all_jobs:
        if not job.get("description"):
            p = job.get("portal", "Unknown")
            no_desc_counts[p] = no_desc_counts.get(p, 0) + 1
    log.info("Empty description per portal (pre-filter): %s", no_desc_counts)

    no_id_counts = {}
    for job in all_jobs:
        if not job.get("job_id"):
            p = job.get("portal", "Unknown")
            no_id_counts[p] = no_id_counts.get(p, 0) + 1
    log.info("Empty job_id per portal (pre-filter): %s", no_id_counts)

    valid_jobs = [
        job for job in all_jobs
        if job.get("title") and job.get("title") != "Unknown" and job.get("url")
    ]
    dropped_invalid = len(all_jobs) - len(valid_jobs)

    valid_jobs = dedupe_jobs(valid_jobs)
    after_dedupe = len(valid_jobs)

    valid_jobs = cap_jobs_by_portal(valid_jobs, MAX_JOBS_PER_PORTAL)
    after_cap = len(valid_jobs)

    valid_jobs = valid_jobs[:TARGET_TOTAL_JOBS]

    portals = {job.get("portal", "Unknown") for job in valid_jobs}
    log.info(
        "Funnel: raw=%s -> dropped_invalid=%s -> after_dedupe=%s -> after_cap=%s -> final=%s | portals=%s | errors=%s",
        len(all_jobs), dropped_invalid, after_dedupe, after_cap, len(valid_jobs), len(portals), len(all_errors),
    )
    if all_errors:
        log.info("Errors detail: %s", all_errors)

    return {
        "success": len(valid_jobs) > 0,
        "count": len(valid_jobs),
        "jobs": valid_jobs,
        "errors": all_errors,
    }


async def _extract_description(page, url: str, portal: str = "") -> str:
    """Navigate to job URL and extract description text. Uses portal-specific selectors."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        await page.wait_for_timeout(3000)

        selectors = DESCRIPTION_SELECTORS_BY_PORTAL.get(portal, []) + GENERIC_DESCRIPTION_SELECTORS
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if len(text) > 50:
                        return text[:2500]
            except Exception:
                continue

        body = await page.query_selector("body")
        if body:
            text = (await body.inner_text()).strip()
            return text[:2000]
    except Exception as e:
        log.warning("Description fetch failed for %s: %s", url, e)
    return ""


@app.post("/job-description")
async def job_description(req: JobDescriptionRequest):
    if not req.url or not req.url.startswith("http"):
        raise HTTPException(400, "Invalid URL")
    portal = req.portal or detect_portal(req.url)
    async with async_playwright() as pw:
        browser, context = await launch_browser(pw)
        page = await context.new_page()
        desc = await _extract_description(page, req.url, portal)
        await browser.close()
    return {"url": req.url, "description": desc}


class BulkDescriptionRequest(BaseModel):
    urls: list[str]


@app.post("/bulk-descriptions")
async def bulk_descriptions(req: BulkDescriptionRequest):
    urls = [u for u in req.urls[:50] if u.startswith("http")]
    if not urls:
        return {"descriptions": []}
    results = []
    async with async_playwright() as pw:
        browser, context = await launch_browser(pw)
        sem = asyncio.Semaphore(5)

        async def fetch_one(url):
            portal = detect_portal(url)
            async with sem:
                p = await context.new_page()
                try:
                    desc = await _extract_description(p, url, portal)
                    return {"url": url, "description": desc}
                finally:
                    await p.close()

        results = await asyncio.gather(*[fetch_one(u) for u in urls])
        await browser.close()
    return {"descriptions": results}
