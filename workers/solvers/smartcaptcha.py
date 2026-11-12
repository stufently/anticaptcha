"""Yandex SmartCaptcha widget mechanics and vision LLM text challenges."""
import asyncio
import contextvars
import time
from typing import Optional

from playwright.async_api import Error as PlaywrightError

from app.utils.browser import browser_manager
from app.utils.captcha_solver import BaseSolver
from workers.classifiers.vision_llm import VisionLLMClassifier
from workers.solvers.proxy import parse_proxy
from workers.solvers.url_guard import validate_page_url
from workers.solvers.widget_page import check_browser_input, install_widget_page

DEADLINE_SECONDS = 75
MAX_TEXT_ROUNDS = 3
MAX_ACTIONS = 4
ACTION_WAIT_SECONDS = 5
INVISIBLE_DELAY_SECONDS = 3
POLL_INTERVAL = 0.2
MOUSE_UP_SECONDS = 1.0
_deadline = contextvars.ContextVar('smartcaptcha_deadline', default=None)
CHECKBOX_FRAME = 'iframe[data-testid="checkbox-iframe"]'


async def _bounded(operation):
    """Bound every browser roundtrip, including locator and mouse operations."""
    deadline = _deadline.get()
    remaining = DEADLINE_SECONDS if deadline is None else deadline - time.monotonic()
    return await asyncio.wait_for(operation, max(0.5, remaining))


async def _within_action(operation, deadline):
    """All parts of one gesture share a short absolute deadline, with no floor."""
    return await asyncio.wait_for(operation, max(0, deadline - time.monotonic()))


