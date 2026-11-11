"""M3b contract tests, no network: the edges of the reCAPTCHA v2 round logic.

Most tests replace the page with mocks; the ones that need real DOM behaviour
(selection classes, swapped pictures, banners) use the fake bframe document of
tests/test_m3b_unit.py in the Chromium of the image. Test names carry the id of
the mutation they were written against (V..) or the behaviour they pin.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

import workers.solvers.recaptcha as mod
from test_m3b_unit import (
    DESC_HYDRANT,
    TOKEN,
    StubClassifier,
    _dom,
    _run,
)

SELECT_MORE = ".rc-imageselect-error-select-more"


def solver():
    return mod.RecaptchaV2Solver()


def challenge(**overrides):
    base = dict(images=("a",) * 9, target="fire hydrants",
                instruction="Select fire hydrants", grid="3x3", dynamic=False)
    base.update(overrides)
    return base


def root_with_count(count=9):
    root = MagicMock()
    root.locator.return_value.count = AsyncMock(return_value=count)
    root.locator.return_value.screenshot = AsyncMock(return_value=b"grid")
    root.locator.return_value.click = AsyncMock()
    return root


async def _forever(*args, **kwargs):
    await asyncio.Event().wait()


class HangingLocator:
    """Every read hangs, the way a frame with a stuck main thread does."""

    first = property(lambda self: self)
    count = text_content = is_visible = evaluate_all = staticmethod(_forever)


class HangingPage:
    evaluate = staticmethod(_forever)

    def locator(self, selector):
        return HangingLocator()


# --- survivors of the mutation run ----------------------------------------

def test_V04_dynamic_error_banner():
    async def run():
        s = solver()
        s._read_token = AsyncMock(return_value=None)
        s._visible = AsyncMock(
            side_effect=lambda root, selector, deadline=None:
            selector == ".rc-imageselect-error-dynamic-more"
        )
        assert await s._wait_round_outcome(None, None, timeout=0) == "retry"
    asyncio.run(run())


def test_V05_changed_grid_same_target():
    async def run():
        s = solver()
        before = challenge()
        s._read_token = AsyncMock(return_value=None)
        s._visible = AsyncMock(return_value=False)
        s._read_challenge = AsyncMock(return_value=dict(before, grid="4x4"))
        assert await s._wait_round_outcome(None, None, timeout=0, before=before) == "retry"
    asyncio.run(run())


def test_V06_timeout_stops_after_one_verify():
    async def run():
        s, root = solver(), root_with_count()
        s._read_challenge = AsyncMock(return_value=challenge())
        s._pick = AsyncMock(return_value=[])
        s._wait_round_outcome = AsyncMock(return_value="timeout")
        with pytest.raises(RuntimeError, match="no outcome after verify"):
            await s._solve_rounds(None, root)
        assert root.locator.return_value.click.await_count == 1
    asyncio.run(run())


def _dynamic_mocks(s, pick=(2,)):
    s._pick = AsyncMock(return_value=list(pick))
    s._tile_srcs = AsyncMock(return_value=["a"] * 9)
    s._click_tiles = AsyncMock(return_value=list(pick))
    s._wait_tiles_swapped = AsyncMock(return_value=True)


def test_V07_dynamic_pass_limit():
    async def run():
        s = solver()
        _dynamic_mocks(s)
        await s._clear_dynamic_grid(None, challenge(dynamic=True))
        assert s._pick.await_count == mod.MAX_DYNAMIC_PASSES == 5
        assert s._click_tiles.await_count == 5
    asyncio.run(run())


def test_V08_uppercase_dynamic_marker():
    async def run():
        s, root = solver(), root_with_count()
        s._text = AsyncMock(side_effect=[
            "Select fire hydrants. Click verify once there are NONE LEFT.", "fire hydrants",
        ])
        s._tile_states = AsyncMock(return_value=[("a", False)] * 9)
        assert (await s._read_challenge(root))["dynamic"] is True
    asyncio.run(run())


def test_V09_wait_for_tile_replacement():
    """The next pick sees the swapped picture, not the one just clicked."""
    async def run():
        s = solver()
        clicked_at = {}
        picks = []

        def replaced():
            return 0 in clicked_at and time.monotonic() - clicked_at[0] >= 0.6

        async def states(root, deadline=None):
            return [("new" if replaced() else "old", False)] + [("x", False)] * 8

        async def pick(root, ch):
            picks.append(replaced())
            return [] if replaced() else [0]

        async def click(root, idx):
            clicked_at[idx] = time.monotonic()

        s._tile_states = states
        s._pick = pick
        s._click_tile = click
        await s._clear_dynamic_grid(None, challenge(dynamic=True))
        assert picks == [False, True], "next classification must see the replacement"
    asyncio.run(run())


def test_V12_normalized_instruction_whitespace():
    async def run():
        s, root = solver(), MagicMock()
        loc = root.locator.return_value.first
        loc.count = AsyncMock(return_value=1)
        loc.text_content = AsyncMock(return_value=" \n Select\t all   fire\n hydrants  ")
        assert await s._text(root, mod.CHALLENGE_DESC) == "Select all fire hydrants"
    asyncio.run(run())


def test_V13_index_upper_bound():
    async def run():
        s, root = solver(), root_with_count()
        s.vision_classifier = MagicMock()
        s.vision_classifier.classify_tiles = AsyncMock(return_value=[-1, 0, 8, 9, 10])
        assert await s._pick(root, challenge()) == [0, 8]
    asyncio.run(run())


def test_V14_local_fallback_on_vision_failure():
    async def run():
        s, root = solver(), root_with_count()
        s.vision_classifier = MagicMock()
        s.vision_classifier.classify_tiles = AsyncMock(side_effect=RuntimeError("down"))
        s._pick_with_yolo = AsyncMock(return_value=[1, 7])
        ch = challenge()
        assert await s._pick(root, ch) == [1, 7]
        s._pick_with_yolo.assert_awaited_once_with(root, ch)
    asyncio.run(run())


def test_V16_local_target_normalization():
    async def run():
        s = solver()
        s._grab_tile_shots = AsyncMock(return_value=[b"crop0", b"crop1"])
        s._classify_image_hybrid = AsyncMock(side_effect=[False, True])
        assert await s._pick_with_yolo(None, challenge(target="Fire Hydrants")) == [1]
        assert [c.args for c in s._classify_image_hybrid.await_args_list] == [
            (b"crop0", "fire_hydrant"), (b"crop1", "fire_hydrant")]
    asyncio.run(run())


def test_V17_verify_after_dynamic_clicks():
    async def run():
        s, root = solver(), root_with_count()
        events = []

        async def clear(root, ch):
            events.append("dynamic clicks")

        async def verify(**kwargs):
            events.append("verify")

        async def outcome(*args, **kwargs):
            events.append("outcome")
            return "token"

        s._read_challenge = AsyncMock(return_value=challenge(dynamic=True))
        s._clear_dynamic_grid = clear
        root.locator.return_value.click = verify
        s._wait_round_outcome = outcome
        s._read_token = AsyncMock(return_value="token")
        assert await s._solve_rounds(None, root) == "token"
        assert events == ["dynamic clicks", "verify", "outcome"]
    asyncio.run(run())


# --- round outcome: new pictures, stale banners ----------------------------

def test_new_pictures_same_instruction_is_retry():
    async def run():
        s = solver()
        before = challenge()
        s._read_token = AsyncMock(return_value=None)
        s._visible = AsyncMock(return_value=False)
        s._read_challenge = AsyncMock(return_value=dict(before, images=("b",) * 9))
        assert await s._wait_round_outcome(None, None, timeout=0, before=before) == "retry"
    asyncio.run(run())


def test_new_pictures_same_instruction_dom():
    """Google swaps every picture, keeps instruction and size, shows no banner."""
    script = """
