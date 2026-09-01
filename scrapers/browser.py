from __future__ import annotations

import logging
from typing import Tuple

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

log = logging.getLogger("job-scraper.browser")

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

STEALTH_SCRIPT = """
// Hide webdriver
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Spoof plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],
});

// Spoof languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-IN', 'en-US', 'en'],
});

// Spoof platform
Object.defineProperty(navigator, 'platform', {
    get: () => 'MacIntel',
});

// Remove chrome.runtime
if (window.chrome) {
    window.chrome.runtime = undefined;
}

// Override permissions
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (params) => (
    params.name === 'notifications' || params.name === 'clipboard-read'
        ? Promise.resolve({state: 'denied', onchange: null})
        : originalQuery(params)
);
"""


async def launch_browser(pw: Playwright) -> Tuple[Browser, BrowserContext]:
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ]
    browser = None

    for channel in ("chrome", None):
        try:
            opts = {"headless": True, "args": launch_args}
            if channel:
                opts["channel"] = channel
            browser = await pw.chromium.launch(**opts)
            if channel:
                log.info("Using system Chrome for scraping")
            break
        except Exception as exc:
            log.warning("Browser launch failed (%s): %s", channel or "chromium", exc)

    if browser is None:
        raise RuntimeError("Could not launch Playwright browser")

    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
        extra_http_headers={"Accept-Language": "en-IN,en;q=0.9"},
    )
    await context.add_init_script(STEALTH_SCRIPT)
    return browser, context


def normalize_query(query: str) -> str:
    return query.replace("-", " ").replace("developer", "engineer").strip()


def is_valid_job(title: str, url: str) -> bool:
    if not title or title.strip().lower() in ("unknown", "n/a", ""):
        return False
    if not url or not url.startswith("http"):
        return False
    return True
