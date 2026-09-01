import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class JobPosting:
    title: str
    company: str
    location: str
    description: str
    url: str
    salary: str = "Not mentioned"
    portal: str = "Unknown"
    posted_at: str = ""
    job_id: str = ""
    company_url: str = ""
    apply_url: str = ""
    skills: str = ""


DESCRIPTION_SELECTORS_BY_PORTAL = {
    "Indeed": [
        "#jobDescriptionText",
        "div.jobsearch-JobComponent-description",
        "[class*='jobsearch-jobDescriptionText']",
        ".job-desc",
    ],
    "LinkedIn": [
        ".description__text",
        ".show-more-less-html__markup",
        "article[class*='description']",
        "#job-details",
    ],
    "Wellfound": [
        "[class*='description']",
        "[data-test='job-description']",
        "article",
        "main",
    ],
    "Naukri": [
        ".job-desc",
        ".row4",
        "[class*='description']",
    ],
}

GENERIC_DESCRIPTION_SELECTORS = [
    "[class*='description']",
    "[class*='detail']",
    "article",
    "main",
    ".job-desc",
    "[class*='job-description']",
    "[class*='posting']",
    ".show-more-less-html__markup",
    "#job-details",
]


_browser_instance = None


class BaseScraper(ABC):
    def __init__(self, timeout: int = 240):
        self.timeout = timeout
        self.name = self.__class__.__name__.replace("Scraper", "")

    @abstractmethod
    async def scrape(self, queries: list[str], location: str = "India", remote: bool = False) -> tuple[list[dict], list[dict]]:
        """Return (jobs, errors). Each job is dict with JobPosting fields."""
        pass

    def _make_job(self, **kwargs) -> dict:
        kwargs.setdefault("portal", self.name)
        url = kwargs.get("url", "")
        if url and not kwargs.get("job_id"):
            portal = kwargs.get("portal", "")
            extracted = _extract_job_id(url, portal)
            if extracted:
                kwargs["job_id"] = extracted
        if url and not kwargs.get("apply_url"):
            kwargs["apply_url"] = url
        kwargs.setdefault("company_url", "")
        kwargs.setdefault("skills", "")
        return asdict(JobPosting(**kwargs))


def _extract_job_id(url: str, portal: str = "") -> str:
    if not url:
        return ""
    # Indeed: jk= param
    m = re.search(r'[?&]jk=([^&]+)', url)
    if m:
        return m.group(1)
    # LinkedIn URL pattern: /jobs/view/...-ID
    if "linkedin.com" in url:
        m = re.search(r'-(\d+)$', url.rstrip("/"))
        if m:
            return m.group(1)
    # Naukri URL pattern: ...-ID at end
    if "naukri.com" in url:
        m = re.search(r'-(\d+)$', url.rstrip("/"))
        if m:
            return m.group(1)
    # Wellfound URL pattern: /jobs/NUM-slug
    if "wellfound.com" in url:
        m = re.search(r'/jobs/(\d+)', url)
        if m:
            return m.group(1)
    # Fallback: last path segment
    last = url.rstrip("/").split("/")[-1].split("?")[0]
    if last and last != "-":
        return last
    return ""


async def _fetch_description(page, url: str, portal: str = "") -> str:
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
        logging.getLogger("job-scraper").warning("Desc fetch failed for %s: %s", url, e)
    return ""
