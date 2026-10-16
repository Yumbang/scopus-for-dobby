"""Small file helpers shared by the config and the full-text cache."""

from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    """Write ``data`` so that no reader ever sees a half-written ``path``.

    The bytes go to a sibling temp file, created with ``mode`` from the start (so a secret is
    never briefly world-readable, as with write-then-chmod), then replace ``path`` in one step.
    Several agents share ``config.json`` and the full-text cache; writing them in place let one
    process read another's half-written file and fail to parse it.
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        _replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def atomic_write_text(path: Path, text: str, *, mode: int = 0o600, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding), mode=mode)


def _replace(src: Path, dst: Path) -> None:
    # On Windows the target can be briefly held open by a reader or a virus scanner, which
    # makes os.replace raise PermissionError; a few short retries ride that out.
    for attempt in range(6):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.02 * (attempt + 1))
