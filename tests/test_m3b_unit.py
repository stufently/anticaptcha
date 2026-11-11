"""M3b unit tests, no network: reCAPTCHA v2 tile crop, rounds, dynamic grid.

In production the challenge lives in a cross-origin iframe, so every solver
helper works against a "root" that only needs `.locator()`. These tests hand it
the page itself carrying a fake bframe DOM: the real reCAPTCHA tile geometry (a
378x378 sprite shifted inside a 126x126 window), a verify button whose handler
plays Google's part of the round, and the `#g-recaptcha-response` textarea the
token is read from. The classifier is a stub — the image has no API key, and the
point of these tests is the flow around it, not the model.

Every test name carries B (milestone marker).
"""
import asyncio
import base64
import io

import pytest
from PIL import Image, ImageDraw, ImageStat

from app.utils.browser import browser_manager
from workers.solvers import recaptcha as recaptcha_mod
from workers.solvers.recaptcha import RecaptchaV2Solver

TILE = 126  # reCAPTCHA's tile window, measured live on the Google demo
TOKEN = "03AGdBqK4E-M3B-STUB-TOKEN-" + "x" * 60
IMAGES_READY = "Array.from(document.images).every(i => i.complete && i.naturalWidth > 0)"

# Far enough apart that the mean color of a crop identifies its tile.
PALETTE = [
    (200, 30, 30), (30, 200, 30), (30, 30, 200), (210, 210, 30),
    (200, 30, 200), (30, 200, 200), (120, 60, 20), (60, 120, 90),
    (240, 240, 240), (15, 15, 15), (255, 130, 0), (0, 130, 255),
    (130, 0, 255), (255, 0, 130), (0, 255, 130), (90, 90, 90),
]