function onVerify(n) {
  if (n === 1) {
    document.querySelectorAll('.rc-image-tile-wrapper img').forEach(function (img) {
      img.setAttribute('src', img.getAttribute('src') + '#round2');
    });
  } else {
    setToken('%TOKEN%');
  }
}
"""
    stub = StubClassifier([[1], [2]])

    async def body(page):
        s = solver()
        s.vision_classifier = stub
        assert await s._solve_rounds(page, page) == TOKEN
        assert await page.evaluate("window.__verify") == 2
        assert await page.evaluate("window.__clicks") == [1, 2]

    asyncio.run(_run(_dom(DESC_HYDRANT, script), body))


def test_stale_banner_is_not_retry():
    async def run():
        s = solver()
        s._read_token = AsyncMock(side_effect=[None, None, "tok"])
        s._visible = AsyncMock(
            side_effect=lambda root, selector, deadline=None: selector == SELECT_MORE
        )
        out = await s._wait_round_outcome(None, None, timeout=5, banners={SELECT_MORE})
        assert out == "token"
    asyncio.run(run())


def test_banner_gone_and_back_is_retry():
    async def run():
        s = solver()
        seen = iter([True, False, True])
        s._read_token = AsyncMock(return_value=None)
        s._visible = AsyncMock(
            side_effect=lambda root, selector, deadline=None:
            next(seen) if selector == SELECT_MORE else False
        )
        out = await s._wait_round_outcome(None, None, timeout=5, banners={SELECT_MORE})
        assert out == "retry"
        assert s._read_token.await_count == 3
    asyncio.run(run())


def test_stale_banner_dom():
    """A banner left over from the last round, then a token 600 ms after verify."""
    script = """
