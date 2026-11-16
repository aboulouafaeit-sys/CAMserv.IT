"""
camserv.platform.windows.credentials
===================================

Microsoft Windows Data Protection API (DPAPI) credential vault.
Uses Win32 CryptProtectData and CryptUnprotectData (via crypt32.dll)
to encrypt master encryption keys and camera secrets bound to the local machine context.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from typing import Any

import structlog

from camserv.platform.shared.credentials import StandardSoftwareCredentialVault
from camserv.platform.shared.interfaces import PlatformCredentialVault

logger = structlog.get_logger(__name__)

# Win32 Constants
_CRYPTPROTECT_LOCAL_MACHINE = 0x4
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class WindowsDPAPIVault(PlatformCredentialVault):
    """
    Hardware and machine-bound secret vault leveraging Windows DPAPI.
    Eliminates plaintext master secrets from Windows configuration files.
    """

    def __init__(self, fallback_key: str | bytes | None = None) -> None:
        self._is_windows = os.name == "nt"
        self._software_fallback = StandardSoftwareCredentialVault(master_key=fallback_key)

    def is_hardware_bound(self) -> bool:
        """DPAPI tied to machine security credentials and hardware TPM/LSA state."""
        return self._is_windows

    def protect_secret(self, secret_bytes: bytes, description: str = "camserv_master_secret") -> bytes:
        """Encrypt secret bytes with Windows DPAPI CryptProtectData."""
        if not self._is_windows:
            return self._software_fallback.protect_secret(secret_bytes, description=description)

        cb = len(secret_bytes)
        buf = (ctypes.c_byte * cb)(*secret_bytes)
        blob_in = DATA_BLOB(cb, ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        blob_out = DATA_BLOB()

        flags = _CRYPTPROTECT_LOCAL_MACHINE | _CRYPTPROTECT_UI_FORBIDDEN
        res = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            description,
            None,
            None,
            None,
            flags,
            ctypes.byref(blob_out),
        )

        if not res:
            err = ctypes.GetLastError()
            logger.warning("windows.dpapi.protect_failed_falling_back", error=err)
            return self._software_fallback.protect_secret(secret_bytes, description=description)

        try:
            out_bytes = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return out_bytes
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)

    def unprotect_secret(self, encrypted_bytes: bytes, description: str = "camserv_master_secret") -> bytes:
        """Decrypt secret bytes with Windows DPAPI CryptUnprotectData."""
        if not self._is_windows:
            return self._software_fallback.unprotect_secret(encrypted_bytes, description=description)

        cb = len(encrypted_bytes)
        buf = (ctypes.c_byte * cb)(*encrypted_bytes)
        blob_in = DATA_BLOB(cb, ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
        blob_out = DATA_BLOB()

        flags = _CRYPTPROTECT_LOCAL_MACHINE | _CRYPTPROTECT_UI_FORBIDDEN
        res = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            flags,
            ctypes.byref(blob_out),
        )

        if not res:
            # Check if this payload was encrypted by the software fallback
            try:
                return self._software_fallback.unprotect_secret(encrypted_bytes, description=description)
            except Exception:
                err = ctypes.GetLastError()
                raise OSError(f"Windows DPAPI CryptUnprotectData failed: error code {err}")

        try:
            decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            return decrypted
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
