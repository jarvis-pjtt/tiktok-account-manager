"""Small secret store: Windows DPAPI (CryptProtectData) so saved passwords only decrypt for this Windows user."""
from __future__ import annotations

import base64
import ctypes
import sys

PREFIX_DPAPI = "dpapi:"
PREFIX_B64 = "b64:"


if sys.platform == "win32":
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    def _to_blob(data: bytes) -> _DATA_BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _from_blob(blob: _DATA_BLOB) -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            _kernel32.LocalFree(blob.pbData)

    def _dpapi(data: bytes, encrypt: bool) -> bytes:
        blob_in = _to_blob(data)
        blob_out = _DATA_BLOB()
        fn = _crypt32.CryptProtectData if encrypt else _crypt32.CryptUnprotectData
        ok = fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
        if not ok:
            raise OSError("DPAPI call failed")
        return _from_blob(blob_out)
else:  # pragma: no cover
    def _dpapi(data: bytes, encrypt: bool) -> bytes:
        raise OSError("DPAPI unavailable")


def protect(text: str) -> str:
    """Encrypt *text* for storage. Falls back to base64 (obfuscation only) off Windows."""
    if not text:
        return ""
    try:
        return PREFIX_DPAPI + base64.b64encode(_dpapi(text.encode("utf-8"), True)).decode("ascii")
    except Exception:
        return PREFIX_B64 + base64.b64encode(text.encode("utf-8")).decode("ascii")


def unprotect(token: str) -> str:
    if not token:
        return ""
    try:
        if token.startswith(PREFIX_DPAPI):
            return _dpapi(base64.b64decode(token[len(PREFIX_DPAPI):]), False).decode("utf-8")
        if token.startswith(PREFIX_B64):
            return base64.b64decode(token[len(PREFIX_B64):]).decode("utf-8")
    except Exception:
        return ""
    return ""
