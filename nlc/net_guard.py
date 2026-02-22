#!/usr/bin/env python3
"""
Process-level network guard for v1 structured builds and replay.

On activation: monkeypatches socket, urllib, requests so any network attempt
raises NetworkGuardError with POLICY.NETWORK.DISALLOWED. Structural guarantee,
not behavioral. Must be activated BEFORE any code that might call network.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Tuple, Type

POLICY_NETWORK_DISALLOWED = "POLICY.NETWORK.DISALLOWED"


class NetworkGuardError(Exception):
    """Deterministic exception on any network attempt when guard is active."""

    def __init__(self, msg: str = "", context: str = ""):
        detail = f"{POLICY_NETWORK_DISALLOWED}"
        if context:
            detail += f": {context}"
        if msg and context != msg:
            detail += f" ({msg})"
        super().__init__(detail)
        self.canonical_id = POLICY_NETWORK_DISALLOWED
        self.context = context or msg


def repro_mode_enabled() -> bool:
    from dcs_core.repro_env import is_repro_mode
    return is_repro_mode()


def _guard_blocker(context: str) -> Callable[..., None]:
    def _block(*args: Any, **kwargs: Any) -> None:
        raise NetworkGuardError(context=context)
    return _block


_ACTIVE = False
_ORIGINAL: dict[str, Any] = {}


def _save_and_patch(module_name: str, attr: str, replacement: Any) -> None:
    """Save original and replace. Idempotent if already patched."""
    import importlib
    mod = __import__(module_name)
    for part in module_name.split(".")[1:]:
        mod = getattr(mod, part)
    key = f"{module_name}.{attr}"
    if key not in _ORIGINAL:
        _ORIGINAL[key] = getattr(mod, attr)
    setattr(mod, attr, replacement)


def activate_network_guard() -> None:
    """
    Activate process-level network block. Monkeypatch socket, urllib, requests.
    Any network attempt raises NetworkGuardError with POLICY.NETWORK.DISALLOWED.
    Idempotent: safe to call multiple times.
    """
    global _ACTIVE
    if _ACTIVE:
        return
    _ACTIVE = True

    # 1. socket: wrap socket class to raise on connect/create_connection
    import socket as _socket_mod
    _original_socket = _socket_mod.socket
    _orig_create = getattr(_socket_mod, "create_connection", None)

    class _BlockingSocket(_original_socket):
        """Socket subclass that raises on any connect attempt."""

        def connect(self, *args: Any, **kwargs: Any) -> None:
            raise NetworkGuardError(context="socket.connect")

        def connect_ex(self, *args: Any, **kwargs: Any) -> Any:
            raise NetworkGuardError(context="socket.connect_ex")

    _ORIGINAL["socket.socket"] = _original_socket
    _socket_mod.socket = _BlockingSocket
    if _orig_create is not None:
        def _blocked_create(*args: Any, **kwargs: Any) -> Any:
            raise NetworkGuardError(context="socket.create_connection")
        _ORIGINAL["socket.create_connection"] = _orig_create
        _socket_mod.create_connection = _blocked_create

    # 2. urllib.request.urlopen (must run after socket patch; urllib uses socket)
    try:
        import urllib.request as _urllib_request
        _orig_urlopen = _urllib_request.urlopen

        def _blocked_urlopen(*args: Any, **kwargs: Any) -> Any:
            raise NetworkGuardError(context="urllib.request.urlopen")
        _ORIGINAL["urllib.request.urlopen"] = _orig_urlopen
        _urllib_request.urlopen = _blocked_urlopen
    except ImportError:
        pass

    # 4. requests.get, requests.post, requests.request, requests.Session
    try:
        import requests as _requests_mod
        for method in ("get", "post", "put", "delete", "patch", "head", "request"):
            _orig = getattr(_requests_mod, method, None)
            if callable(_orig):
                def _blocker(name: str = method):
                    def _block(*a: Any, **kw: Any) -> Any:
                        raise NetworkGuardError(context=f"requests.{name}")
                    return _block
                _ORIGINAL[f"requests.{method}"] = _orig
                setattr(_requests_mod, method, _blocker(method))
        _orig_session = _requests_mod.Session

        def _blocked_session(*args: Any, **kwargs: Any) -> Any:
            raise NetworkGuardError(context="requests.Session")
        _ORIGINAL["requests.Session"] = _orig_session
        _requests_mod.Session = _blocked_session
    except ImportError:
        pass


def is_active() -> bool:
    return _ACTIVE


def deactivate_network_guard() -> None:
    """Restore original implementations. For tests only."""
    global _ACTIVE
    if not _ACTIVE:
        return
    import socket as _socket_mod
    if "socket.socket" in _ORIGINAL:
        _socket_mod.socket = _ORIGINAL["socket.socket"]
    if "socket.create_connection" in _ORIGINAL:
        _socket_mod.create_connection = _ORIGINAL["socket.create_connection"]
    try:
        import urllib.request as _urllib_request
        if "urllib.request.urlopen" in _ORIGINAL:
            _urllib_request.urlopen = _ORIGINAL["urllib.request.urlopen"]
    except ImportError:
        pass
    try:
        import requests as _requests_mod
        for k, v in _ORIGINAL.items():
            if k.startswith("requests."):
                attr = k.split(".")[1]
                setattr(_requests_mod, attr, v)
    except ImportError:
        pass
    _ORIGINAL.clear()
    _ACTIVE = False


def log_network_attempt(context: str) -> None:
    p = os.environ.get("NLC_NET_LOG")
    if not p:
        return
    try:
        path = Path(p)
        path.parent.mkdir(parents=True, exist_ok=True)
        prev = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        path.write_text(prev + context + "\n", encoding="utf-8")
    except Exception:
        pass


def assert_network_allowed(context: str = "") -> None:
    """Legacy: used by some modules. Raises if guard active or NLC_REPRO."""
    if is_active():
        ctx = context or "network"
        log_network_attempt(ctx)
        raise NetworkGuardError(context=ctx)
    if repro_mode_enabled():
        ctx = context or "network"
        log_network_attempt(ctx)
        raise NetworkGuardError(context=ctx)
