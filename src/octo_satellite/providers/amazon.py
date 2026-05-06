"""Amazon provider — Playwright-based session management.

First run: launches a visible browser for manual login (handles 2FA naturally).
Subsequent runs: reuses saved session headlessly.
"""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from octo_satellite.config import settings

logger = logging.getLogger("octo_satellite.amazon")

# Persistent session storage
SESSION_DIR = Path(settings.amazon_session_dir).expanduser()


class AmazonSession:
    """Manages a persistent Playwright browser session for Amazon."""

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()

    @property
    def _session_exists(self) -> bool:
        """Check if a saved session (cookies/storage) exists on disk."""
        return (SESSION_DIR / "state.json").exists()

    async def start(self, headless: bool | None = None) -> BrowserContext:
        """Start or resume the browser session.

        If no saved session exists, launches headed for manual login.
        Otherwise, launches headless with saved state.
        """
        if self._context:
            return self._context

        if headless is None:
            headless = self._session_exists

        SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)

        if self._session_exists:
            self._context = await self._browser.new_context(
                storage_state=str(SESSION_DIR / "state.json"),
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            )
        else:
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            )

        return self._context

    async def save_session(self):
        """Persist session state (cookies, localStorage) to disk."""
        if self._context:
            state_file = SESSION_DIR / "state.json"
            await self._context.storage_state(path=str(state_file))
            state_file.chmod(0o600)

    async def _new_page(self) -> Page:
        """Create a new page from the current context."""
        ctx = await self.start(headless=True)
        return await ctx.new_page()

    async def _verify_authenticated(self, page: Page) -> bool:
        """Check if current page is authenticated (not redirected to sign-in)."""
        return "ap/signin" not in page.url

    async def login(self) -> bool:
        """Launch a headed browser for manual login. Returns True when authenticated."""
        async with self._lock:
            # Always start fresh for login — don't reuse stale cookies
            await self.close()
            SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=False)
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            )

            page = await self._context.new_page()
            await page.goto("https://www.amazon.com/gp/css/order-history")

            print("\n🔐 Please log in to Amazon in the browser window.")
            print("   Complete 2FA if prompted. This window will close once login is detected.\n")

            try:
                while True:
                    if "ap/signin" not in page.url and "your-orders" in page.url:
                        break
                    await page.wait_for_timeout(1000)
            except Exception:
                return False

            # Let all cookies settle
            await page.wait_for_timeout(3000)

            await self.save_session()
            print("✅ Login detected! Session saved.")
            await page.close()
            # Close headed browser so subsequent calls use headless
            await self.close()
            return True

    async def check_auth(self) -> dict:
        """Verify the saved session is still authenticated.

        Returns {"authenticated": bool, "name": str|None}.
        """
        async with self._lock:
            page = await self._new_page()
            try:
                await page.goto(
                    "https://www.amazon.com/gp/css/homepage.html",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(2000)

                if not await self._verify_authenticated(page):
                    return {"authenticated": False, "name": None}

                name_el = await page.query_selector("#nav-link-accountList-nav-line-1")
                name = None
                if name_el:
                    text = await name_el.inner_text()
                    if "Hello" in text and "Sign in" not in text:
                        name = text.replace("Hello, ", "").strip()

                authenticated = name is not None
                if authenticated:
                    await self.save_session()

                return {"authenticated": authenticated, "name": name}
            finally:
                await page.close()

    async def get_orders(self, page_num: int = 1) -> dict:
        """Fetch orders from Amazon order history.

        Args:
            page_num: Page number (1-based). Each page has ~10 orders.

        Returns dict with total_count, page, total_pages, and orders list.
        """
        async with self._lock:
            page = await self._new_page()
            try:
                start_index = (page_num - 1) * 10
                url = f"https://www.amazon.com/your-orders/orders?startIndex={start_index}"
                await page.goto(url, wait_until="domcontentloaded")
                # Wait for order cards to appear
                await page.wait_for_selector(
                    ".order-card",
                    timeout=15000,
                )
                await page.wait_for_timeout(2000)

                if not await self._verify_authenticated(page):
                    return {"total_count": 0, "page": page_num, "total_pages": 0, "orders": []}

                # Get total order count
                count_info = await page.evaluate(r"""() => {
                    const text = document.body.innerText;
                    const match = text.match(/(\d+) orders? placed in/);
                    return match ? parseInt(match[1]) : null;
                }""")

                total_count = count_info or 0
                total_pages = (total_count + 9) // 10 if total_count else 1

                orders = await self._scrape_order_list(page)
                await self.save_session()

                return {
                    "total_count": total_count,
                    "page": page_num,
                    "total_pages": total_pages,
                    "orders": orders,
                }
            finally:
                await page.close()

    async def get_order(self, order_id: str) -> dict | None:
        """Fetch details and tracking info for a specific order.

        Returns order details with tracking info, or None if not found.
        """
        async with self._lock:
            page = await self._new_page()
            try:
                # Navigate to order detail page
                url = f"https://www.amazon.com/gp/your-account/order-details?orderID={order_id}"
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                if not await self._verify_authenticated(page):
                    return None

                order = await self._scrape_order_detail(page, order_id)

                # Try to get tracking info
                tracking = await self._scrape_tracking(page)
                if tracking:
                    order["tracking"] = tracking

                await self.save_session()
                return order
            finally:
                await page.close()

    async def heartbeat(self) -> bool:
        """Keep the session alive by loading an authenticated page.

        Returns True if session is still valid, False if expired.
        """
        async with self._lock:
            page = await self._new_page()
            try:
                await page.goto(
                    "https://www.amazon.com/gp/css/homepage.html",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(2000)

                if not await self._verify_authenticated(page):
                    logger.warning("Heartbeat: session expired!")
                    return False

                await self.save_session()
                logger.info("Heartbeat: session alive")
                return True
            finally:
                await page.close()

    async def _scrape_order_list(self, page: Page) -> list[dict]:
        """Extract order info from the order history page DOM."""
        return await page.evaluate("""() => {
            const orders = [];
            const cards = document.querySelectorAll('.order-card');

            for (const card of cards) {
                const order = {
                    order_id: null,
                    date: null,
                    total: null,
                    status: null,
                    items: []
                };

                // Parse header items
                const headerItems = card.querySelectorAll('.order-header__header-list-item');
                for (const item of headerItems) {
                    const spans = item.querySelectorAll(':scope > span, :scope > div > span');
                    const texts = Array.from(spans)
                        .map(s => s.childNodes.length <= 2 ? s.textContent.trim() : '')
                        .filter(Boolean);
                    if (texts.length >= 2) {
                        const [label, value] = texts;
                        if (label.includes('Order placed')) order.date = value;
                        else if (label === 'Total') order.total = value;
                        else if (label.includes('Order #')) order.order_id = value;
                    }
                }

                // Fallback: order ID from link
                if (!order.order_id) {
                    const link = card.querySelector('a[href*="orderID"]');
                    if (link) {
                        const match = link.href.match(/orderID=([^&]+)/);
                        if (match) order.order_id = match[1];
                    }
                }

                // Status
                const statusEl = card.querySelector(
                    '.delivery-box__primary-text, .yohtmlc-shipment-status-primaryText'
                );
                if (statusEl) order.status = statusEl.textContent.trim();

                // Items (deduplicated)
                const itemEls = card.querySelectorAll('.yohtmlc-product-title');
                const seen = new Set();
                for (const el of itemEls) {
                    const title = el.textContent.trim();
                    if (title && !seen.has(title)) {
                        seen.add(title);
                        order.items.push(title);
                    }
                }

                if (order.order_id || order.items.length) {
                    orders.push(order);
                }
            }
            return orders;
        }""")

    async def _scrape_order_detail(self, page: Page, order_id: str) -> dict:
        """Extract order detail info from the order detail page."""
        order = {
            "order_id": order_id,
            "date": None,
            "total": None,
            "status": None,
            "items": [],
            "shipping_address": None,
            "tracking": None,
        }

        # Date — find "Order placed" text and get next sibling's value
        date_val = await page.evaluate("""() => {
            const el = [...document.querySelectorAll('span')].find(
                s => s.textContent.trim() === 'Order placed'
            );
            if (el) {
                const next = el.parentElement?.querySelector('span:last-of-type')
                    || el.nextElementSibling;
                if (next && next !== el) return next.textContent.trim();
                // Try parent's next sibling
                const pNext = el.parentElement?.nextElementSibling;
                if (pNext) return pNext.textContent.trim();
            }
            return null;
        }""")
        if date_val:
            order["date"] = date_val

        # Grand Total
        total_val = await page.evaluate("""() => {
            const el = [...document.querySelectorAll('span, td')]
                .find(s => s.textContent.trim().includes('Grand Total'));
            if (el) {
                const row = el.closest('tr') || el.closest('div');
                if (row) {
                    const bold = row.querySelector('.a-text-bold, .a-color-base');
                    if (bold && bold !== el) return bold.textContent.trim();
                }
            }
            return null;
        }""")
        if total_val:
            order["total"] = total_val

        # Delivery status
        status_el = await page.query_selector(
            ".delivery-box__primary-text, .pt-promise-main-slot, h1.pt-promise-main-slot"
        )
        if status_el:
            order["status"] = (await status_el.inner_text()).strip()
        else:
            # Fallback: find bold text with delivery keywords
            status_val = await page.evaluate("""() => {
                const bolds = document.querySelectorAll('.a-text-bold');
                for (const b of bolds) {
                    const t = b.textContent.trim();
                    if (/deliver|arriv|ship|cancel/i.test(t)) return t;
                }
                return null;
            }""")
            if status_val:
                order["status"] = status_val

        # Items — detail page uses product links rather than .yohtmlc-product-title
        item_els = await page.query_selector_all(".yohtmlc-product-title")
        if not item_els:
            # Fallback: product links (filter out unrelated card/promo links)
            item_els = await page.evaluate("""() => {
                const links = document.querySelectorAll('a[href*="/dp/"]');
                const titles = [];
                for (const a of links) {
                    const text = a.textContent.trim();
                    if (text && text.length > 10
                        && !text.includes('Card')
                        && !titles.includes(text)) {
                        titles.push(text);
                    }
                }
                return titles;
            }""")
            if item_els:
                order["items"] = item_els
        else:
            for item_el in item_els:
                title = (await item_el.inner_text()).strip()
                if title and title not in order["items"]:
                    order["items"].append(title)

        # Shipping address — find "Ship to" section
        addr_val = await page.evaluate("""() => {
            const el = [...document.querySelectorAll('span')]
                .find(s => s.textContent.trim() === 'Ship to');
            if (el) {
                const container = el.closest('.order-header__header-list-item')
                    || el.closest('div');
                if (container) {
                    const lines = container.textContent.replace('Ship to', '')
                        .trim().split(/\\n/).map(s => s.trim()).filter(Boolean);
                    return lines.join(', ');
                }
            }
            return null;
        }""")
        if addr_val:
            order["shipping_address"] = addr_val

        return order

    async def _scrape_tracking(self, page: Page) -> list[dict] | None:
        """Extract tracking info from the order detail or tracking page.

        Clicks 'Track package' if available to navigate to tracking page.
        """
        # Try clicking "Track package" to get to tracking page
        track_btn = await page.query_selector("a:has-text('Track package'), input[value*='Track']")
        if track_btn:
            try:
                await track_btn.click()
                await page.wait_for_timeout(4000)
            except Exception:
                pass

        # Check if we're on a tracking page
        tracking_id_el = await page.query_selector(
            ".pt-delivery-card-trackingId, .tracking-event-trackingId-text"
        )
        if not tracking_id_el:
            return None

        result = {
            "tracking_id": None,
            "carrier": None,
            "status": None,
            "events": [],
        }

        # Tracking ID
        if tracking_id_el:
            text = (await tracking_id_el.inner_text()).strip()
            # Format: "Tracking ID: TBA330759513374"
            result["tracking_id"] = text.replace("Tracking ID:", "").strip()

        # Carrier
        carrier_el = await page.query_selector(".tracking-event-carrier-header, h3.a-spacing-small")
        if carrier_el:
            result["carrier"] = (await carrier_el.inner_text()).strip()

        # Primary status (e.g., "Delivered today")
        status_el = await page.query_selector("h1.pt-promise-main-slot, .milestone-primaryMessage")
        if status_el:
            result["status"] = (await status_el.inner_text()).strip()

        # Tracking events
        events = await page.evaluate("""() => {
            const results = [];
            let currentDate = null;

            // Date headers and events are siblings in the tracking modal
            const dateHeaders = document.querySelectorAll('.tracking-event-date-header');
            dateHeaders.forEach(header => {
                currentDate = header.textContent.trim();
            });

            // Get all events with their times, messages, and locations
            const times = document.querySelectorAll('.tracking-event-time');
            const messages = document.querySelectorAll('.tracking-event-message');
            const locations = document.querySelectorAll('.tracking-event-location');

            // Find date headers to associate with events
            const allDateHeaders = [...document.querySelectorAll('.tracking-event-date-header')];
            const allMessages = [...document.querySelectorAll('.tracking-event-message')];

            // Walk through the DOM to associate dates with events
            const container = document.querySelector('.tracking-events-modal-inner')
                || document.querySelector('[class*=tracking-event]')?.closest('div');

            if (container) {
                let date = null;
                const children = container.querySelectorAll(
                    '.tracking-event-date-header, .tracking-event-time-left, .tracking-event-message, .tracking-event-location'
                );
                let event = {};
                for (const child of children) {
                    if (child.classList.contains('tracking-event-date-header')) {
                        date = child.textContent.trim();
                    } else if (child.classList.contains('tracking-event-time-left')
                               || child.classList.contains('tracking-event-time')) {
                        if (event.message) {
                            results.push(event);
                            event = {};
                        }
                        event.date = date;
                        event.time = child.textContent.trim();
                    } else if (child.classList.contains('tracking-event-message')) {
                        event.message = child.textContent.trim();
                    } else if (child.classList.contains('tracking-event-location')) {
                        event.location = child.textContent.trim();
                    }
                }
                if (event.message) results.push(event);
            }

            return results;
        }""")
        if events:
            result["events"] = events

        return [result] if (result["tracking_id"] or result["events"]) else None

    async def close(self):
        """Shut down the browser."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None


# Singleton instance
amazon_session = AmazonSession()