DESC_HYDRANT = "Select all images with <strong>fire hydrants</strong>"
DESC_NO_STRONG = "Select all images with a fire hydrant"
DESC_PARKING = "Select all images with <strong>parking meters</strong>"
DESC_DYNAMIC = (
    "Select all images with <strong>fire hydrants</strong>."
    " Click verify once there are none left."
)

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>fake bframe</title>
<script>
window.__clicks = [];
window.__verify = 0;
function setToken(value) {
  document.getElementById('g-recaptcha-response').value = value;
}
function clearErrors() {
  document.getElementById('errors').innerHTML = '';
}
function showError(cls) {
  clearErrors();
  const div = document.createElement('div');
  div.className = cls;
  div.textContent = cls;
  document.getElementById('errors').appendChild(div);
}
function setInstruction(html) {
  document.querySelector('.rc-imageselect-desc-wrapper').innerHTML = html;
}
%SCRIPT%
</script></head>
<body>
<div class="rc-imageselect-desc-wrapper">%DESC%</div>
<div class="rc-imageselect-target" style="width:378px;height:60px;background:#777"></div>
<div id="grid">%TILES%</div>
<div id="errors"></div>
<button id="recaptcha-verify-button">Verify</button>
<textarea id="g-recaptcha-response"></textarea>
<script>
document.addEventListener('click', function (event) {
  const wrapper = event.target.closest('.rc-image-tile-wrapper');
  if (wrapper) window.__clicks.push(Number(wrapper.dataset.idx));
}, true);
document.getElementById('recaptcha-verify-button').addEventListener('click', function () {
  window.__verify += 1;
  onVerify(window.__verify);
});
</script>
</body></html>
"""


def _sprite_uri(count):
    """One PNG holding every tile of the grid, the way Google serves it."""
    side = 3 if count == 9 else 4
    image = Image.new("RGB", (TILE * side, TILE * side))
    draw = ImageDraw.Draw(image)
    for idx in range(count):
        row, col = divmod(idx, side)
        box = (col * TILE, row * TILE, col * TILE + TILE - 1, row * TILE + TILE - 1)
        draw.rectangle(box, fill=PALETTE[idx])
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _tiles(count, tile_class):
    """`count` wrappers of TILE x TILE, each showing its own slice of the sprite."""
    side = 3 if count == 9 else 4
    uri = _sprite_uri(count)
    cells = []
    for idx in range(count):
        row, col = divmod(idx, side)
        cells.append(
            f'<div class="rc-image-tile-wrapper" data-idx="{idx}" '
            f'style="position:relative;display:inline-block;width:{TILE}px;'
            f'height:{TILE}px;overflow:hidden">'
            f'<img class="{tile_class}" src="{uri}" '
            f'style="position:absolute;width:{side * TILE}px;height:{side * TILE}px;'
            f'left:-{col * TILE}px;top:-{row * TILE}px"></div>'
        )
    return "".join(cells)


def _dom(desc, script="", count=9, tile_class="rc-image-tile-33"):
    """A fake bframe document; `script` supplies the `onVerify` handler."""
    return (
        PAGE.replace("%DESC%", desc)
        .replace("%TILES%", _tiles(count, tile_class))
        .replace("%SCRIPT%", script.replace("%TOKEN%", TOKEN))
    )


async def _run(html, body):
    """Load the fake DOM, run `body(page)`, always release the browser.

    `browser_manager` is a module-level singleton: a transport left behind by a
    closed event loop makes the next test hang, so it is closed inside the loop
    that used it.
    """
    page = await browser_manager.new_page(stealth=False)
    try:
        await page.set_content(html)
        await page.wait_for_function(IMAGES_READY)
        return await body(page)
    finally:
        await browser_manager.close()


class StubClassifier:
    """Stands in for VisionLLMClassifier: answers from a written-down script."""

    def __init__(self, picks):
        self.picks = list(picks)
        self.calls = []   # (instruction, grid_size) of every call
        self.shots = []   # the bytes it was asked about

    async def classify_tiles(self, image_bytes, instruction, grid_size="3x3"):
        self.calls.append((instruction, grid_size))
        self.shots.append(image_bytes)
        return self.picks.pop(0) if self.picks else []


class PendingStub(StubClassifier):
    """Also notes how many tile swaps were still on their way at each call."""

    def __init__(self, picks):
        super().__init__(picks)
        self.page = None
        self.pending = []

    async def classify_tiles(self, image_bytes, instruction, grid_size="3x3"):
        self.pending.append(await self.page.evaluate("window.__pending"))
        return await super().classify_tiles(image_bytes, instruction, grid_size)


def test_B1_crop():
    """A tile shot is one 126x126 crop, not the 378x378 sprite of all nine.

    The sprite is the bug this milestone fixes: screenshotting the wrapper's
    `img` hands the classifier the whole grid nine times, so every tile looks
    like a match.
    """

    async def body(page):
        solver = RecaptchaV2Solver()
        shots = await solver._grab_tile_shots(page)
        assert len(shots) == 9

        means = []
        for idx, shot in enumerate(shots):
            image = Image.open(io.BytesIO(shot)).convert("RGB")
            assert abs(image.width - TILE) <= 6, f"tile {idx}: {image.size}"
            assert abs(image.height - TILE) <= 6, f"tile {idx}: {image.size}"
            mean = tuple(ImageStat.Stat(image).mean)
            means.append(mean)
            for channel in range(3):
                assert abs(mean[channel] - PALETTE[idx][channel]) <= 8, (
                    f"tile {idx} shows {mean}, expected its own color {PALETTE[idx]}"
                )
        assert len({tuple(round(c) for c in mean) for mean in means}) == 9

    asyncio.run(_run(_dom(DESC_HYDRANT), body))


def test_B2_two_rounds():
    """Verify #1 answers with a new instruction, verify #2 with the token."""
    script = """
function onVerify(n) {
  clearErrors();
  if (n === 1) {
    setInstruction('Select all squares with <strong>motorcycles</strong>');
  } else {
    setToken('%TOKEN%');
  }
}
"""
    stub = StubClassifier([[0, 4], [2]])

    async def body(page):
        solver = RecaptchaV2Solver()
        solver.vision_classifier = stub
        assert await solver._solve_rounds(page, page) == TOKEN
        assert await page.evaluate("window.__verify") == 2
        assert await page.evaluate("window.__clicks") == [0, 4, 2]
        # the classifier is asked about what the instruction actually says,
        # and the second round is read again, not carried over
        assert stub.calls == [
            ("Select all fire hydrants", "3x3"),
            ("Select all motorcycles", "3x3"),
        ]
        assert all(shot for shot in stub.shots)

    asyncio.run(_run(_dom(DESC_HYDRANT, script), body))


def test_B3_select_more():
    """An empty selection earns `error-select-more` and another round."""
    script = """
function onVerify(n) {
  clearErrors();
  if (n === 1) {
    showError('rc-imageselect-error-select-more');
  } else {
    setToken('%TOKEN%');
  }
}
"""
    stub = StubClassifier([[], [3]])

    async def body(page):
        solver = RecaptchaV2Solver()
        solver.vision_classifier = stub
        assert await solver._solve_rounds(page, page) == TOKEN
        assert await page.evaluate("window.__verify") == 2
        assert await page.evaluate("window.__clicks") == [3]
        assert len(stub.calls) == 2

    asyncio.run(_run(_dom(DESC_HYDRANT, script), body))