class SmartCaptchaSolver(BaseSolver):
    def __init__(self):
        super().__init__()
        self.vision_classifier = None

    async def setup(self):
        self.vision_classifier = VisionLLMClassifier()

    async def cleanup(self):
        if self.vision_classifier is not None:
            self.vision_classifier.cleanup()

    async def solve(self, input_data) -> dict:
        site_key, page_url, render_mode = check_browser_input(input_data)
        page_url = await asyncio.to_thread(validate_page_url, page_url)
        proxy = await asyncio.to_thread(parse_proxy, input_data.get('proxy'))
        page = await browser_manager.new_page(stealth=True, proxy=proxy)
        try:
            if render_mode == 'widget':
                await install_widget_page(page, page_url, 'yandex_smartcaptcha', site_key)
            await page.goto(page_url, timeout=30000, wait_until='domcontentloaded')
            token = await self._poll(page)
            print(f'SmartCaptcha: received token ({len(token)} chars)')
            return {'token': token}
        finally:
            await browser_manager.close_page(page)

    async def _poll(self, page) -> str:
        loaded_at = time.monotonic()
        deadline = loaded_at + DEADLINE_SECONDS
        marker = _deadline.set(deadline)
        actions = 0
        next_action_at = loaded_at
        executed = False
        try:
            while time.monotonic() < deadline:
                try:
                    token = await self._read_token(page)
                    if token:
                        return token
                    if time.monotonic() >= deadline:
                        break
                    kind = await self._challenge_kind(page)
                    if kind:
                        token = await self._solve_challenge(page, kind)
                        if token is not None:
                            return token
                    if time.monotonic() >= deadline:
                        break
                    has_checkbox = bool(await _bounded(page.locator(CHECKBOX_FRAME).count()))
                    if not has_checkbox:
                        if not executed and time.monotonic() - loaded_at >= INVISIBLE_DELAY_SECONDS:
                            executed = await _bounded(page.evaluate("""() => {
                                if (window.smartCaptcha && typeof window.smartCaptcha.execute === 'function') {
                                    window.smartCaptcha.execute();
                                    return true;
                                }
                                return false;
                            }"""))
                        await asyncio.sleep(POLL_INTERVAL)
                        continue
                    # Keep polling tokens/challenges while the widget processes
                    # the last gesture. Both kinds of gesture share one budget.
                    if actions >= MAX_ACTIONS or time.monotonic() < next_action_at:
                        await asyncio.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
                        continue
                    frame = page.frame_locator(CHECKBOX_FRAME).first
                    thumb = frame.locator('.SliderCaptcha [data-testid="thumb"]').first
                    slider = await _bounded(thumb.is_visible())
                    button = frame.locator('#js-button').first
                    if slider or await _bounded(button.is_visible()):
                        actions += 1
                        action_deadline = min(deadline, time.monotonic() + ACTION_WAIT_SECONDS)
                        try:
                            if slider:
                                await self._drag_slider(page, thumb, frame, action_deadline)
                            else:
                                await _within_action(button.click(), action_deadline)
                        except (asyncio.TimeoutError, PlaywrightError):
                            pass
                        finally:
                            next_action_at = time.monotonic() + ACTION_WAIT_SECONDS
                        # Even a stalled action may have issued a token. Read it
                        # before checking the poll deadline or attempting anything else.
                        token = await self._read_token(page)
                        if token:
                            return token
                except (asyncio.TimeoutError, PlaywrightError):
                    # A loading/replaced frame can race a lookup; a stalled
                    # renderer consumes the remaining deadline and ends here.
                    pass
                await asyncio.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
        finally:
            _deadline.reset(marker)
        raise RuntimeError(f'SmartCaptcha: no token within {DEADLINE_SECONDS}s')

    async def _drag_slider(self, page, thumb, frame, deadline):
        await _within_action(thumb.scroll_into_view_if_needed(), deadline)
        start = await _within_action(thumb.bounding_box(), deadline)
        track = await _within_action(frame.locator('.SliderCaptcha').first.bounding_box(), deadline)
        if not start or not track:
            return
        x, y = start['x'] + start['width'] / 2, start['y'] + start['height'] / 2
        await _within_action(page.mouse.move(x, y), deadline)
        try:
            await _within_action(page.mouse.down(), deadline)
            await _within_action(page.mouse.move(track['x'] + track['width'] - 1, y, steps=15), deadline)
        finally:
            # Release even when the gesture budget is spent (a button left down
            # turns later clicks into a drag), but with its own short bound so a
            # stalled release cannot delay reading an already issued token.
            await asyncio.wait_for(page.mouse.up(), MOUSE_UP_SECONDS)

    async def _read_token(self, page) -> Optional[str]:
        return await _bounded(page.evaluate("""() => {
            const input = document.querySelector('input[name="smart-token"]');
            return input && input.value ? input.value : null;
        }"""))

    async def _challenge_kind(self, page) -> Optional[str]:
        selector = 'iframe[data-testid="advanced-iframe"]'
        if not await _bounded(page.locator(selector).first.is_visible()):
            return None
        root = page.frame_locator(selector).first.locator('.AdvancedCaptcha').first
        if not await _bounded(root.count()):
            return None
        classes = (await _bounded(root.get_attribute('class')) or '').split()
        if 'AdvancedCaptcha_image' in classes:
            return 'text'
        if 'AdvancedCaptcha_silhouette' in classes:
            return 'silhouette'
        return 'unknown'

    async def _solve_challenge(self, page, kind):
        if kind != "text":
            raise RuntimeError(f'SmartCaptcha: {kind} challenge is not supported yet')
        return await self._solve_text(page)

    async def _solve_text(self, page) -> Optional[str]:
        if self.vision_classifier is None:
            self.vision_classifier = VisionLLMClassifier()
        if not self.vision_classifier.enabled:
            raise RuntimeError("SmartCaptcha: text challenge needs the vision LLM")

        iframe = page.locator('iframe[data-testid="advanced-iframe"]').first
        frame = page.frame_locator('iframe[data-testid="advanced-iframe"]').first
        image = frame.locator('.AdvancedCaptcha-View img').first
        hint = frame.locator('.Textinput-Hint').first
        previous_src = None
        deadline = _deadline.get()
        if deadline is None:
            deadline = time.monotonic() + DEADLINE_SECONDS

        async def hint_state():
            visible = await _bounded(hint.is_visible())
            return visible, (await _bounded(hint.text_content()) if visible else None)

        for round_no in range(MAX_TEXT_ROUNDS):
            # A visible image can still be loading, or be the rejected image
            # while the widget fetches the replacement asynchronously.
            await _bounded(image.wait_for(state='visible'))
            while True:
                if time.monotonic() >= deadline:
                    raise asyncio.TimeoutError
                src = await _bounded(image.evaluate("""(img, previous) =>
                    img.complete && img.naturalWidth > 0 && img.src !== previous
                        ? img.src : null""", previous_src))
                if src:
                    break
                await _bounded(asyncio.sleep(POLL_INTERVAL))
            previous_src = src
            shot = await _bounded(image.screenshot())
            try:
                text = await _bounded(self.vision_classifier.read_text(shot))
            except Exception as exc:
                # Cancellation of the CLI at the poll deadline must reach
                # _poll, rather than refreshing and spending another round.
                if time.monotonic() >= deadline:
                    raise asyncio.TimeoutError from None
                if isinstance(exc, RuntimeError) and 'disabled' in str(exc).lower():
                    raise RuntimeError("SmartCaptcha: text challenge needs the vision LLM") from None
                print(f"SmartCaptcha: text round {round_no + 1}, recognition failed")
                refresh = frame.locator('button[data-testid="refresh"]').first
                if await _bounded(refresh.is_visible()):
                    await _bounded(refresh.click())
                continue

            answer = " ".join(text.lower().split())
            print(f"SmartCaptcha: text round {round_no + 1}, answer length {len(answer)}")
            field = frame.locator('input[name="rep"]').first
            await _bounded(field.fill(''))
            await _bounded(field.press_sequentially(answer, delay=40))
            before_hint = await hint_state()
            await _bounded(frame.locator('button[data-testid="submit"]').first.click())

            outcome_deadline = time.monotonic() + 10
            while time.monotonic() < outcome_deadline:
                if time.monotonic() >= deadline:
                    raise asyncio.TimeoutError
                token = await self._read_token(page)
                if token:
                    return token
                if not await _bounded(iframe.is_visible()):
                    return None
                current_src = await _bounded(image.evaluate('(img) => img.src'))
                current_hint = await hint_state()
                if current_src != src or (current_hint[0] and current_hint != before_hint):
                    break
                await _bounded(asyncio.sleep(POLL_INTERVAL))

        if time.monotonic() >= deadline:
            raise asyncio.TimeoutError
        raise RuntimeError("SmartCaptcha: text challenge not solved in 3 rounds")
