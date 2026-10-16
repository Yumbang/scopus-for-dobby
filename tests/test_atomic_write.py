"""config.json and the full-text cache are shared by every agent: writes must be atomic.

`save_config` ran after every API response (it caches the quota) and rewrote the file in
place, so a second process reading it mid-write got a truncated file and crashed in
`json.loads`. The file also held credentials but was chmod-ed only after it was written.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import threading

import pytest

from scopus_for_dobby.utils import api_client
from scopus_for_dobby.utils.fsutil import atomic_write_bytes, atomic_write_text


def test_writes_the_content_and_leaves_no_temp_file(tmp_path):
    target = tmp_path / "x.json"
    atomic_write_text(target, '{"a": 1}')
    assert json.loads(target.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_replaces_an_existing_file(tmp_path):
    target = tmp_path / "x.txt"
    atomic_write_text(target, "old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_a_secret_is_never_readable_by_others_even_briefly(tmp_path, monkeypatch):
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(stat.S_IMODE(os.stat(src).st_mode))  # the mode at the moment it goes live
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    atomic_write_text(tmp_path / "config.json", "{}", mode=0o600)
    assert seen == [0o600]
    assert stat.S_IMODE((tmp_path / "config.json").stat().st_mode) == 0o600


def test_a_failed_write_leaves_the_original_and_no_litter(tmp_path, monkeypatch):
    target = tmp_path / "x.txt"
    atomic_write_text(target, "keep me")

    def boom(src, dst):
        raise OSError("disk says no")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk says no"):
        atomic_write_text(target, "lost")
    assert target.read_text() == "keep me"
    assert [p.name for p in tmp_path.iterdir()] == ["x.txt"]


def test_bytes_round_trip(tmp_path):
    atomic_write_bytes(tmp_path / "f.jpg", b"\xff\xd8\xff")
    assert (tmp_path / "f.jpg").read_bytes() == b"\xff\xd8\xff"


def test_readers_never_see_a_torn_config(tmp_path, monkeypatch):
    """Many writers, many readers, one config.json: every read parses."""
    monkeypatch.setattr(api_client, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(api_client, "CONFIG_FILE", tmp_path / "config.json")
    api_client.save_config({"api_key": "k" * 40, "pad": "x" * 20000})
    stop = threading.Event()
    failures = []

    def reader():
        while not stop.is_set():
            try:
                assert api_client.load_config()["api_key"] == "k" * 40
            except Exception as exc:  # noqa: BLE001 — any failure is the bug
                failures.append(repr(exc))
                return

    def writer(n):
        for i in range(60):
            api_client._cache_quota(n * 1000 + i, "2026-10-20", bucket=f"b{n}")

    readers = [threading.Thread(target=reader) for _ in range(4)]
    writers = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in readers + writers:
        t.start()
    for t in writers:
        t.join()
    stop.set()
    for t in readers:
        t.join()
    assert failures == []
    assert api_client.load_config()["api_key"] == "k" * 40  # the credentials survived it all
