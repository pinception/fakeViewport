import pytest
import viewport
from unittest.mock import MagicMock
from selenium.common.exceptions import TimeoutException

# --------------------------------------------------------------------------- # 
# Tests for wait_for_liveview: tries every known wrapper class, then <video>
# --------------------------------------------------------------------------- # 
class ImmediateWait:
    """WebDriverWait stand-in: evaluates the condition once, no polling."""
    def __init__(self, driver, timeout):
        self.driver = driver
    def until(self, cond):
        result = cond(self.driver)
        if not result:
            raise TimeoutException("condition not met")
        return result

@pytest.fixture(autouse=True)
def immediate_wait(monkeypatch):
    monkeypatch.setattr(viewport, "WebDriverWait", ImmediateWait)
    monkeypatch.setattr(viewport, "CSS_LIVEVIEW_WRAPPER", ["div.new-wrapper", "div.old-wrapper"])

def test_wait_for_liveview_returns_first_matching_selector():
    driver = MagicMock()
    driver.find_elements.side_effect = lambda by, sel: [object()] if sel == "div.old-wrapper" else []

    assert viewport.wait_for_liveview(driver) == "div.old-wrapper"
    # no need for the <video> fallback when a wrapper class matched
    driver.execute_script.assert_not_called()

def test_wait_for_liveview_falls_back_to_video_presence(monkeypatch):
    driver = MagicMock()
    driver.find_elements.return_value = []
    driver.execute_script.return_value = 4        # four <video> elements
    warns = []
    monkeypatch.setattr(viewport.logging, "warning", lambda msg: warns.append(msg))

    assert viewport.wait_for_liveview(driver) == "video"
    assert any("renamed" in w for w in warns)

def test_wait_for_liveview_raises_when_nothing_found():
    driver = MagicMock()
    driver.find_elements.return_value = []
    driver.execute_script.return_value = 0

    with pytest.raises(TimeoutException):
        viewport.wait_for_liveview(driver)

def test_wait_for_liveview_accepts_single_selector_string(monkeypatch):
    monkeypatch.setattr(viewport, "CSS_LIVEVIEW_WRAPPER", "div.only-wrapper")
    driver = MagicMock()
    driver.find_elements.side_effect = lambda by, sel: [object()] if sel == "div.only-wrapper" else []

    assert viewport.wait_for_liveview(driver) == "div.only-wrapper"
