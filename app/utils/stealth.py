"""
Stealth configuration for Playwright to avoid bot detection
"""
import asyncio
import random
from typing import Optional


class StealthConfig:
    """Configuration for stealth browser automation"""
    
    # Random delays range (seconds)
    MIN_DELAY = 0.5
    MAX_DELAY = 2.0
    
    # Mouse movement steps
    MOUSE_STEPS_MIN = 20
    MOUSE_STEPS_MAX = 50
    
    @staticmethod
    async def apply_stealth(page):
        """
        Apply stealth patches to page to avoid detection
        
        Args:
            page: Playwright page object
        """
        # Inject stealth scripts
        await page.add_init_script("""
            // Override navigator.webdriver
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Override navigator.plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Override navigator.languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            
            // Override WebGL vendor
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {
                if (parameter === 37445) {
                    return 'Intel Inc.';
                }
                if (parameter === 37446) {
                    return 'Intel Iris OpenGL Engine';
                }
                return getParameter.apply(this, arguments);
            };
            
            // Override Chrome detection
            window.chrome = {
                runtime: {}
            };
            
            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );
            
            // Override plugins length
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const plugins = [
                        {
                            name: 'Chrome PDF Plugin',
                            description: 'Portable Document Format',
                            filename: 'internal-pdf-viewer'
                        },
                        {
                            name: 'Chrome PDF Viewer',
                            description: '',
                            filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'
                        },
                        {
                            name: 'Native Client',
                            description: '',
                            filename: 'internal-nacl-plugin'
                        }
                    ];
                    plugins.item = (index) => plugins[index];
                    plugins.namedItem = (name) => plugins.find(p => p.name === name);
                    plugins.refresh = () => {};
                    return plugins;
                }
            });
            
            // Hide automation indicators
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_JSON;
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_Object;
            
            // Override permissions API
            const originalPermissions = window.navigator.permissions;
            window.navigator.permissions = {
                query: (parameters) => {
                    return Promise.resolve({ state: 'granted' });
                }
            };
        """)
        
        # Set additional context
        await page.set_extra_http_headers({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
    
    @staticmethod
    async def human_delay(min_seconds: Optional[float] = None, max_seconds: Optional[float] = None):
        """
        Add random human-like delay
        
        Args:
            min_seconds: Minimum delay (default from config)
            max_seconds: Maximum delay (default from config)
        """
        min_s = min_seconds or StealthConfig.MIN_DELAY
        max_s = max_seconds or StealthConfig.MAX_DELAY
        delay = random.uniform(min_s, max_s)
        await asyncio.sleep(delay)
    
    @staticmethod
    async def human_mouse_move(page, target_x: int, target_y: int):
        """
        Move mouse to target with human-like curved path
        
        Args:
            page: Playwright page
            target_x: Target X coordinate
            target_y: Target Y coordinate
        """
        # Get current position (assume starting from random position)
        start_x = random.randint(100, 500)
        start_y = random.randint(100, 500)
        
        # Calculate steps
        steps = random.randint(
            StealthConfig.MOUSE_STEPS_MIN,
            StealthConfig.MOUSE_STEPS_MAX
        )
        
        # Generate bezier curve points for natural movement
        points = StealthConfig._generate_bezier_curve(
            start_x, start_y, target_x, target_y, steps
        )
        
        # Move mouse along the path
        for x, y in points:
            await page.mouse.move(x, y)
            await asyncio.sleep(random.uniform(0.001, 0.003))
    
    @staticmethod
    def _generate_bezier_curve(x0, y0, x1, y1, steps: int):
        """
        Generate bezier curve for natural mouse movement
        
        Args:
            x0, y0: Start position
            x1, y1: End position
            steps: Number of steps
            
        Returns:
            List of (x, y) coordinates
        """
        # Control points for bezier curve
        cx1 = x0 + (x1 - x0) * random.uniform(0.2, 0.4)
        cy1 = y0 + (y1 - y0) * random.uniform(0.1, 0.3)
        cx2 = x0 + (x1 - x0) * random.uniform(0.6, 0.8)
        cy2 = y0 + (y1 - y0) * random.uniform(0.7, 0.9)
        
        points = []
        for i in range(steps):
            t = i / steps
            # Cubic bezier formula
            x = (1-t)**3 * x0 + 3*(1-t)**2*t * cx1 + 3*(1-t)*t**2 * cx2 + t**3 * x1
            y = (1-t)**3 * y0 + 3*(1-t)**2*t * cy1 + 3*(1-t)*t**2 * cy2 + t**3 * y1
            points.append((int(x), int(y)))
        
        return points
    
    @staticmethod
    async def human_click(page, selector: str):
        """
        Perform human-like click with mouse movement and random delays
        
        Args:
            page: Playwright page
            selector: Element selector
        """
        # Wait for element
        element = await page.wait_for_selector(selector)
        
        # Get element position
        box = await element.bounding_box()
        if not box:
            await element.click()
            return
        
        # Calculate target position (center with random offset)
        target_x = box['x'] + box['width'] / 2 + random.randint(-5, 5)
        target_y = box['y'] + box['height'] / 2 + random.randint(-5, 5)
        
        # Move mouse naturally
        await StealthConfig.human_mouse_move(page, target_x, target_y)
        
        # Random delay before click
        await StealthConfig.human_delay(0.1, 0.3)
        
        # Click
        await page.mouse.click(target_x, target_y)
        
        # Random delay after click
        await StealthConfig.human_delay(0.2, 0.5)
    
    @staticmethod
    async def human_scroll(page, direction: str = 'down', distance: int = 500):
        """
        Perform human-like scroll with random pauses
        
        Args:
            page: Playwright page
            direction: 'down' or 'up'
            distance: Scroll distance in pixels
        """
        delta = distance if direction == 'down' else -distance
        
        # Break into smaller scrolls
        num_scrolls = random.randint(3, 7)
        scroll_per_step = delta // num_scrolls
        
        for _ in range(num_scrolls):
            await page.mouse.wheel(0, scroll_per_step)
            await StealthConfig.human_delay(0.1, 0.3)
    
    @staticmethod
    async def random_mouse_movements(page, num_moves: int = 3):
        """
        Perform random mouse movements to simulate human behavior
        
        Args:
            page: Playwright page
            num_moves: Number of random movements
        """
        viewport = page.viewport_size
        if not viewport:
            return
        
        for _ in range(num_moves):
            x = random.randint(0, viewport['width'])
            y = random.randint(0, viewport['height'])
            await StealthConfig.human_mouse_move(page, x, y)
            await StealthConfig.human_delay(0.2, 0.5)


async def create_stealth_page(browser):
    """
    Create a new page with stealth configuration
    
    Args:
        browser: Playwright browser instance
        
    Returns:
        Configured page with stealth patches
    """
    # Create new context with realistic settings
    context = await browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        locale='en-US',
        timezone_id='America/New_York',
        geolocation={'latitude': 40.7128, 'longitude': -74.0060},
        permissions=['geolocation'],
    )
    
    page = await context.new_page()
    
    # Apply stealth patches
    await StealthConfig.apply_stealth(page)
    
    return page