"""Costco provider — Playwright-based session management.

First run: launches a visible browser for manual login.
Subsequent runs: reuses saved session headlessly.
"""

import asyncio
import contextlib
import logging
from pathlib import Path
from urllib.parse import quote, urlencode

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from octo_satellite.config import settings

logger = logging.getLogger("octo_satellite.costco")

SESSION_DIR = Path(settings.costco_session_dir).expanduser()

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class CostcoSession:
    """Manages a persistent Playwright browser session for Costco."""

    def __init__(self):
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._lock = asyncio.Lock()

    @property
    def _session_exists(self) -> bool:
        return (SESSION_DIR / "state.json").exists()

    async def start(self, headless: bool | None = None) -> BrowserContext:
        if self._context:
            return self._context

        if headless is None:
            headless = self._session_exists

        SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=headless)

        storage_kwargs = {}
        if self._session_exists:
            storage_kwargs["storage_state"] = str(SESSION_DIR / "state.json")

        self._context = await self._browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/Los_Angeles",
            **storage_kwargs,
        )
        return self._context

    async def save_session(self):
        if self._context:
            state_file = SESSION_DIR / "state.json"
            await self._context.storage_state(path=str(state_file))
            with contextlib.suppress(OSError):
                state_file.chmod(0o600)

    async def _new_page(self) -> Page:
        ctx = await self.start(headless=True)
        return await ctx.new_page()

    async def _verify_authenticated(self, page: Page) -> bool:
        """Check if current page is authenticated (not on sign-in page)."""
        url = page.url.lower()
        if "logonform" in url or "signin" in url:
            return False
        # Check for account link as positive signal
        acct = await page.query_selector(
            'a[href*="/AccountHomeCmd"], a[href*="/myaccount"]'
        )
        return acct is not None

    # -- Login -----------------------------------------------------------------

    async def login(self) -> bool:
        """Launch a headed browser for manual Costco login."""
        async with self._lock:
            await self.close()
            SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=False)
            self._context = await self._browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
                timezone_id="America/Los_Angeles",
            )

            page = await self._context.new_page()
            await page.goto("https://www.costco.com/LogonForm")

            print("\n🔐 Please log in to Costco in the browser window.")
            print(
                "   Complete any verification if prompted."
                " This window will close once login is detected.\n"
            )

            try:
                # Wait for redirect away from login page
                while True:
                    url = page.url.lower()
                    if "logonform" not in url and "signin" not in url:
                        # Verify we actually landed on an authenticated page
                        acct = await page.query_selector(
                            'a[href*="/AccountHomeCmd"], a[href*="/myaccount"]'
                        )
                        if acct:
                            break
                    await page.wait_for_timeout(1000)
            except Exception:
                return False

            await page.wait_for_timeout(3000)
            await self.save_session()
            print("✅ Login detected! Session saved.")
            await page.close()
            await self.close()
            return True

    # -- Health / Auth ---------------------------------------------------------

    async def check_auth(self) -> dict:
        """Verify the saved session is still authenticated."""
        async with self._lock:
            page = await self._new_page()
            try:
                await page.goto(
                    "https://www.costco.com/myaccount",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(2000)

                authenticated = await self._verify_authenticated(page)
                name = None
                if authenticated:
                    name_el = await page.query_selector(
                        "#costco-header-account-name, .account-name, "
                        '.my-account-header [class*="name"]'
                    )
                    if name_el:
                        name = (await name_el.inner_text()).strip() or None
                    await self.save_session()

                return {"authenticated": authenticated, "name": name}
            finally:
                await page.close()

    async def heartbeat(self) -> bool:
        """Keep the session alive. Returns True if session is still valid."""
        async with self._lock:
            page = await self._new_page()
            try:
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
            finally:
                await page.close()

    # -- Orders ----------------------------------------------------------------

    async def get_orders(self, page_num: int = 1) -> dict:
        """Fetch orders from Costco order history."""
        async with self._lock:
            page = await self._new_page()
            try:
                url = f"https://www.costco.com/OrderStatusCmd?pageNum={page_num}"
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

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
            finally:
                await page.close()

    async def _scrape_order_list(self, page: Page) -> list[dict]:
        """Extract order info from Costco order history page."""
        return await page.evaluate("""() => {
            const orders = [];
            // Costco renders order cards with order number, date, total, status
            const cards = document.querySelectorAll(
                '.order-card, .order-tile, [class*="orderCard"], [class*="order-history-item"]'
            );
            for (const card of cards) {
                const order = {
                    order_id: null,
                    date: null,
                    total: null,
                    status: null,
                    items: []
                };

                // Order number — look for links or text with order ID patterns
                const orderLink = card.querySelector(
                    'a[href*="OrderStatusDetailView"], a[href*="orderId"]'
                );
                if (orderLink) {
                    const match = orderLink.href.match(/orderId=([^&]+)/i)
                        || orderLink.href.match(/orderNumber=([^&]+)/i);
                    if (match) order.order_id = match[1];
                    if (!order.order_id) {
                        const text = orderLink.textContent.trim();
                        if (/^\\d{5,}$/.test(text)) order.order_id = text;
                    }
                }

                // Fallback: any text that looks like an order number
                if (!order.order_id) {
                    const allText = card.textContent;
                    const numMatch = allText.match(/Order\\s*#?\\s*(\\d{5,})/i);
                    if (numMatch) order.order_id = numMatch[1];
                }

                // Date
                const dateMatch = card.textContent.match(
                    /(?:Ordered|Placed|Date)[:\\s]*([A-Z][a-z]+ \\d{1,2},? \\d{4})/i
                );
                if (dateMatch) order.date = dateMatch[1];

                // Total
                const totalMatch = card.textContent.match(
                    /(?:Total|Amount)[:\\s]*\\$(\\d[\\d,.]+)/i
                );
                if (totalMatch) order.total = '$' + totalMatch[1];

                // Status
                const statusEl = card.querySelector(
                    '[class*="status"], [class*="tracking"], .order-status'
                );
                if (statusEl) order.status = statusEl.textContent.trim();

                // Item names
                const itemEls = card.querySelectorAll(
                    '[class*="product-name"], [class*="item-name"], [class*="productTitle"]'
                );
                for (const el of itemEls) {
                    const text = el.textContent.trim();
                    if (text && !order.items.includes(text)) order.items.push(text);
                }

                if (order.order_id || order.items.length) {
                    orders.push(order);
                }
            }
            return orders;
        }""")

    async def get_order(self, order_id: str) -> dict | None:
        """Fetch details for a specific Costco order."""
        async with self._lock:
            page = await self._new_page()
            try:
                params = urlencode({"orderId": order_id})
                url = f"https://www.costco.com/OrderStatusDetailView?{params}"
                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                if not await self._verify_authenticated(page):
                    return None

                order = await self._scrape_order_detail(page, order_id)
                await self.save_session()
                return order
            finally:
                await page.close()

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
            finally:
                await page.close()

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
                product_link = await page.query_selector(
                    f'a[href*=".product.{item_number}.html"]'
                )
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
                    'span[itemprop="name"], .product-title, h1[class*="product"]'
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
                    '.out-of-stock-message, .oos-overlay, '
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
                    '#add-to-cart-btn:not([disabled]), '
                    'button[data-testid="add-to-cart"]:not([disabled]), '
                    '#add-to-cart-button:not([disabled]), '
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

                # Verify success — look for cart confirmation modal or redirect
                confirm = await page.query_selector(
                    '[class*="added-to-cart"], [class*="cart-confirm"], '
                    '[class*="add-to-cart-success"], [class*="modal"] [class*="cart"]'
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
            finally:
                await page.close()

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
                    '.modal button.primary'
                )
                if confirm_btn:
                    await confirm_btn.click()
                    await page.wait_for_timeout(2000)

                await self.save_session()
                return {"success": True, "item_id": item_id}
            except Exception as e:
                logger.error(f"remove_from_cart failed: {e}")
                return {"success": False, "error": str(e)}
            finally:
                await page.close()

    # -- Search ----------------------------------------------------------------

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
            finally:
                await page.close()

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
                product_link = await page.query_selector(
                    f'a[href*=".product.{item_number}.html"]'
                )
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
            finally:
                await page.close()

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
costco_session = CostcoSession()