function onVerify(n) {
  setTimeout(function () { setToken('%TOKEN%'); }, 600);
}
"""
    stub = StubClassifier([[3]])

    async def body(page):
        await page.evaluate("showError('rc-imageselect-error-select-more')")
        s = solver()
        s.vision_classifier = stub
        assert await s._solve_rounds(page, page) == TOKEN
        assert await page.evaluate("window.__verify") == 1

    asyncio.run(_run(_dom(DESC_HYDRANT, script), body))


# --- bounded page calls -----------------------------------------------------

def test_poll_token_hanging_evaluate():
    async def run():
        s = solver()
        started = time.monotonic()
        assert await s._poll_token(HangingPage(), 1) is None
        assert time.monotonic() - started < 1.9
    asyncio.run(run())


def test_round_outcome_hanging_page():
    async def run():
        s = solver()
        page = HangingPage()
        started = time.monotonic()
        out = await s._wait_round_outcome(page, page, timeout=1, before=challenge())
        assert out == "timeout"
        assert time.monotonic() - started < 1.9
    asyncio.run(run())


def test_round_outcome_hanging_locators():
    """The token read answers (no token), every frame read hangs."""
    async def run():
        s = solver()
        page = MagicMock()
        page.evaluate = AsyncMock(return_value=None)
        page.locator = lambda selector: HangingLocator()
        started = time.monotonic()
        out = await s._wait_round_outcome(page, page, timeout=1, before=challenge())
        assert out == "timeout"
        assert time.monotonic() - started < 1.9
    asyncio.run(run())


def test_read_challenge_hanging_is_bounded():
    async def run():
        s = solver()
        started = time.monotonic()
        with pytest.raises(asyncio.TimeoutError):
            await s._read_challenge(HangingPage(), time.monotonic() + 0.2)
        assert time.monotonic() - started < 1.5
    asyncio.run(run())


# --- picking and clicking ---------------------------------------------------

def test_pick_drops_duplicates_keeps_order():
    async def run():
        s, root = solver(), root_with_count()
        s.vision_classifier = MagicMock()
        s.vision_classifier.classify_tiles = AsyncMock(return_value=[4, 0, 4, 2, 0])
        assert await s._pick(root, challenge()) == [4, 0, 2]
    asyncio.run(run())


def test_selected_tile_not_clicked_again():
    async def body(page):
        await page.evaluate(
            "document.querySelector('[data-idx=\"1\"]')"
            ".classList.add('rc-imageselect-tileselected')"
        )
        s = solver()
        assert await s._click_tiles(page, [1, 2]) == [2]
        assert await page.evaluate("window.__clicks") == [2]

    asyncio.run(_run(_dom(DESC_HYDRANT, "function onVerify(n) {}"), body))


def test_dynamic_passes_exhausted_still_verifies(capsys):
    async def run():
        s, root = solver(), root_with_count()
        _dynamic_mocks(s)
        s._read_challenge = AsyncMock(return_value=challenge(dynamic=True))
        s._wait_round_outcome = AsyncMock(return_value="token")
        s._read_token = AsyncMock(return_value="tok")
        assert await s._solve_rounds(None, root) == "tok"
        assert s._pick.await_count == mod.MAX_DYNAMIC_PASSES
        assert root.locator.return_value.click.await_count == 1
    asyncio.run(run())
    assert "still has matches after 5 passes, verifying anyway" in capsys.readouterr().out


def test_dynamic_swap_timeout_is_logged(capsys, monkeypatch):
    monkeypatch.setattr(mod, "TILE_SWAP_TIMEOUT", 0.3)

    async def run():
        s = solver()
        s._pick = AsyncMock(side_effect=[[0], []])
        s._tile_states = AsyncMock(return_value=[("same", False)] * 9)
        s._click_tile = AsyncMock()
        await s._clear_dynamic_grid(None, challenge(dynamic=True))
        assert s._pick.await_count == 2
    asyncio.run(run())
    assert "not replaced within 0.3s, picking again anyway" in capsys.readouterr().out


@pytest.mark.parametrize("target, expected", [
    ("fire hydrants", "fire_hydrant"),
    ("a fire hydrant", "fire_hydrant"),
    ("cars", "car"),
    ("buses", "bus"),
    ("a bus", "bus"),
    ("traffic lights", "traffic_light"),
    ("motorcycles", "motorcycle"),
    ("bicycles", "bicycle"),
    ("crosswalks", "crosswalk"),
    ("palm trees", "palm_tree"),
    ("stairs", "stairs"),
    ("bridges", "bridge"),
    ("mountains or hills", "mountain"),
    ("Select all images with a fire hydrant", "fire_hydrant"),
    ("Select all squares with Traffic Lights. If there are none, click skip", "traffic_light"),
])
def test_local_class_names(target, expected):
    assert mod.RecaptchaV2Solver._local_class(target) == expected
