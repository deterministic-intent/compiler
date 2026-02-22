#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class UXMode:
    isatty: bool
    json: bool
    replay: bool
    spinner: str
    effects_env: str


def should_banner(mode: UXMode) -> bool:
    return mode.isatty and (not mode.json) and (not mode.replay)


def should_spinner(mode: UXMode) -> bool:
    if not mode.isatty:
        return False
    if mode.json or mode.replay:
        return False
    if str(mode.spinner).strip().lower() not in ("auto", "on"):
        return False
    if str(mode.effects_env).strip() in ("0", "false", "no"):
        return False
    return True


def should_fallback(mode: UXMode) -> bool:
    # Fallback required whenever spinner is disabled, except in replay/json.
    if mode.json or mode.replay:
        return False
    return not should_spinner(mode)


class _Spinner:
    def __init__(self, message: str):
        self.message = message
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def start(self) -> None:
        # Print one frame synchronously so very fast commands still show a spinner at least once.
        # This writes to stderr so stdout stays clean/stable for piping/json.
        sys.stderr.write(f"\r{self.message} -")
        sys.stderr.flush()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.0)
        # clear line
        sys.stderr.write("\r" + (" " * (len(self.message) + 4)) + "\r")
        sys.stderr.flush()

    def _run(self) -> None:
        # ASCII-only spinner frames (terminal-safe).
        frames = ["-", "\\", "|", "/"]
        i = 1
        while not self._stop.is_set():
            sys.stderr.write(f"\r{self.message} {frames[i % len(frames)]}")
            sys.stderr.flush()
            i += 1
            time.sleep(0.08)


class GateProgress:
    def __init__(self, mode: UXMode, label: str):
        self.mode = mode
        self.label = label
        self._spinner: _Spinner | None = None

    def __enter__(self):
        if not self.mode.json and (not self.mode.replay):
            sys.stdout.write(f"[loading] {self.label}\n")
            sys.stdout.flush()
        if should_spinner(self.mode):
            self._spinner = _Spinner(self.label)
            self._spinner.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._spinner:
            self._spinner.stop()


def gate_line(gate_n: int, gate_label: str, dots: str, status_word: str) -> str:
    return f"[gate {gate_n}] {gate_label} {dots} {status_word}\n"


def map_status_for_line(gate_n: int, gate_status: str) -> str:
    gs = str(gate_status or "").strip().upper()
    ok = gs == "PASS"
    # Locked UX: verifier shows PASS/FAIL, everything else shows OK/FAIL.
    if gate_n == 3:
        return "PASS" if ok else "FAIL"
    return "OK" if ok else "FAIL"


def emit_gate_status(mode: UXMode, gate_n: int, gate_label: str, dots: str, gate_status: str) -> None:
    if mode.json:
        return
    status_word = map_status_for_line(gate_n, gate_status)
    sys.stdout.write(gate_line(gate_n, gate_label, dots, status_word))
    sys.stdout.flush()

