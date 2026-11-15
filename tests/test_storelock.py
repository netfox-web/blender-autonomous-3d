from pathlib import Path
from unittest.mock import patch

import pytest

from fox3d.storelock import FileLock


def test_acquire_and_release(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "lock")
    with lock:
        assert lock._fh is not None
        assert lock._acquired
    assert lock._fh is None
    assert not lock._acquired
    lock.release()
    lock.release()


def test_timeout_closes_file_and_lock_can_be_reacquired(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    first = FileLock(path)
    second = FileLock(path, timeout=0.05)
    with first:
        with pytest.raises(TimeoutError), second:
            pytest.fail("contended lock was acquired")
        assert second._fh is None
        assert not second._acquired
    with FileLock(path, timeout=0.05) as third:
        assert third._acquired


def test_blocked_marker_written_once(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    marker = tmp_path / "marker"
    with FileLock(path), patch.object(Path, "write_text", autospec=True) as write:
        with pytest.raises(TimeoutError):
            FileLock(path, timeout=0.05, blocked_marker=marker).acquire()
    write.assert_called_once_with(marker, "waiting", encoding="utf-8")


def test_unexpected_acquire_exception_closes_file(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    second = FileLock(path)
    with FileLock(path), patch("fox3d.storelock.time.sleep", side_effect=RuntimeError("failure")):
        with pytest.raises(RuntimeError, match="failure"):
            second.acquire()
    assert second._fh is None
    assert not second._acquired
