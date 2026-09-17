"""Local OS-backed generation ownership; never publication/product authority.

The persistent, empty file is only a stable lock inode. Never unlink it or infer
ownership from its existence/mtime. The kernel releases ownership on process exit.
"""
import errno
import os


class PreviewBusy(ValueError):
    pass


class PreviewOwnership:
    def __init__(self, folder):
        folder.mkdir(parents=True, exist_ok=True)
        self.folder = folder.resolve()
        self.stream = (self.folder / 'owner.lock').open('a+b')
        self.held = False
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.held = True
        except OSError as exc:
            self.stream.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise PreviewBusy('此商品已有生成工作，請完成或取消後再試') from exc
            raise

    def close(self):
        # Closing this non-inheritable handle releases only this acquisition.
        self.held = False
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
