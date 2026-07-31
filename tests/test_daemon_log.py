"""daemon.log must stay bounded.

The daemon runs detached, so its log is the only diagnostic there is — a real
one reached 3.9 MB of DuckDB lock failures and enrichment errors, all of it
worth keeping. The bug was that nothing ever capped it: `_spawn` opened the
file in append mode and no rotation existed anywhere.
"""

import logging

import pytest

from scopus_for_dobby.cli import _daemon, serve


@pytest.fixture
def log_file(monkeypatch, tmp_path):
    path = tmp_path / "daemon.log"
    monkeypatch.setattr(serve, "LOG_FILE", path)
    monkeypatch.setattr(_daemon, "LOG_FILE", path)
    yield path
    # Detach any handler this test installed so it can't leak into others.
    for h in list(logging.getLogger().handlers):
        if isinstance(h, logging.FileHandler) and str(path) in str(h.baseFilename):
            logging.getLogger().removeHandler(h)
            h.close()


class TestRotateOnSpawn:
    def test_oversized_log_is_rotated(self, log_file, monkeypatch):
        monkeypatch.setattr(_daemon, "MAX_LOG_BYTES", 1024)
        log_file.write_bytes(b"x" * 4096)

        assert _daemon._rotate_if_oversized() is True
        assert not log_file.exists()
        assert log_file.with_name("daemon.log.1").read_bytes() == b"x" * 4096

    def test_small_log_is_left_alone(self, log_file, monkeypatch):
        monkeypatch.setattr(_daemon, "MAX_LOG_BYTES", 1024)
        log_file.write_bytes(b"y" * 10)

        assert _daemon._rotate_if_oversized() is False
        assert log_file.read_bytes() == b"y" * 10
        assert not log_file.with_name("daemon.log.1").exists()

    def test_missing_log_is_not_an_error(self, log_file):
        assert _daemon._rotate_if_oversized() is False


class TestDaemonFileLogging:
    def test_handler_is_capped_and_rotating(self, log_file):
        from logging.handlers import RotatingFileHandler

        handler = serve.configure_file_logging()
        try:
            assert isinstance(handler, RotatingFileHandler)
            assert handler.maxBytes == serve.MAX_LOG_BYTES
            assert handler.backupCount == serve.LOG_BACKUPS
        finally:
            logging.getLogger().removeHandler(handler)
            handler.close()

    def test_log_is_owner_only(self, log_file):
        handler = serve.configure_file_logging()
        try:
            assert log_file.stat().st_mode & 0o777 == 0o600
        finally:
            logging.getLogger().removeHandler(handler)
            handler.close()

    def test_writes_reach_the_file(self, log_file):
        handler = serve.configure_file_logging()
        try:
            logging.getLogger("scopus_for_dobby.test").error("boom-marker")
            handler.flush()
            assert "boom-marker" in log_file.read_text()
        finally:
            logging.getLogger().removeHandler(handler)
            handler.close()

    def test_growth_is_bounded(self, log_file, monkeypatch):
        """The actual bug: writing a lot must not grow the file without limit."""
        monkeypatch.setattr(serve, "MAX_LOG_BYTES", 2048)
        monkeypatch.setattr(serve, "LOG_BACKUPS", 1)
        handler = serve.configure_file_logging()
        try:
            log = logging.getLogger("scopus_for_dobby.test")
            for i in range(500):
                log.error("a traceback line that repeats forever %d", i)
            handler.flush()
            # Live file respects the cap, and only one backup is retained.
            assert log_file.stat().st_size <= 2048
            assert not log_file.with_name("daemon.log.2").exists()
        finally:
            logging.getLogger().removeHandler(handler)
            handler.close()
