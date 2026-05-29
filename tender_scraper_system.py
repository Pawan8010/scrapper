"""
AI-powered Indian government tender scraper engine.

Colab:
    !python tender_scraper_system.py
    !python tender_scraper_system.py --self-test
    !python tender_scraper_system.py --portal GeM --portal CPPP --max-pages 1

Outputs:
    tender_results.csv, tender_results.xlsx, tender_results.json

CAPTCHA/access challenges are detected and skipped safely. This scraper does
not solve CAPTCHA, bypass login, or break access controls.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import logging
import os
import random
import re
import subprocess
import sys
import time
import ssl
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


def ensure_dependencies() -> None:
    if os.environ.get("TENDER_SKIP_AUTO_INSTALL", "").lower() in {"1", "true", "yes"}:
        return

    self_test = "--self-test" in sys.argv
    static_only = "--static-only" in sys.argv
    streamlit_ui = any("streamlit" in arg.lower() or "tender_scraper_ui.py" in arg.lower() for arg in sys.argv)
    required_packages = {
        "bs4": "beautifulsoup4",
        "pandas": "pandas",
        "openpyxl": "openpyxl",
        "nest_asyncio": "nest_asyncio",
    }
    missing = [pip_name for module_name, pip_name in required_packages.items() if importlib.util.find_spec(module_name) is None]
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *missing], timeout=180)

    if not self_test and not static_only and not streamlit_ui and importlib.util.find_spec("playwright") is None:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "playwright"], timeout=180)
        except Exception as exc:
            print(f"WARNING: Playwright package install failed; static fallback may still work. Details: {exc}")

    if not self_test and not static_only and not streamlit_ui and os.environ.get("TENDER_SKIP_BROWSER_INSTALL", "").lower() not in {"1", "true", "yes"}:
        try:
            subprocess.check_call(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
            )
        except Exception as exc:
            print(f"WARNING: Playwright Chromium install failed; static fallback may still work. Details: {exc}")


ensure_dependencies()

import pandas as pd  # noqa: E402
from bs4 import BeautifulSoup, Tag  # noqa: E402


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("tender_scraper")


AI_KEYWORDS = [
    "reflex sight",
    "red dot sight",
    "holographic sight",
    "thermal weapon sight",
    "night vision sight",
    "day night sight",
    "thermal imager",
    "thermal imaging sight",
    "handheld thermal imager",
    "night vision device",
    "nvd",
    "night vision goggles",
    "nvg",
    "image intensifier",
    "uncooled thermal",
    "cooled thermal",
    "lwir",
    "mwir",
    "target acquisition system",
    "laser range finder",
    "lrf",
    "electro optical surveillance system",
    "long range observation system",
    "loros",
    "battlefield surveillance radar",
    "border surveillance system",
    "thermal camera",
    "long range ptz camera",
    "ptz camera",
    "optical camera",
    "night vision camera",
    "night vision",
    "drone",
    "surveillance",
    "ptz",
    "eoss",
    "infrared",
    "optical system",
]

TENDER_HINTS = [
    "tender",
    "tenders",
    "bid",
    "bids",
    "rfp",
    "rfq",
    "eoi",
    "auction",
    "corrigendum",
    "nit",
    "notice inviting tender",
    "enquiry",
    "procurement",
    "work item",
    "limited tender",
    "open tender",
    "global tender",
]

NON_TENDER_HINTS = [
    "login",
    "signup",
    "register",
    "contact",
    "privacy",
    "terms",
    "help",
    "faq",
    "sitemap",
    "archive policy",
    "accessibility",
    "about us",
    "manual",
    "download app",
    "forgot password",
    "announcements",
    "debarment",
    "downloads",
    "feedback",
    "site compatibility",
    "screen reader",
    "portal policies",
    "visitor no",
    "certifying agency",
    "information about dsc",
    "online bidder enrollment",
    "recognitions",
    "hassle free bid submission",
    "tenders by classification",
    "tenders by location",
    "tenders by organisation",
    "tenders in archive",
    "tenders status",
    "cancelled/retendered",
    "standard bidding documents",
    "service=restart",
    "search | active tenders",
    "latest tenders updates",
    "latest corrigendum updates",
    "find my nodal officer",
    "designed, developed and hosted",
    "nic, all rights reserved",
]

NON_TENDER_URL_PARTS = [
    "page=frontendadvancedsearch",
    "page=frontendlisttendersbydate",
    "page=resultoftenders",
    "page=home&service=page",
    "page=webannouncements",
    "page=webcancelledtenderlists",
    "page=frontenddebarmentlist",
    "page=standardbiddingdocuments",
    "page=frontfeedback",
    "page=dscinfo",
    "page=sitecomp",
    "page=webscreenreaderaccess",
    "page=webawards",
    "page=disclaimer",
    "webhomeborder",
    "service=restart",
]

GENERIC_NON_TENDER_TITLES = {
    "etenders",
    "eprocurement",
    "konugolu",
    "pmgsy assam",
}

CAPTCHA_MARKERS = [
    "captcha",
    "recaptcha",
    "g-recaptcha",
    "hcaptcha",
    "enter the characters",
    "security code",
    "verification code",
    "access denied",
    "unusual traffic",
    "bot detection",
    "cloudflare ray id",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1600, "height": 900},
    {"width": 1920, "height": 1080},
]


@dataclass(frozen=True)
class PortalConfig:
    name: str
    start_urls: list[str]
    base_url: Optional[str] = None
    max_pages: int = 2
    dynamic: bool = True
    wait_until: str = "domcontentloaded"
    tender_selectors: list[str] = field(default_factory=list)
    row_selectors: list[str] = field(default_factory=lambda: ["table tr", ".card", ".list-item", "li"])
    next_selectors: list[str] = field(
        default_factory=lambda: [
            "a:has-text('Next')",
            "button:has-text('Next')",
            "a[aria-label='Next']",
            "li.next a",
            ".pagination a:has-text('>')",
        ]
    )


@dataclass
class TenderRecord:
    portal: str
    title: str
    tender_url: str
    ai_score: int
    matched_keywords: str
    hash: str
    tender_id: str = ""
    department: str = ""
    deadline: str = ""
    closing_date: str = ""
    bid_opening_date: str = ""
    description: str = ""
    source_page: str = ""
    scraped_at: str = ""


@dataclass
class ScrapeStats:
    portal: str
    pages_loaded: int = 0
    candidates_seen: int = 0
    matched_records: int = 0
    captcha_detected: bool = False
    errors: list[str] = field(default_factory=list)


PORTALS = [
    PortalConfig("GeM", ["https://bidplus.gem.gov.in/all-bids", "https://gem.gov.in", "https://gem.gov.in/cppp"], tender_selectors=["a[href*='bid']", "a[href*='showbid']", ".bid_no a", ".card a", "table a"]),
    PortalConfig("CPPP", ["https://eprocure.gov.in/eprocure/app?page=FrontEndLatestActiveTenders&service=page", "https://eprocure.gov.in/eprocure/app?page=FrontEndTendersByOrganisation&service=page", "https://eprocure.gov.in"], tender_selectors=["a[href*='DirectLink']", "a[href*='Tender']", "table a", ".list_table a"]),
    PortalConfig("GePNIC", ["https://gepnic.gov.in", "https://eprocure.gov.in/eprocure/app"], tender_selectors=["a[href*='Tender']", "a[href*='DirectLink']", "table a"]),
    PortalConfig("IREPS Railway", ["https://www.ireps.gov.in/epsn/home/showTender.do"], tender_selectors=["a[href*='tender']", "a[href*='Tender']", "table a"]),
    PortalConfig("Defence Procurement", ["https://defproc.gov.in/nicgep/app", "https://mod.gov.in/dod/defence-procurement"], tender_selectors=["a[href*='tender']", "a[href*='Tender']", "a[href*='DirectLink']", "table a"]),
    PortalConfig("Coal India", ["https://www.coalindia.in/tenders/", "https://coalindiatenders.nic.in/nicgep/app"], tender_selectors=["a[href*='tender']", "a[href*='Tender']", "a[href*='DirectLink']", "table a"]),
    PortalConfig("Maharashtra Tenders", ["https://mahatenders.gov.in/nicgep/app"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Gujarat Police", ["https://nprocure.com", "https://tender.nprocure.com/"], tender_selectors=["a[href*='tender']", "a[href*='Tender']", "table a"]),
    PortalConfig("Karnataka Police", ["https://eproc.karnataka.gov.in", "https://kppp.karnataka.gov.in/"], tender_selectors=["a[href*='tender']", "a[href*='Tender']", "table a"]),
    PortalConfig("Tamil Nadu Tenders", ["https://tntenders.gov.in/nicgep/app"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Telangana Police", ["https://tender.telangana.gov.in/"], tender_selectors=["a[href*='tender']", "a[href*='Tender']", "table a"]),
    PortalConfig("Andhra Pradesh Police", ["https://apeprocurement.gov.in", "https://tender.apeprocurement.gov.in/"], tender_selectors=["a[href*='tender']", "a[href*='Tender']", "table a"]),
    PortalConfig("Uttar Pradesh Tenders", ["https://etender.up.nic.in/nicgep/app"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Rajasthan Tenders", ["https://eproc.rajasthan.gov.in/nicgep/app"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Madhya Pradesh Police", ["https://mptenders.gov.in/nicgep/app", "https://mptenders.gov.in"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Haryana Police", ["https://etenders.hry.nic.in/nicgep/app", "https://etenders.hry.nic.in"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Punjab Police", ["https://eproc.punjab.gov.in/nicgep/app", "https://eproc.punjab.gov.in"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Kerala Tenders", ["https://etenders.kerala.gov.in/nicgep/app"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("West Bengal Tenders", ["https://wbtenders.gov.in/nicgep/app"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Odisha Tenders", ["https://tendersodisha.gov.in/nicgep/app"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Bihar Police", ["https://eproc2.bihar.gov.in/nicgep/app", "https://eproc2.bihar.gov.in"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Jharkhand Police", ["https://jharkhandtenders.gov.in/nicgep/app", "https://jharkhandtenders.gov.in"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
    PortalConfig("Assam Police", ["https://assamtenders.gov.in/nicgep/app", "https://assamtenders.gov.in"], tender_selectors=["table a", "a[href*='DirectLink']", "a[href*='Tender']"]),
]


SELF_TEST_HTML = """
<html><body>
<table>
  <tr><td>Open Tender for thermal camera and night vision surveillance system</td><td><a href="/tender/123">View Tender</a></td></tr>
  <tr><td>Procurement of office chairs</td><td><a href="/tender/456">View Tender</a></td></tr>
