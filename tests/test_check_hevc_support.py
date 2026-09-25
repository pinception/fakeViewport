import viewport
import pytest
from unittest.mock import MagicMock
from selenium.common.exceptions import WebDriverException

# --------------------------------------------------------------------------- #
# check_hevc_support: reads MSE / mediaCapabilities and logs the verdict
# --------------------------------------------------------------------------- #
@pytest.fixture
def captured(monkeypatch):
    logs = {"info": [], "warning": [], "status": [], "error": []}
    monkeypatch.setattr(viewport.logging, "info", lambda m: logs["info"].append(m))
    monkeypatch.setattr(viewport.logging, "warning", lambda m: logs["warning"].append(m))
    monkeypatch.setattr(viewport, "api_status", lambda m: logs["status"].append(m))
    monkeypatch.setattr(viewport, "log_error", lambda m, e=None, driver=None: logs["error"].append(m))
    return logs

def test_hevc_hardware_decoding(captured):
    driver = MagicMock()
    driver.execute_async_script.return_value = {"supported": True, "powerEfficient": True}
    assert viewport.check_hevc_support(driver) is True
    assert any("hardware decoding" in m for m in captured["info"])
    assert captured["warning"] == []

def test_hevc_software_only(captured):
    driver = MagicMock()
    driver.execute_async_script.return_value = {"supported": True, "powerEfficient": False}
    assert viewport.check_hevc_support(driver) is True
    assert any("only in software" in m for m in captured["warning"])

@pytest.mark.parametrize("result", [{"supported": False, "powerEfficient": False}, None])
def test_hevc_not_supported(captured, result):
    driver = MagicMock()
    driver.execute_async_script.return_value = result
    assert viewport.check_hevc_support(driver) is False
    assert any("cannot decode HEVC" in m for m in captured["warning"])
    assert captured["status"] == ["HEVC not supported by browser"]

def test_hevc_check_script_error(captured):
    driver = MagicMock()
    driver.execute_async_script.side_effect = WebDriverException("script timeout")
    assert viewport.check_hevc_support(driver) is False
    assert captured["error"] == ["Could not check HEVC support: "]
