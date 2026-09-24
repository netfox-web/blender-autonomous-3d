"""Small host flush primitives; success is not a tested power-loss guarantee."""
import errno
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path


class CommitIndeterminate(OSError):
    """Namespace changed, but its following synchronization did not complete.

    Do not retry/rollback the mutation. A later reader must use the existing
    authority verifier; this exception is not a second on-disk authority.
    """
    def __init__(self, path, operation, cause):
        self.path = str(path)
        self.operation = operation
        super().__init__(cause.errno or errno.EIO,
                         f'COMMIT_INDETERMINATE: {operation} namespace sync failed: {cause}', str(path))


def dam_identity(source):
    """Return strict authoritative DAM digest/size metadata for a worker artifact."""
    digest = getattr(source, 'sha256', None)
    if type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
        raise ValueError('worker DAM sha256 missing or malformed')
    metadata = getattr(source, 'metadata', {})
    if not isinstance(metadata, dict):
        raise ValueError('worker DAM metadata malformed')
    size = metadata.get('bytes', metadata.get('size'))
    if size is not None and (type(size) is not int or size < 0):
        raise ValueError('worker DAM size malformed')
    return digest, size


def _kernel():
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel.FlushFileBuffers.restype = wintypes.BOOL
    return kernel


def flush_file(stream):
    """Flush complete runtime bytes, then the still-open host file handle."""
    stream.flush()
    if sys.platform == 'win32':
        import ctypes
        import msvcrt
        if not _kernel().FlushFileBuffers(msvcrt.get_osfhandle(stream.fileno())):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.fsync(stream.fileno())


def sync_directory(directory):
    """Request namespace persistence on the exercised Linux / Windows NTFS surface.

    MS-FSA 2.1.5.7, product-behavior note 80: non-NTFS Windows filesystems may
    return success without persisting directory structure. Reject that surface.
    Errors must propagate; no silent unsupported-platform fallback.
    """
    if sys.platform != 'win32':
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return
    import ctypes
    from ctypes import wintypes
    kernel = _kernel()
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetVolumeInformationByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
        wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPDWORD, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumeInformationByHandleW.restype = wintypes.BOOL
    # Writable directory handle, full sharing, no volume handle or elevation.
    handle = kernel.CreateFileW(str(directory.absolute()), 0x40000000, 0x1 | 0x2 | 0x4,
                                None, 3, 0x02000000, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        filesystem = ctypes.create_unicode_buffer(32)
        if not kernel.GetVolumeInformationByHandleW(handle, None, 0, None, None, None, filesystem, len(filesystem)):
            raise ctypes.WinError(ctypes.get_last_error())
        if filesystem.value != 'NTFS':
            raise OSError(errno.ENOTSUP, 'Directory durability requires the exercised NTFS surface')
        if not kernel.FlushFileBuffers(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if not kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def namespace_committed(path, operation):
    """Call only after a successful namespace mutation; never roll it back."""
    try:
        sync_directory(path.parent)
    except OSError as exc:
        raise CommitIndeterminate(path, operation, exc) from exc


def unlink_owned(path, *, missing_ok=False):
    """Existing owned-temp deletion plus its directory sync; no broader cleanup."""
    try:
        path.unlink()
    except FileNotFoundError:
        if not missing_ok:
            raise
    else:
        namespace_committed(path, 'unlink')


def publish_binary(source, target, *, expected_sha256=None, expected_size=None):
    """Copy one artifact through an owned same-directory durable temp."""
    source, target = Path(source), Path(target)
    if not source.is_file():
        raise FileNotFoundError(str(source))
    if target.is_symlink():
        raise ValueError('refuse symlink artifact target')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f'.{target.name}.artifact.{secrets.token_hex(8)}.tmp')
    digest = hashlib.sha256(); size = 0
    try:
        with source.open('rb') as src, temporary.open('xb') as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk); digest.update(chunk); size += len(chunk)
            flush_file(dst)
        if expected_size is not None and size != expected_size:
            raise ValueError('artifact size mismatch')
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise ValueError('artifact SHA mismatch')
        os.replace(temporary, target)
        namespace_committed(target, 'replace')
    except Exception:
        if temporary.exists():
            try: unlink_owned(temporary, missing_ok=True)
            except OSError: pass
        raise
    return {'sha256': digest.hexdigest(), 'size': size}


def publish_bytes(writer, target, *, expected_sha256=None, expected_size=None):
    """Publish bytes produced into a stream using the same artifact invariant."""
    target = Path(target)
    if target.is_symlink():
        raise ValueError('refuse symlink artifact target')
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f'.{target.name}.artifact.{secrets.token_hex(8)}.tmp')
    digest = hashlib.sha256(); size = 0
    try:
        class DigestingStream:
            def __init__(self, stream): self.stream = stream
            def write(self, data):
                nonlocal size
                digest.update(data); size += len(data)
                return self.stream.write(data)
            def flush(self): return self.stream.flush()
            def __getattr__(self, name): return getattr(self.stream, name)
        with temporary.open('xb') as raw:
            writer(DigestingStream(raw))
            flush_file(raw)
        if expected_size is not None and size != expected_size:
            raise ValueError('artifact size mismatch')
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise ValueError('artifact SHA mismatch')
        os.replace(temporary, target)
        namespace_committed(target, 'replace')
    except Exception:
        if temporary.exists():
            try: unlink_owned(temporary, missing_ok=True)
            except OSError: pass
        raise
    return {'sha256': digest.hexdigest(), 'size': size}


def verify_receipt(target, receipt):
    """Verify that the current regular file is still the published receipt."""
    target = Path(target)
    if target.is_symlink() or not target.is_file():
        raise ValueError('published artifact missing or non-regular')
    size = target.stat().st_size
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != receipt.get('sha256') or size != receipt.get('size'):
        raise ValueError('published artifact receipt mismatch')
    return {'sha256': digest, 'size': size}


def verify_receipt_set(folder, receipts, expected):
    """Verify the complete receipt-bound artifact set at an authority boundary."""
    if set(receipts) != set(expected):
        raise ValueError('publication receipt set mismatch')
    verified = {}
    for name in expected:
        verified[name] = verify_receipt(Path(folder) / name, receipts[name])
    return verified


def verify_manifest_meta(folder, manifest_sha):
    """Keep the validated manifest/meta pair bound to one transaction digest."""
    folder = Path(folder)
    manifest = folder / 'manifest.json'; meta = folder / 'meta.json'
    if manifest.is_symlink() or not manifest.is_file() or meta.is_symlink() or not meta.is_file():
        raise ValueError('manifest/meta authority is not regular')
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != manifest_sha:
        raise ValueError('manifest authority changed')
    try:
        record = json.loads(meta.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('invalid manifest metadata') from exc
    if record.get('manifestSha256') != manifest_sha:
        raise ValueError('manifest metadata changed')
    return manifest_sha


def verify_publication_seal(path, manifest_sha):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('publication seal is not regular')
    try:
        record = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('invalid publication seal') from exc
    if record.get('manifestSha256') != manifest_sha:
        raise ValueError('publication seal mismatch')
    return record