</table>
<div class="card"><a href="https://example.gov.in/bid/789">Bid for drone based infrared optical system with PTZ payload</a></div>
<a href="/contact">Contact us</a>
</body></html>
"""


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def normalize_url(url: str, base_url: str) -> str:
    absolute = urljoin(base_url, url)
    parsed = urlparse(absolute)
    return parsed._replace(fragment="").geturl()


def make_hash(portal: str, title: str, url: str) -> str:
    payload = f"{portal.lower()}|{clean_text(title).lower()}|{url.lower()}".encode("utf-8", "ignore")
    return hashlib.md5(payload).hexdigest()


def score_tender(*texts: str) -> tuple[int, list[str]]:
    haystack = " ".join(clean_text(text).lower() for text in texts if text)
    matched = [keyword for keyword in AI_KEYWORDS if re.search(rf"\b{re.escape(keyword.lower())}\b", haystack)]
    return len(matched) * 10, matched


def extract_tender_dates(text: str) -> tuple[str, str]:
    """Best-effort extraction for NIC-style rows: closing date then bid opening date."""
    date_pattern = r"\b\d{1,2}[-/](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{1,2})[-/]\d{2,4}(?:\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)?\b"
    dates = [clean_text(match.group(0)) for match in re.finditer(date_pattern, text, flags=re.IGNORECASE)]
    if len(dates) >= 2:
        return dates[-2], dates[-1]
    if len(dates) == 1:
        return dates[0], ""
    return "", ""


def is_direct_tender_url(url: str) -> bool:
    parsed = urlparse(url)
    lowered = url.lower()
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if any(part in lowered for part in NON_TENDER_URL_PARTS):
        return False
    if "nicgep/app?page=" in lowered and "directlink" not in lowered:
        return False
    path = parsed.path.strip("/")
    query = parsed.query.lower()
    if not path and not query:
        return False
    direct_markers = [
        "directlink",
        "showbid",
        "showtender",
        "viewtender",
        "view-tender",
        "tender-detail",
        "bid-detail",
        "document",
        "download",
        "tender",
        "bid",
        "nit",
        "auction",
        "corrigendum",
        "tenderdetail",
        "tenderdetails",
    ]
    return any(marker in lowered for marker in direct_markers)


def looks_like_tender(title: str, url: str, description: str = "") -> bool:
    text = f"{title} {url} {description}".lower()
    lowered_url = url.lower()
    normalized_title = clean_text(title).lower()
    if not clean_text(title) or len(clean_text(title)) < 15:
        return False
    if not is_direct_tender_url(url):
        return False
    if normalized_title in GENERIC_NON_TENDER_TITLES:
        return False
    if any(part in lowered_url for part in NON_TENDER_URL_PARTS):
        return False
    if "nicgep/app?page=" in lowered_url and "directlink" not in lowered_url:
        return False
    if any(bad in text for bad in NON_TENDER_HINTS):
        return False
    if is_direct_tender_url(url):
        return True
    tender_reference = re.search(
        r"\b(?:gem/\d{4}/b/\d+|cil/|nit|rfp|rfq|eoi|tender\s*ref|bid\s*no)\b",
        text,
        flags=re.IGNORECASE,
    )
    return bool(tender_reference) or any(hint in text for hint in TENDER_HINTS)


def detect_captcha(html: str) -> bool:
    return any(marker in html.lower() for marker in CAPTCHA_MARKERS)


async def random_delay(min_seconds: float, max_seconds: float) -> None:
    await asyncio.sleep(random.uniform(min_seconds, max_seconds))


async def retry_async(operation, retries: int, base_delay: float, portal: str):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return await operation()
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                delay = base_delay * attempt + random.uniform(0.5, 2.0)
                logger.info("%s retrying after error (%s/%s): %s", portal, attempt, retries, exc)
                await asyncio.sleep(delay)
    raise RuntimeError(f"{portal} failed after {retries} attempts: {last_error}")


class BrowserPool:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self.browser = None
        self.available = False

    async def __aenter__(self) -> "BrowserPool":
        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self.browser = await self._launch_chromium()
            self.available = True
        except Exception as exc:
            logger.error("Playwright browser unavailable; using static fallback where possible: %s", exc)
            self.available = False
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _launch_chromium(self):
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
        try:
            return await self._playwright.chromium.launch(headless=self.headless, args=launch_args)
        except Exception as exc:
            message = str(exc).lower()
            if "executable doesn't exist" not in message and "please run" not in message:
                raise
            logger.info("Installing Playwright Chromium runtime for dynamic scraping")
            subprocess.check_call(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=240,
            )
            return await self._playwright.chromium.launch(headless=self.headless, args=launch_args)

    async def new_context(self):
        if not self.browser:
            raise RuntimeError("BrowserPool has not been started")
        context = await self.browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport=random.choice(VIEWPORTS),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
            java_script_enabled=True,
            ignore_https_errors=True,
            extra_http_headers={"Accept-Language": "en-IN,en;q=0.9", "DNT": "1"},
        )
        await context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-IN', 'en'] });
            window.chrome = window.chrome || { runtime: {} };
            """
        )
        return context


