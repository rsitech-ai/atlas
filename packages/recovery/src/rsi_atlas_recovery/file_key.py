"""Owner file-key AES-GCM backup encryption (no Keychain required)."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_KEY_BYTES = 32
_NONCE_BYTES = 12


class FileKeyError(RuntimeError):
    """Raised when the owner key file is missing or unsafe."""


def generate_owner_key_file(path: Path) -> Path:
    """Write a 32-byte key with mode 0600. Never overwrite an existing key."""
    if path.exists():
        raise FileKeyError(f"key file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(secrets.token_bytes(_KEY_BYTES))
    os.chmod(path, 0o600)
    return path


def load_owner_key(path: Path) -> bytes:
    if not path.is_file():
        raise FileKeyError(f"owner key missing: {path}")
    key = path.read_bytes()
    if len(key) != _KEY_BYTES:
        raise FileKeyError("owner key must be exactly 32 bytes")
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise FileKeyError(f"owner key permissions too open: {oct(mode)}")
    return key


def encrypt_bytes(plaintext: bytes, *, key: bytes) -> bytes:
    nonce = secrets.token_bytes(_NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt_bytes(blob: bytes, *, key: bytes) -> bytes:
    if len(blob) < _NONCE_BYTES + 16:
        raise FileKeyError("ciphertext too short")
    nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, ct, None)


__all__ = [
    "FileKeyError",
    "decrypt_bytes",
    "encrypt_bytes",
    "generate_owner_key_file",
    "load_owner_key",
]
