"""Costco provider — Chrome CDP session management.

Connects to a real Chrome browser via Chrome DevTools Protocol to bypass
Akamai bot detection. Chrome is launched with a dedicated profile directory
so cookies/session persist across restarts.
"""

import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote, urlencode

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from octo_satellite.config import settings

logger = logging.getLogger("octo_satellite.costco")

SESSION_DIR = Path(settings.costco_session_dir).expanduser()

# Dedicated Chrome profile for Costco (separate from user's default profile)
CHROME_PROFILE_DIR = SESSION_DIR / "chrome-profile"

CDP_PORT = 9222


def _find_chrome() -> str:
    """Find the Chrome executable on the system."""
    # Try common names in PATH
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "msedge"):
        path = shutil.which(name)
        if path:
            return path

    # Windows default locations
    for candidate in (
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ):
        if candidate.exists():
            return str(candidate)

    raise FileNotFoundError("Chrome not found. Install Google Chrome or set it in your PATH.")


class CostcoSession:
    """Manages a Costco session via Chrome CDP.

    Launches a real Chrome instance with remote debugging and connects
    via Playwright CDP. This bypasses Akamai bot detection entirely
    since it's a genuine browser, not an automation-controlled one.
    """

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._chrome_process: subprocess.Popen | None = None
        self._lock = asyncio.Lock()

    def _launch_chrome(self):
        """Launch Chrome with remote debugging if not already running."""
        if self._chrome_process and self._chrome_process.poll() is None:
            return

        CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        chrome = _find_chrome()
        logger.info("Launching Chrome from %s with CDP on port %s", chrome, CDP_PORT)

        self._chrome_process = subprocess.Popen(
            [
                chrome,
                f"--remote-debugging-port={CDP_PORT}",
                f"--user-data-dir={CHROME_PROFILE_DIR}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def start(self) -> BrowserContext:
        """Connect to Chrome via CDP, launching it if needed."""
        if self._context:
            return self._context

        SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._launch_chrome()

        # Give Chrome a moment to start the CDP server
        await asyncio.sleep(2)

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.connect_over_cdp(
            f"http://localhost:{CDP_PORT}"
        )
        self._context = self._browser.contexts[0]
        return self._context

    async def save_session(self):
        # Cookies persist automatically in Chrome's profile directory.
        pass

    async def _new_page(self) -> Page:
        """Return the reusable page, creating one only if needed."""
        ctx = await self.start()
        if self._page and not self._page.is_closed():
            return self._page
        # Reuse Chrome's existing tab if available
        if ctx.pages:
            self._page = ctx.pages[0]
        else:
            self._page = await ctx.new_page()
        return self._page

    async def _verify_authenticated(self, page: Page) -> bool:
        """Check if current page is authenticated (not on sign-in page)."""
        url = page.url.lower()
        logger.info(f"Auth check URL: {page.url}")
        if "logonform" in url or "signin" in url:
            logger.info("Auth check: on sign-in page")
            return False
        # Check for account link as positive signal
        acct = await page.query_selector('a[href*="/AccountHomeCmd"], a[href*="/myaccount"]')
        if not acct:
            # Broader fallback: look for sign-in link absence as negative signal
            sign_in = await page.query_selector('a[href*="/LogonForm"], a[id="header_sign_in"]')
            if sign_in:
                logger.info("Auth check: sign-in link found — not authenticated")
                return False
            # If neither account nor sign-in link found, check page content
            body_text = await page.evaluate(
                "() => document.body?.innerText?.substring(0, 500) || ''"
            )
            logger.info(f"Auth check: no account/sign-in link found. Body: {body_text[:200]}")
            return False
        logger.info("Auth check: account link found — authenticated")
        return True

    # -- Login -----------------------------------------------------------------

    async def login(self) -> bool:
        """Launch Chrome via CDP for manual Costco login."""
        async with self._lock:
            await self.close()

            ctx = await self.start()
            page = await ctx.new_page()
            await page.goto("https://www.costco.com")

            print("\n🔐 Please log in to Costco in the browser window.")
            print("   Click 'Sign In' on the Costco homepage and complete login.")
            print("   This window will close once login is detected.\n")

            try:
                # Wait for user to complete login
                while True:
                    url = page.url.lower()
                    if "logonform" not in url and "signin" not in url and "oauth" not in url:
                        # Check if we see an account link (positive auth signal)
                        acct = await page.query_selector(
                            'a[href*="/AccountHomeCmd"], a[href*="/myaccount"]'
                        )
                        if acct:
                            break
                    await page.wait_for_timeout(1000)
            except Exception:
                return False

            # Let cookies settle after login redirect
            await page.wait_for_timeout(5000)

            # Log what cookies we captured
            cookies = await self._context.cookies()
            cookie_names = [c["name"] for c in cookies]
            logger.info(f"Login: captured {len(cookies)} cookies: {cookie_names}")

            print("✅ Login detected! Session saved in Chrome profile.")
            await page.close()
            return True

    # -- Health / Auth ---------------------------------------------------------

    async def check_auth(self) -> dict:
        """Verify the saved session is still authenticated."""
        async with self._lock:
            page = await self._new_page()
            await page.goto(
                "https://www.costco.com",
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(3000)

            authenticated = await self._verify_authenticated(page)
            name = None
            if authenticated:
                name_el = await page.query_selector(
                    '#costco-header-account-name, .account-name, .my-account-header [class*="name"]'
                )
                if name_el:
                    name = (await name_el.inner_text()).strip() or None
                await self.save_session()

            return {"authenticated": authenticated, "name": name}

    async def heartbeat(self) -> bool:
        """Keep the session alive. Returns True if session is still valid."""
        async with self._lock:
            page = await self._new_page()
            await page.goto(
                "https://www.costco.com/myaccount",
                wait_until="domcontentloaded",
            )
            await page.wait_for_timeout(2000)

            if not await self._verify_authenticated(page):
                logger.warning("Heartbeat: session expired!")
                return False

            await self.save_session()
            logger.info("Heartbeat: session alive")
            return True

    # -- Orders ----------------------------------------------------------------

    async def get_orders(self, page_num: int = 1) -> dict:
        """Fetch orders from Costco order history."""
        async with self._lock:
            page = await self._new_page()
            url = "https://www.costco.com/myaccount/#/app/4900eb1f-0c10-4bd9-99c3-c59e6c1ecebf/ordersandpurchases"
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(8000)

            if not await self._verify_authenticated(page):
                return {
                    "total_count": 0,
                    "page": page_num,
                    "total_pages": 0,
                    "orders": None,
                    "error": "not_authenticated",
                }

            orders = await self._scrape_order_list(page)
            total_count = len(orders)
            await self.save_session()

            return {
                "total_count": total_count,
                "page": page_num,
                "total_pages": 1,
                "orders": orders,
                "error": None,
            }

    async def _scrape_order_list(self, page: Page) -> list[dict]:
        """Extract order info from Costco myaccount order history (MUI SPA)."""
        return await page.evaluate("""() => {
            const orders = [];
            // Each order card has a link with automation-id="OnlineOrdersViewOrchangeOrder"
            // and an id like "orderNumber_XXXXXXXXXX"
            const orderLinks = document.querySelectorAll(
                'a[automation-id="OnlineOrdersViewOrchangeOrder"]'
            );
            // Deduplicate by order ID (multiple links per order)
            const seen = new Set();
            for (const link of orderLinks) {
                const idAttr = link.id || '';
                const match = idAttr.match(/orderNumber_(\\d+)/);
                if (!match || seen.has(match[1])) continue;
                const orderId = match[1];
                seen.add(orderId);

                const order = {
                    order_id: orderId,
                    date: null,
                    total: null,
                    status: null,
                    items: [],
                    tracking: []
                };

                // Date — element with id="orderDate_XXXXXXXXXX"
                const dateEl = document.getElementById('orderDate_' + orderId);
                if (dateEl) order.date = dateEl.textContent.trim();

                // Total — element with id="totalPrice_XXXXXXXXXX"
                const totalEl = document.getElementById('totalPrice_' + orderId);
                if (totalEl) {
                    const m = totalEl.textContent.match(/\\$(\\d[\\d,.]+)/);
                    if (m) order.total = '$' + m[1];
                }

                // Walk up to the card container (css-z91irn) for items/status
                let card = link;
                while (card && !(card.className && card.className.includes('css-z91irn'))) {
                    card = card.parentElement;
                }
                if (!card) continue;

                // Status — shipped/delivered lines
                const statusHeaders = card.querySelectorAll(
                    '.MuiTypography-t4'
                );
                const statuses = [];
                for (const h of statusHeaders) {
                    const txt = h.textContent.trim();
                    if (txt.match(/^(Shipped|Delivered|Processing|Cancelled)/i)) {
                        statuses.push(txt.replace(/Order \\d+/, '').trim());
                    }
                }
                if (statuses.length) order.status = statuses[0];

                // Item names — product links to costco.com product pages
                const itemLinks = card.querySelectorAll(
                    'a[href*="costco.com/"][href*=".product."]'
                );
                for (const il of itemLinks) {
                    const text = il.textContent.trim();
                    if (text && text.length > 3 && !order.items.includes(text)) {
                        order.items.push(text);
                    }
                }

                // Tracking numbers — links whose text looks like a tracking number
                const allLinks = card.querySelectorAll('a');
                for (const tl of allLinks) {
                    const txt = tl.textContent.trim();
                    if (txt && /^#?[A-Z0-9]{10,}$/.test(txt)) {
                        order.tracking.push(txt.replace(/^#/, ''));
                    }
                }

                orders.push(order);
            }
            return orders;
        }""")

    async def get_order(self, order_id: str) -> dict | None:
        """Fetch details for a specific Costco order."""
        async with self._lock:
            page = await self._new_page()
            params = urlencode({"orderId": order_id})
            url = f"https://www.costco.com/OrderStatusDetailView?{params}"
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            if not await self._verify_authenticated(page):
                return None

            order = await self._scrape_order_detail(page, order_id)
            await self.save_session()
            return order

    async def _scrape_order_detail(self, page: Page, order_id: str) -> dict:
        """Extract order detail info from Costco order detail page."""
        return await page.evaluate(
            """(orderId) => {
            const order = {
                order_id: orderId,
                date: null,
                total: null,
                status: null,
                items: [],
                shipping_address: null,
                tracking: null,
            };

            const body = document.body.innerText;

            // Date
            const dateMatch = body.match(
                /(?:Order(?:ed)?|Placed)[:\\s]+([A-Z][a-z]+ \\d{1,2},? \\d{4})/i
            );
            if (dateMatch) order.date = dateMatch[1];

            // Total
            const totalMatch = body.match(
                /(?:Order Total|Total)[:\\s]*\\$(\\d[\\d,.]+)/i
            );
            if (totalMatch) order.total = '$' + totalMatch[1];

            // Status
            const statusEl = document.querySelector(
                '[class*="shipment-status"], [class*="delivery-status"], '
                + '[class*="order-status"], [class*="tracking-status"]'
            );
            if (statusEl) order.status = statusEl.textContent.trim();

            // Items
            const itemEls = document.querySelectorAll(
                '[class*="product-name"], [class*="item-description"], '
                + '[class*="productTitle"], .product-title'
            );
            for (const el of itemEls) {
                const text = el.textContent.trim();
                if (text && text.length > 3 && !order.items.some(i => i.title === text)) {
                    order.items.push({ title: text });
                }
            }

            // Shipping address
            const addrEl = document.querySelector(
                '[class*="shipping-address"], [class*="ship-to"], '
                + '[class*="delivery-address"]'
            );
            if (addrEl) {
                order.shipping_address = addrEl.textContent.trim()
                    .replace(/\\s+/g, ' ');
            }

            // Tracking
            const trackEl = document.querySelector(
                'a[href*="tracking"], [class*="tracking-number"]'
            );
            if (trackEl) {
                order.tracking = trackEl.textContent.trim();
            }

            return order;
        }""",
            order_id,
        )

    # -- Cart ------------------------------------------------------------------

    async def get_cart(self) -> dict:
        """Scrape current Costco cart contents."""
        async with self._lock:
            page = await self._new_page()
            try:
                await page.goto(
                    "https://www.costco.com/CheckoutCartDisplayView",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(3000)

                if not await self._verify_authenticated(page):
                    return {"items": [], "subtotal": None, "error": "not_authenticated"}

                result = await self._scrape_cart(page)
                await self.save_session()
                return result
            except Exception as e:
                logger.error(f"get_cart failed: {e}")
                return {"items": [], "subtotal": None, "error": str(e)}

    async def _scrape_cart(self, page: Page) -> dict:
        """Extract cart items from Costco cart page."""
        return await page.evaluate("""() => {
            const items = [];

            // Costco cart items
            const itemEls = document.querySelectorAll(
                '[class*="cart-item"], [class*="product-list"] [class*="item"], '
                + '.cart-product, [data-testid*="cart-item"]'
            );
            for (const el of itemEls) {
                const titleEl = el.querySelector(
                    '[class*="product-name"] a, [class*="item-name"] a, '
                    + '[class*="productTitle"], .product-title a'
                );
                const title = titleEl ? titleEl.textContent.trim() : null;
                if (!title) continue;

                const priceEl = el.querySelector(
                    '[class*="price"], [class*="your-price"]'
                );
                const price = priceEl ? priceEl.textContent.trim() : null;

                const qtyEl = el.querySelector(
                    'input[name*="quantity"], select[name*="quantity"], '
                    + '[class*="quantity"] input'
                );
                const quantity = qtyEl ? (parseInt(qtyEl.value) || 1) : 1;

                // Item number from product link or data attribute
                let item_number = null;
                if (titleEl && titleEl.href) {
                    const match = titleEl.href.match(/\\.product\\.(\\d+)\\.html/);
                    if (match) item_number = match[1];
                }
                if (!item_number) {
                    const numEl = el.querySelector('[class*="item-number"], [class*="sku"]');
                    if (numEl) {
                        const m = numEl.textContent.match(/(\\d{5,})/);
                        if (m) item_number = m[1];
                    }
                }

                // Cart item ID for removal
                let item_id = el.getAttribute('data-itemid')
                    || el.getAttribute('data-product-id')
                    || el.getAttribute('id');

                items.push({
                    item_number: item_number,
                    item_id: item_id,
                    title: title,
                    price: price,
                    quantity: quantity,
                });
            }

            // Subtotal
            const subtotalEl = document.querySelector(
                '[class*="order-summary"] [class*="subtotal"] [class*="value"], '
                + '[class*="subtotal-amount"], .subtotal .value'
            );
            const subtotal = subtotalEl ? subtotalEl.textContent.trim() : null;

            return { items, subtotal, error: null };
        }""")

    async def add_to_cart(self, item_number: str) -> dict:
        """Add a product to cart by Costco item number."""
        async with self._lock:
            page = await self._new_page()
            try:
                url = f"https://www.costco.com/CatalogSearch?keyword={quote(item_number)}"
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                if not await self._verify_authenticated(page):
                    return {"success": False, "error": "not_authenticated"}

                # Find the product link from search results and navigate to it
                product_link = await page.query_selector(f'a[href*=".product.{item_number}.html"]')
                if not product_link:
                    # Try direct product URL pattern
                    await page.goto(
                        f"https://www.costco.com/.product.{quote(item_number)}.html",
                        wait_until="domcontentloaded",
                    )
                    await page.wait_for_timeout(2000)
                else:
                    await product_link.click()
                    await page.wait_for_timeout(2000)

                # Get product title
                title_el = await page.query_selector(
                    'h1, span[itemprop="name"], .product-title, h1[class*="product"]'
                )
                title = None
                if title_el:
                    title = (await title_el.inner_text()).strip()

                if not title:
                    return {
                        "success": False,
                        "error": "product_not_found",
                        "item_number": item_number,
                    }

                # Check availability
                oos = await page.query_selector(
                    ".out-of-stock-message, .oos-overlay, "
                    '[class*="out-of-stock"], [class*="outOfStock"]'
                )
                if oos:
                    return {
                        "success": False,
                        "error": "out_of_stock",
                        "title": title,
                        "item_number": item_number,
                    }

                # Find and click Add to Cart
                atc = await page.query_selector(
                    "#Button_addToCartDrawer_pdp, "
                    "#add-to-cart-btn:not([disabled]), "
                    'button[data-testid="add-to-cart"]:not([disabled]), '
                    "#add-to-cart-button:not([disabled]), "
                    'input[value="Add to Cart"]:not([disabled])'
                )
                if not atc:
                    return {
                        "success": False,
                        "error": "not_directly_addable",
                        "title": title,
                        "item_number": item_number,
                    }

                await atc.click()
                await page.wait_for_timeout(3000)

                # Verify success — look for cart confirmation drawer
                confirm = await page.query_selector(
                    '[role="dialog"]:has-text("Added to Cart"), '
                    '.MuiDrawer-root:has-text("Added to Cart"), '
                    '[class*="added-to-cart"], [class*="cart-confirm"]'
                )
                success = confirm is not None or "cart" in page.url.lower()

                if success:
                    await self.save_session()

                return {
                    "success": success,
                    "item_number": item_number,
                    "title": title,
                }
            except Exception as e:
                logger.error(f"add_to_cart failed: {e}")
                return {"success": False, "error": str(e)}

    async def remove_from_cart(self, item_id: str) -> dict:
        """Remove an item from cart by item_id."""
        async with self._lock:
            page = await self._new_page()
            try:
                await page.goto(
                    "https://www.costco.com/CheckoutCartDisplayView",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(3000)

                if not await self._verify_authenticated(page):
                    return {"success": False, "error": "not_authenticated"}

                # Find remove/delete button for this item
                delete_btn = await page.query_selector(
                    f'[data-itemid="{item_id}"] button[class*="remove"], '
                    f'[data-itemid="{item_id}"] [class*="delete"], '
                    f'[data-product-id="{item_id}"] button[class*="remove"], '
                    f'#{item_id} button[class*="remove"]'
                )
                if not delete_btn:
                    # Fallback: find by aria-label or text
                    delete_btn = await page.query_selector(
                        f'button[aria-label*="Remove"][data-id="{item_id}"]'
                    )

                if not delete_btn:
                    return {"success": False, "error": "item_not_found"}

                await delete_btn.click()
                await page.wait_for_timeout(2000)

                # Confirm removal if a dialog appears
                confirm_btn = await page.query_selector(
                    'button[class*="confirm-remove"], '
                    'button[data-testid*="confirm"], '
                    ".modal button.primary"
                )
                if confirm_btn:
                    await confirm_btn.click()
                    await page.wait_for_timeout(2000)

                await self.save_session()
                return {"success": True, "item_id": item_id}
            except Exception as e:
                logger.error(f"remove_from_cart failed: {e}")
                return {"success": False, "error": str(e)}

    # -- Search----------------------------------------------------------------

    async def search(self, query: str, page_num: int = 1) -> dict:
        """Search Costco products."""
        async with self._lock:
            page = await self._new_page()
            try:
                params = urlencode({"keyword": query, "currentPage": page_num})
                url = f"https://www.costco.com/CatalogSearch?{params}"
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                if not await self._verify_authenticated(page):
                    return {"results": [], "error": "not_authenticated"}

                return await self._scrape_search(page, page_num)
            except Exception as e:
                logger.error(f"search failed: {e}")
                return {"results": [], "error": str(e)}

    async def _scrape_search(self, page: Page, page_num: int) -> dict:
        """Extract search results from Costco search page."""
        data = await page.evaluate("""() => {
            const results = [];

            const productEls = document.querySelectorAll(
                '.product-tile, [class*="product-card"], '
                + '.product, [data-testid*="product"]'
            );
            for (const el of productEls) {
                const titleEl = el.querySelector(
                    'a[class*="product-title"], .description a, '
                    + '[class*="product-name"] a, a[href*=".product."]'
                );
                const title = titleEl ? titleEl.textContent.trim() : null;
                if (!title) continue;

                let item_number = null;
                if (titleEl && titleEl.href) {
                    const match = titleEl.href.match(/\\.product\\.(\\d+)\\.html/);
                    if (match) item_number = match[1];
                }

                const priceEl = el.querySelector(
                    '[class*="price"], [automation-id*="price"]'
                );
                const price = priceEl ? priceEl.textContent.trim() : null;

                const ratingEl = el.querySelector(
                    '[class*="rating"], [class*="star"]'
                );
                const rating = ratingEl
                    ? parseFloat(ratingEl.textContent || ratingEl.getAttribute('aria-label'))
                    : null;

                const imgEl = el.querySelector('img[src*="costco"], img.product-image');
                const image = imgEl ? imgEl.getAttribute('src') : null;

                results.push({
                    item_number: item_number,
                    title: title,
                    price: price,
                    rating: isNaN(rating) ? null : rating,
                    image: image,
                });
            }

            // Pagination
            const nextBtn = document.querySelector(
                'a[class*="next"]:not(.disabled), '
                + 'button[class*="next"]:not([disabled]), '
                + '[aria-label="Next"]'
            );
            const hasNext = !!nextBtn;

            return { results, has_next: hasNext };
        }""")

        data["page"] = page_num
        data["error"] = None
        return data

    # -- Product Detail --------------------------------------------------------

    async def get_product(self, item_number: str) -> dict | None:
        """Get product details by Costco item number."""
        async with self._lock:
            page = await self._new_page()
            try:
                url = f"https://www.costco.com/CatalogSearch?keyword={quote(item_number)}"
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                # Try to find and click through to the product page
                product_link = await page.query_selector(f'a[href*=".product.{item_number}.html"]')
                if product_link:
                    await product_link.click()
                    await page.wait_for_timeout(2000)
                else:
                    # Try direct URL
                    await page.goto(
                        f"https://www.costco.com/.product.{quote(item_number)}.html",
                        wait_until="domcontentloaded",
                    )
                    await page.wait_for_timeout(2000)

                if not await self._verify_authenticated(page):
                    return None

                return await self._scrape_product(page, item_number)
            except Exception as e:
                logger.error(f"get_product failed: {e}")
                return None

    async def _scrape_product(self, page: Page, item_number: str) -> dict | None:
        """Extract product details from Costco product page."""
        return await page.evaluate(
            """(itemNumber) => {
            const titleEl = document.querySelector(
                'span[itemprop="name"], .product-title, '
                + 'h1[class*="product"], h1[automation-id*="productName"]'
            );
            if (!titleEl) return null;

            const priceEl = document.querySelector(
                'span.value[automation-id="productPriceOutput"], '
                + '[class*="your-price"] [class*="value"], '
                + '[itemprop="price"]'
            );

            const ratingEl = document.querySelector(
                '[itemprop="ratingValue"], [class*="rating-value"]'
            );
            const reviewCountEl = document.querySelector(
                '[itemprop="reviewCount"], [class*="review-count"]'
            );

            const skuEl = document.querySelector(
                'span[itemprop="sku"], [class*="item-number"]'
            );

            const features = [];
            document.querySelectorAll(
                'ul.pdp-features li, [class*="product-features"] li, '
                + '[class*="product-info"] li'
            ).forEach(li => {
                const text = li.textContent.trim();
                if (text) features.push(text);
            });

            const imgEl = document.querySelector(
                '#initialProductImage img, .product-image img, '
                + 'img[itemprop="image"]'
            );
            const image = imgEl ? imgEl.getAttribute('src') : null;

            const descEl = document.querySelector(
                '[itemprop="description"], .product-description, '
                + '[class*="product-detail-description"]'
            );

            const addable = !!document.querySelector(
                '#add-to-cart-btn:not([disabled]), '
                + 'button[data-testid="add-to-cart"]:not([disabled])'
            );

            const oos = !!document.querySelector(
                '.out-of-stock-message, .oos-overlay, '
                + '[class*="out-of-stock"], [class*="outOfStock"]'
            );

            return {
                item_number: skuEl
                    ? (skuEl.getAttribute('data-sku') || skuEl.textContent.trim().replace(/[^\\d]/g, ''))
                    : itemNumber,
                title: titleEl.textContent.trim(),
                price: priceEl ? priceEl.textContent.trim() : null,
                rating: ratingEl ? parseFloat(ratingEl.textContent) : null,
                review_count: reviewCountEl ? reviewCountEl.textContent.trim() : null,
                features: features,
                image: image,
                description: descEl ? descEl.textContent.trim() : null,
                directly_addable: addable,
                out_of_stock: oos,
            };
        }""",
            item_number,
        )

    # -- Lifecycle -------------------------------------------------------------

    async def close(self):
        """Disconnect from Chrome CDP (does not kill Chrome)."""
        self._context = None
        if self._browser:
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def shutdown(self):
        """Full shutdown — disconnect CDP and kill the Chrome process."""
        await self.close()
        if self._chrome_process and self._chrome_process.poll() is None:
            self._chrome_process.terminate()
            self._chrome_process.wait(timeout=5)
            self._chrome_process = None


# Singleton instance
costco_session = CostcoSession()