class TenderScraperEngine:
    def __init__(
        self,
        portals: list[PortalConfig],
        concurrency: int = 3,
        headless: bool = True,
        min_delay: float = 5.0,
        max_delay: float = 15.0,
        retries: int = 3,
        browser_enabled: bool = True,
        all_tenders: bool = False,
    ):
        self.portals = portals
        self.semaphore = asyncio.Semaphore(concurrency)
        self.headless = headless
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.retries = retries
        self.browser_enabled = browser_enabled
        self.all_tenders = all_tenders
        self.seen_hashes: set[str] = set()
        self.stats: dict[str, ScrapeStats] = {}

    async def scrape_all(self) -> pd.DataFrame:
        start = time.perf_counter()
        if self.browser_enabled:
            async with BrowserPool(headless=self.headless) as browser_pool:
                results = await asyncio.gather(*[self._safe_scrape_portal(browser_pool, p) for p in self.portals])
        else:
            results = await asyncio.gather(*[self._safe_scrape_portal(None, p) for p in self.portals])

        records = [record for portal_records in results for record in portal_records]
        df = self._to_dataframe(records)
        logger.info("Scraping completed: %s filtered tender(s) in %.1fs", len(df), time.perf_counter() - start)
        self._log_stats()
        return df

    async def _safe_scrape_portal(self, browser_pool: Optional[BrowserPool], portal: PortalConfig) -> list[TenderRecord]:
        async with self.semaphore:
            self.stats[portal.name] = ScrapeStats(portal=portal.name)
            try:
                return await self.scrape_portal(browser_pool, portal)
            except Exception as exc:
                self.stats[portal.name].errors.append(str(exc))
                logger.error("Portal failed: %s | %s", portal.name, exc)
                return []

    async def scrape_portal(self, browser_pool: Optional[BrowserPool], portal: PortalConfig) -> list[TenderRecord]:
        logger.info("Starting portal: %s", portal.name)
        if browser_pool and browser_pool.available and portal.dynamic:
            return await self._scrape_dynamic(browser_pool, portal)
        return await self._scrape_static(portal)

    async def _scrape_dynamic(self, browser_pool: BrowserPool, portal: PortalConfig) -> list[TenderRecord]:
        context = await browser_pool.new_context()
        page = await context.new_page()
        records: list[TenderRecord] = []
        try:
            for url in portal.start_urls:
                html = await retry_async(lambda url=url: self._fetch_dynamic_page(page, url, portal), self.retries, 2.0, portal.name)
                records.extend(self._parse_records(portal, html, page.url))
                for _ in range(max(0, portal.max_pages - 1)):
                    if not await self._go_next(page, portal):
                        break
                    await random_delay(self.min_delay, min(self.max_delay, self.min_delay + 5))
                    html = await page.content()
                    if detect_captcha(html):
                        self.stats[portal.name].captcha_detected = True
                        break
                    self.stats[portal.name].pages_loaded += 1
                    records.extend(self._parse_records(portal, html, page.url))
        finally:
            await context.close()
        logger.info("%s produced %s scored tender(s)", portal.name, len(records))
        return records

    async def _scrape_static(self, portal: PortalConfig) -> list[TenderRecord]:
        records: list[TenderRecord] = []
        queue = list(portal.start_urls)
        visited: set[str] = set()

        while queue and len(visited) < portal.max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            html = await retry_async(lambda url=url: asyncio.to_thread(self._fetch_static_page, url, portal), self.retries, 2.0, portal.name)
            if not html:
                continue
            if detect_captcha(html):
                self.stats[portal.name].captcha_detected = True
                logger.error("CAPTCHA/access challenge detected, skipping: %s", portal.name)
                continue
            self.stats[portal.name].pages_loaded += 1
            records.extend(self._parse_records(portal, html, url))

            for next_url in self._extract_static_follow_urls(html, url):
                if next_url not in visited and next_url not in queue and self._same_site(url, next_url):
                    queue.append(next_url)
        logger.info("%s produced %s scored tender(s)", portal.name, len(records))
        return records

    def _extract_static_follow_urls(self, html: str, current_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        follow_terms = [
            "active tender",
            "latest tender",
            "closing date",
            "corrigendum",
            "tenders by",
            "next",
            "more",
        ]
        follow_url_parts = [
            "frontendlatestactivetenders",
            "frontendlisttendersbydate",
            "frontendlatestactivecorrigendums",
            "frontendtendersbyorganisation",
            "frontendtendersbylocation",
            "frontendtendersbyclassification",
            "page=home",
        ]

        urls: list[str] = []
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if self._skip_href(href):
                continue
            text = clean_text(anchor.get_text(" ", strip=True)).lower()
            absolute = normalize_url(href, current_url)
            lowered = absolute.lower()
            if "directlink" in lowered:
                continue
            should_follow = any(term in text for term in follow_terms) or any(part in lowered for part in follow_url_parts)
            if should_follow and not any(part in lowered for part in NON_TENDER_URL_PARTS if part not in {"page=frontendlisttendersbydate"}):
                urls.append(absolute)
        return urls

    @staticmethod
    def _same_site(source_url: str, target_url: str) -> bool:
        return urlparse(source_url).netloc.lower() == urlparse(target_url).netloc.lower()

    async def _fetch_dynamic_page(self, page, url: str, portal: PortalConfig) -> str:
        logger.info("Loading %s | %s", portal.name, url)
        await random_delay(self.min_delay, self.max_delay)
        response = await page.goto(url, wait_until=portal.wait_until, timeout=60_000)
        if response and response.status >= 400:
            logger.error("%s returned HTTP %s for %s", portal.name, response.status, url)
        await self._humanize_page(page)
        html = await page.content()
        if detect_captcha(html):
            self.stats[portal.name].captcha_detected = True
            return ""
        self.stats[portal.name].pages_loaded += 1
        return html
    
    
    def _fetch_static_page(self, url: str, portal: PortalConfig) -> str:
        logger.info("Static loading %s | %s", portal.name, url)
        time.sleep(random.uniform(self.min_delay, self.max_delay))
        request = Request(url, headers={"User-Agent": random.choice(USER_AGENTS), "Accept-Language": "en-IN,en;q=0.9"})
        with urlopen(request, timeout=45, context=ssl._create_unverified_context()) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace")

    async def _humanize_page(self, page) -> None:
        viewport = page.viewport_size or {"width": 1366, "height": 768}
        for _ in range(random.randint(2, 5)):
            await page.mouse.move(random.randint(50, max(60, viewport["width"] - 50)), random.randint(50, max(60, viewport["height"] - 50)), steps=random.randint(8, 20))
            await asyncio.sleep(random.uniform(0.2, 0.8))
        for _ in range(random.randint(2, 4)):
            await page.mouse.wheel(0, random.randint(250, 900))
            await asyncio.sleep(random.uniform(0.5, 1.5))
        await page.mouse.wheel(0, random.randint(-250, -50))
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            logger.info("Network idle timeout; continuing with available DOM")

    async def _go_next(self, page, portal: PortalConfig) -> bool:
        for selector in portal.next_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() and await locator.is_visible():
                    await locator.click(timeout=5_000)
                    await page.wait_for_load_state("domcontentloaded", timeout=20_000)
                    return True
            except Exception:
                continue
        return False

    def _parse_records(self, portal: PortalConfig, html: str, current_url: str) -> list[TenderRecord]:
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        candidates = self._extract_candidates(portal, soup, current_url)
        self.stats[portal.name].candidates_seen += len(candidates)
        records: list[TenderRecord] = []

        for candidate in candidates:
            title, url, description, tender_id, department, deadline = candidate
            if not looks_like_tender(title, url, description):
                continue
            score, matched = score_tender(title, description, url)
            if score <= 0 and not self.all_tenders:
                continue
            row_hash = make_hash(portal.name, title, url)
            if row_hash in self.seen_hashes:
                continue
            self.seen_hashes.add(row_hash)
            closing_date, bid_opening_date = extract_tender_dates(f"{title} {description}")
            records.append(
                TenderRecord(
                    portal=portal.name,
                    title=clean_text(title),
                    tender_url=url,
                    ai_score=score,
                    matched_keywords=", ".join(matched),
                    hash=row_hash,
                    tender_id=clean_text(tender_id),
                    department=clean_text(department),
                    deadline=clean_text(deadline or closing_date),
                    closing_date=closing_date,
                    bid_opening_date=bid_opening_date,
                    description=clean_text(description),
                    source_page=current_url,
                    scraped_at=datetime.now().isoformat(timespec="seconds"),
                )
            )
        self.stats[portal.name].matched_records += len(records)
        return records

    def _extract_candidates(self, portal: PortalConfig, soup: BeautifulSoup, current_url: str) -> list[tuple[str, str, str, str, str, str]]:
        candidates = self._extract_row_candidates(portal, soup, current_url)
        candidates.extend(self._extract_anchor_candidates(portal, soup, current_url))
        unique: dict[str, tuple[str, str, str, str, str, str]] = {}
        for title, url, description, tender_id, department, deadline in candidates:
            if not url or not is_direct_tender_url(url):
                continue
            unique.setdefault(url, (title, url, description, tender_id, department, deadline))
        return list(unique.values())

    def _extract_row_candidates(self, portal: PortalConfig, soup: BeautifulSoup, current_url: str) -> list[tuple[str, str, str, str, str, str]]:
        rows: list[Tag] = []
        for selector in portal.row_selectors:
            try:
                rows.extend([row for row in soup.select(selector) if isinstance(row, Tag)])
            except Exception:
                logger.info("Ignoring invalid row selector for %s: %s", portal.name, selector)

        candidates = []
        for row in rows:
            link = self._select_detail_link(row, portal.base_url or current_url)
            if not link:
                continue
            href = link.get("href", "")
            if self._skip_href(href):
                continue
            url = normalize_url(href, portal.base_url or current_url)
            if not is_direct_tender_url(url):
                continue
            row_text = clean_text(row.get_text(" ", strip=True))
            link_text = clean_text(link.get_text(" ", strip=True))
            title, tender_id, department, deadline = self._extract_structured_row_fields(row, link)
            if not title:
                title = self._best_title(row_text, link_text, href)
            candidates.append((title, url, row_text, tender_id, department, deadline))
        return candidates

    def _extract_anchor_candidates(self, portal: PortalConfig, soup: BeautifulSoup, current_url: str) -> list[tuple[str, str, str, str, str, str]]:
        anchors: list[Tag] = []
        for selector in portal.tender_selectors or ["a[href]"]:
            try:
                anchors.extend([anchor for anchor in soup.select(selector) if isinstance(anchor, Tag)])
            except Exception:
                logger.info("Ignoring invalid selector for %s: %s", portal.name, selector)

        if not anchors:
            anchors = [anchor for anchor in soup.find_all("a", href=True) if isinstance(anchor, Tag)]

        candidates = []
        for anchor in anchors:
            href = anchor.get("href", "")
            if self._skip_href(href):
                continue
            url = normalize_url(href, portal.base_url or current_url)
            if not is_direct_tender_url(url):
                continue
            title = clean_text(anchor.get_text(" ", strip=True)) or self._title_from_url(url)
            container = anchor.find_parent(["tr", "li", "article", "div", "section"])
            description = clean_text(container.get_text(" ", strip=True) if container else title)
            tender_id = ""
            department = ""
            deadline = ""
            if isinstance(container, Tag):
                row_title, tender_id, department, deadline = self._extract_structured_row_fields(container, anchor)
                title = row_title or title
            candidates.append((self._best_title(description, title, href), url, description, tender_id, department, deadline))
        return candidates

    def _select_detail_link(self, row: Tag, base_url: str) -> Optional[Tag]:
        anchors = [anchor for anchor in row.find_all("a", href=True) if isinstance(anchor, Tag)]
        if not anchors:
            return None

        def priority(anchor: Tag) -> tuple[int, int]:
            href = str(anchor.get("href", ""))
            if self._skip_href(href):
                return (99, 0)
            url = normalize_url(href, base_url)
            if not is_direct_tender_url(url):
                return (90, 0)
            text = clean_text(anchor.get_text(" ", strip=True)).lower()
            lowered = url.lower()
            if text in {"view", "view tender", "details", "detail", "open", "download", "download document"}:
                return (0, -len(lowered))
            if any(marker in lowered for marker in ["directlink", "showtender", "showbid", "tenderdetail", "tenderdetails"]):
                return (1, -len(lowered))
            if any(term in text for term in ["tender", "bid", "nit", "rfp", "rfq"]):
                return (2, -len(text))
            return (5, -len(text))

        selected = sorted(anchors, key=priority)[0]
        return selected if priority(selected)[0] < 90 else None

    def _extract_structured_row_fields(self, row: Tag, detail_link: Tag) -> tuple[str, str, str, str]:
        cells = [cell for cell in row.find_all(["td", "th"], recursive=False) if isinstance(cell, Tag)]
        if not cells and row.name != "tr":
            cells = [cell for cell in row.find_all(["td", "th"]) if isinstance(cell, Tag)]

        cell_texts = [clean_text(cell.get_text(" ", strip=True)) for cell in cells]
        link_text = clean_text(detail_link.get_text(" ", strip=True)).lower()
        meaningful_cells = [text for text in cell_texts if text and text.lower() not in {"view", "details", "download", link_text}]

        tender_id = ""
        title = ""
        department = ""
        deadline = ""

        if len(meaningful_cells) >= 2:
            tender_id = meaningful_cells[0]
            title = meaningful_cells[1]
            if len(meaningful_cells) >= 3:
                deadline = meaningful_cells[2]
            if len(meaningful_cells) >= 4:
                department = meaningful_cells[3]
        elif len(meaningful_cells) == 1:
            title = meaningful_cells[0]
        else:
            title = clean_text(row.get_text(" ", strip=True))

        if not deadline:
            deadline, _ = extract_tender_dates(" ".join(meaningful_cells))

        title = self._clean_title_from_row(title, tender_id, deadline)
        return title, tender_id, department, deadline

    @staticmethod
    def _clean_title_from_row(title: str, tender_id: str, deadline: str) -> str:
        cleaned = clean_text(title)
        for part in [tender_id, deadline, "View", "Details", "Download"]:
            part = clean_text(part)
            if part and len(part) > 2:
                cleaned = clean_text(cleaned.replace(part, " "))
        return cleaned[:500]

    @staticmethod
    def _skip_href(href: str) -> bool:
        lowered = href.lower().strip()
        return not lowered or lowered.startswith(("javascript:", "mailto:", "tel:", "#"))

    @staticmethod
    def _best_title(row_text: str, link_text: str, href: str) -> str:
        row_text = clean_text(row_text)
        link_text = clean_text(link_text)
        generic = link_text.lower() in {"view", "view tender", "download", "click here", "details", "more"}
        if row_text and (generic or len(row_text) > len(link_text)):
            return row_text[:500]
        if link_text:
            return link_text[:500]
        return clean_text(re.sub(r"[-_/]+", " ", href))[:500]

    @staticmethod
    def _title_from_url(url: str) -> str:
        return clean_text(re.sub(r"[-_/]+", " ", urlparse(url).path).strip())

    @staticmethod
    def _to_dataframe(records: Iterable[TenderRecord]) -> pd.DataFrame:
        rows = [asdict(record) for record in records]
        columns = [
            "portal",
            "title",
            "tender_url",
            "tender_id",
            "department",
            "deadline",
            "ai_score",
            "matched_keywords",
            "hash",
            "closing_date",
            "bid_opening_date",
            "description",
            "source_page",
            "scraped_at",
        ]
        df = pd.DataFrame(rows, columns=columns)
        if df.empty:
            return df
        return df.drop_duplicates(subset=["hash"]).sort_values(["scraped_at", "ai_score", "portal"], ascending=[False, False, True]).reset_index(drop=True)

    def _log_stats(self) -> None:
        for stat in self.stats.values():
            logger.info("Stats | %s | pages=%s candidates=%s matches=%s captcha=%s errors=%s", stat.portal, stat.pages_loaded, stat.candidates_seen, stat.matched_records, stat.captcha_detected, len(stat.errors))


def filter_portals(names: list[str]) -> list[PortalConfig]:
    if not names:
        return PORTALS
    wanted = {name.lower() for name in names}
    selected = [portal for portal in PORTALS if portal.name.lower() in wanted or any(name in portal.name.lower() for name in wanted)]
    if not selected:
        raise SystemExit("No matching portals found. Available portals: " + ", ".join(portal.name for portal in PORTALS))
    return selected


def with_max_pages(portals: list[PortalConfig], max_pages: int) -> list[PortalConfig]:
    return [
        PortalConfig(p.name, p.start_urls, p.base_url, max_pages, p.dynamic, p.wait_until, p.tender_selectors, p.row_selectors, p.next_selectors)
        for p in portals
    ]


async def run_scraper(args: argparse.Namespace) -> pd.DataFrame:
    if args.self_test:
        portal = PortalConfig("Self Test Portal", ["https://example.gov.in/tenders"], dynamic=False)
        engine = TenderScraperEngine([portal], browser_enabled=False, min_delay=0, max_delay=0, retries=1, all_tenders=args.all_tenders)
        engine.stats[portal.name] = ScrapeStats(portal.name)
        return engine._to_dataframe(engine._parse_records(portal, SELF_TEST_HTML, "https://example.gov.in/tenders"))

    portals = with_max_pages(filter_portals(args.portal), args.max_pages)
    engine = TenderScraperEngine(
        portals,
        args.concurrency,
        not args.show_browser,
        args.min_delay,
        args.max_delay,
        args.retries,
        not args.static_only,
        args.all_tenders,
    )
    return await engine.scrape_all()


def export_results(df: pd.DataFrame, output_prefix: str) -> None:
    csv_path = Path(f"{output_prefix}.csv")
    excel_path = Path(f"{output_prefix}.xlsx")
    json_path = Path(f"{output_prefix}.json")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    df.to_excel(excel_path, index=False)
    df.to_json(json_path, orient="records", indent=2, force_ascii=False)
    logger.info("Exported CSV: %s", csv_path.resolve())
    logger.info("Exported Excel: %s", excel_path.resolve())
    logger.info("Exported JSON: %s", json_path.resolve())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI-powered Indian government tender scraper")
    parser.add_argument("--portal", action="append", default=[], help="Portal name filter. Can be repeated.")
    parser.add_argument("--max-pages", type=int, default=int(os.environ.get("TENDER_MAX_PAGES", "2")))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("TENDER_CONCURRENCY", "3")))
    parser.add_argument("--min-delay", type=float, default=float(os.environ.get("TENDER_MIN_DELAY", "5")))
    parser.add_argument("--max-delay", type=float, default=float(os.environ.get("TENDER_MAX_DELAY", "15")))
    parser.add_argument("--retries", type=int, default=int(os.environ.get("TENDER_RETRIES", "3")))
    parser.add_argument("--output-prefix", default=os.environ.get("TENDER_OUTPUT_PREFIX", "tender_results"))
    parser.add_argument("--static-only", action="store_true", help="Use HTTP/static fallback only.")
    parser.add_argument("--show-browser", action="store_true", help="Run Chromium visibly for debugging.")
    parser.add_argument("--self-test", action="store_true", help="Run parser/scoring/export test on sample HTML.")
    parser.add_argument("--all-tenders", action="store_true", help="Keep every tender-like record, including rows with AI score 0.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.min_delay < 0 or args.max_delay < args.min_delay:
        raise SystemExit("--max-delay must be greater than or equal to --min-delay")

    try:
        df = asyncio.run(run_scraper(args))
    except RuntimeError:
        import nest_asyncio

        nest_asyncio.apply()
        loop = asyncio.get_event_loop()
        df = loop.run_until_complete(run_scraper(args))

    export_results(df, args.output_prefix)
    print("\nScraped tender results:")
    if df.empty:
        print("No tender records found in this run.")
    else:
        cols = ["portal", "title", "tender_url", "ai_score", "matched_keywords", "hash"]
        print(df[cols].to_string(index=False))


if __name__ == "__main__":
    main()