def test_B4_dynamic(monkeypatch):
    """A refilling grid is clicked until the classifier finds nothing left.

    The fake grid plays Google's part: a click on tile 0 or 4 swaps its picture
    a second later, a click on tile 2 only selects it. The classifier must see
    every swap land before it is asked again, verify must wait for the last
    one, and tile 2 — picked twice, never replaced — is clicked once: a second
    click would unselect it.
    """
    # tile 2 never refills, so every pass that clicks it waits the bound out
    monkeypatch.setattr(recaptcha_mod, "TILE_SWAP_TIMEOUT", 1.5)
    script = """
window.__pending = 0;
window.__pendingAtVerify = null;
window.__swaps = 0;
const REFILLS = {0: true, 4: true};
function onVerify(n) {
  window.__pendingAtVerify = window.__pending;
  clearErrors();
  setToken('%TOKEN%');
}
document.addEventListener('click', function (event) {
  const wrapper = event.target.closest('.rc-image-tile-wrapper');
  if (!wrapper) return;
  if (REFILLS[Number(wrapper.dataset.idx)]) {
    window.__pending += 1;
    setTimeout(function () {
      const img = wrapper.querySelector('img');
      window.__swaps += 1;
      img.setAttribute('src', img.getAttribute('src') + '#swap' + window.__swaps);
      window.__pending -= 1;
    }, 1000);
  } else {
    wrapper.classList.toggle('rc-imageselect-tileselected');
  }
});
"""
    # tile 4 is clicked last: without the wait the next pick lands well
    # inside its one-second swap (a click is followed by 0.3-0.7 s)
    stub = PendingStub([[2, 0, 4], [4, 2], []])

    async def body(page):
        stub.page = page
        solver = RecaptchaV2Solver()
        solver.vision_classifier = stub
        assert await solver._solve_rounds(page, page) == TOKEN
        # three picks, all before the single verify: the grid is cleared first
        assert len(stub.calls) == 3
        assert stub.calls[0] == ("Select all fire hydrants", "3x3")
        # no pick and no verify while a swap was still on its way
        assert stub.pending == [0, 0, 0]
        assert await page.evaluate("window.__pendingAtVerify") == 0
        assert await page.evaluate("window.__verify") == 1
        assert await page.evaluate("window.__swaps") == 3
        assert await page.evaluate("window.__clicks") == [2, 0, 4, 4]
        assert await page.evaluate(
            "document.querySelector('[data-idx=\"2\"]')"
            ".classList.contains('rc-imageselect-tileselected')"
        )

    asyncio.run(_run(_dom(DESC_DYNAMIC, script), body))


def test_B5_rounds_exhausted():
    """A challenge that only ever answers `select-more` stops after 5 rounds."""
    script = """
function onVerify(n) {
  // the banner of the previous round goes away, the new one comes back
  clearErrors();
  setTimeout(function () { showError('rc-imageselect-error-select-more'); }, 400);
}
"""
    stub = StubClassifier([[0]])

    async def body(page):
        solver = RecaptchaV2Solver()
        solver.vision_classifier = stub
        with pytest.raises(RuntimeError) as excinfo:
            await solver._solve_rounds(page, page)
        assert "5 rounds" in str(excinfo.value)
        assert await page.evaluate("window.__verify") == 5
        assert len(stub.calls) == 5
        assert await page.evaluate(
            "document.getElementById('g-recaptcha-response').value"
        ) == ""

    asyncio.run(_run(_dom(DESC_HYDRANT, script), body))


def test_B6_target():
    """The target is the <strong> text, the grid size the number of wrappers."""

    async def body(page):
        solver = RecaptchaV2Solver()

        challenge = await solver._read_challenge(page)
        assert challenge["target"] == "parking meters"
        assert challenge["instruction"] == "Select all images with parking meters"
        assert challenge["grid"] == "4x4"
        assert challenge["dynamic"] is False

        # no <strong> in this layout: the instruction itself is the target,
        # instead of the ValueError a fixed word list used to raise
        await page.set_content(_dom(DESC_NO_STRONG))
        await page.wait_for_function(IMAGES_READY)
        challenge = await solver._read_challenge(page)
        assert challenge["target"] == challenge["instruction"] == DESC_NO_STRONG
        assert challenge["grid"] == "3x3"
        assert challenge["dynamic"] is False

        await page.set_content(_dom(DESC_DYNAMIC))
        await page.wait_for_function(IMAGES_READY)
        challenge = await solver._read_challenge(page)
        assert challenge["dynamic"] is True
        assert challenge["target"] == "fire hydrants"

    asyncio.run(
        _run(_dom(DESC_PARKING, count=16, tile_class="rc-image-tile-44"), body)
    )
