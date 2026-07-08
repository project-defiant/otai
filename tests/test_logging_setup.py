import sys

from loguru import logger

from otai import logging_setup


def test_configure_logging_respects_log_level(monkeypatch):
    monkeypatch.setenv("OTAI_LOG_LEVEL", "WARNING")
    buffer = []
    monkeypatch.setattr(sys, "stderr", _FakeStream(buffer))

    logging_setup.configure_logging()
    try:
        logger.info("this info message must be filtered out")
        logger.warning("this warning message must appear")

        output = "".join(buffer)
        assert "this warning message must appear" in output
        assert "this info message must be filtered out" not in output
    finally:
        logger.remove()


def test_configure_logging_is_idempotent(monkeypatch):
    # Calling it twice (e.g. across CLI invocations in a test session) must
    # not accumulate duplicate handlers - only one copy of each message.
    monkeypatch.setenv("OTAI_LOG_LEVEL", "INFO")
    buffer = []
    monkeypatch.setattr(sys, "stderr", _FakeStream(buffer))

    logging_setup.configure_logging()
    logging_setup.configure_logging()
    try:
        logger.info("only once")
        output = "".join(buffer)
        assert output.count("only once") == 1
    finally:
        logger.remove()


class _FakeStream:
    """Minimal writable stream loguru can safely add as a sink."""

    def __init__(self, buffer):
        self._buffer = buffer

    def write(self, message):
        self._buffer.append(message)

    def flush(self):
        pass
