import logging
import viewport
from selenium.common.exceptions import TimeoutException

# --------------------------------------------------------------------------- # 
# log_error must keep the exception type/message even when ERROR_LOGGING is off
# --------------------------------------------------------------------------- # 
def test_log_error_appends_exception_summary_without_traceback(monkeypatch, caplog):
    monkeypatch.setattr(viewport, "ERROR_LOGGING", False)
    monkeypatch.setattr(viewport, "ERROR_PRTSCR", False)
    exc = TimeoutException("Message: waited 30s for input\nStacktrace:\n#0 0x1234")

    with caplog.at_level(logging.ERROR):
        viewport.log_error("Error during login: ", exc)

    assert "Error during login:  [TimeoutException: Message: waited 30s for input]" in caplog.text
    assert "Stacktrace" not in caplog.text

def test_log_error_uses_type_name_when_exception_has_no_message(monkeypatch, caplog):
    monkeypatch.setattr(viewport, "ERROR_LOGGING", False)
    monkeypatch.setattr(viewport, "ERROR_PRTSCR", False)

    with caplog.at_level(logging.ERROR):
        viewport.log_error("Something failed", TimeoutException())

    assert "Something failed [TimeoutException]" in caplog.text

def test_log_error_plain_message_when_no_exception(monkeypatch, caplog):
    monkeypatch.setattr(viewport, "ERROR_LOGGING", False)
    monkeypatch.setattr(viewport, "ERROR_PRTSCR", False)

    with caplog.at_level(logging.ERROR):
        viewport.log_error("Just a message")

    assert "Just a message" in caplog.text
    assert "[" not in caplog.records[-1].getMessage()

def test_log_error_full_traceback_when_error_logging_on(monkeypatch, caplog):
    monkeypatch.setattr(viewport, "ERROR_LOGGING", True)
    monkeypatch.setattr(viewport, "ERROR_PRTSCR", False)

    with caplog.at_level(logging.ERROR):
        try:
            raise ValueError("boom")
        except ValueError as e:
            viewport.log_error("With trace", e)

    assert "With trace" in caplog.text
    assert "ValueError: boom" in caplog.text
