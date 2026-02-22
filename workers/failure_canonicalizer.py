#!/usr/bin/env python3
"""Failure Canonicalizer - Step 4: Normalize failures into stable, canonical format."""

import hashlib
import json
from dataclasses import dataclass, asdict
from enum import Enum
from typing import List, Dict, Any, Optional
from pathlib import Path


class FailureKind(str, Enum):
    """Deterministic failure kind taxonomy."""
    COMPILE_ERROR = "compile_error"
    TEST_FAILURE = "test_failure"
    SNAPSHOT_DIFF = "snapshot_diff"
    CONTRACT_MISMATCH = "contract_mismatch"
    CONTRACT_VIOLATION = "contract_violation"
    POLICY_VIOLATION = "policy_violation"
    TYPE_ERROR = "type_error"
    LINT_ERROR = "lint_error"
    RUNTIME_EXCEPTION = "runtime_exception"
    VERIFIER_ERROR = "verifier_error"
    EXTERNAL_INPUT_VIOLATION = "external_input_violation"
    SNAPSHOT_VIOLATION = "snapshot_violation"
    INDEX_VIOLATION = "index_violation"
    PLANNER_VIOLATION = "planner_violation"
    ANSWER_VIOLATION = "answer_violation"


class FailureSeverity(str, Enum):
    """Failure severity levels."""
    BLOCKER = "BLOCKER"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


@dataclass
class CanonicalFailure:
    """Canonical failure representation with stable ID."""
    failure_id: str
    kind: FailureKind
    severity: FailureSeverity
    artifact: str
    locator: str  # file + line/col if available
    message: str  # verbatim or minimally normalized
    repro: str  # exact command or step identifier
    expected: Optional[str] = None
    actual: Optional[str] = None
    related: Optional[List[str]] = None  # links to check_id/test name
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        d["kind"] = self.kind.value
        d["severity"] = self.severity.value
        return d


def _sha256_bytes(b: bytes) -> str:
    """Compute SHA256 hash."""
    return hashlib.sha256(b).hexdigest()


def _normalize_message(msg: str) -> str:
    """Minimally normalize message (remove timestamps, normalize whitespace)."""
    # Remove common timestamp patterns
    import re
    msg = re.sub(r'\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}[.\d]*[Z]?', '', msg)
    msg = re.sub(r'\d{2}:\d{2}:\d{2}', '', msg)
    # Normalize whitespace
    msg = ' '.join(msg.split())
    return msg.strip()


def compute_failure_id(
    kind: FailureKind,
    artifact: str,
    locator: str,
    repro: str,
    message: str,
    expected: Optional[str] = None,
    actual: Optional[str] = None,
) -> str:
    """
    Compute stable failure_id deterministically.
    
    Formula: sha256(kind + artifact + locator + repro + expected_hash + actual_hash + message_norm)
    """
    message_norm = _normalize_message(message)
    expected_hash = _sha256_bytes((expected or "").encode("utf-8"))[:16] if expected else ""
    actual_hash = _sha256_bytes((actual or "").encode("utf-8"))[:16] if actual else ""
    
    combined = f"{kind.value}:{artifact}:{locator}:{repro}:{expected_hash}:{actual_hash}:{message_norm}"
    return _sha256_bytes(combined.encode("utf-8"))[:32]


def canonicalize_failure(
    kind: FailureKind,
    artifact: str,
    locator: str,
    message: str,
    repro: str,
    severity: FailureSeverity = FailureSeverity.BLOCKER,
    expected: Optional[str] = None,
    actual: Optional[str] = None,
    related: Optional[List[str]] = None,
) -> CanonicalFailure:
    """
    Create canonical failure with stable ID.
    
    Args:
        kind: Failure kind
        artifact: File/module name or logical artifact
        locator: File + line/col if available
        message: Verbatim or minimally normalized message
        repro: Exact command or step identifier
        severity: Failure severity
        expected: Expected value (if available)
        actual: Actual value (if available)
        related: Related check IDs or test names
    
    Returns:
        CanonicalFailure with stable failure_id
    """
    failure_id = compute_failure_id(kind, artifact, locator, repro, message, expected, actual)
    
    return CanonicalFailure(
        failure_id=failure_id,
        kind=kind,
        severity=severity,
        artifact=artifact,
        locator=locator,
        message=message,
        repro=repro,
        expected=expected,
        actual=actual,
        related=related or [],
    )


def sort_failures(failures: List[CanonicalFailure]) -> List[CanonicalFailure]:
    """
    Sort failures deterministically.
    
    Order: kind → artifact → locator → message_hash
    """
    def sort_key(f: CanonicalFailure) -> tuple:
        message_hash = _sha256_bytes(f.message.encode("utf-8"))[:8]
        return (
            f.kind.value,
            f.artifact,
            f.locator,
            message_hash,
        )
    
    return sorted(failures, key=sort_key)


def canonicalize_from_compile_error(
    error_output: str,
    artifact: str,
    locator: str,
    repro: str,
) -> CanonicalFailure:
    """Canonicalize a compile error."""
    return canonicalize_failure(
        kind=FailureKind.COMPILE_ERROR,
        artifact=artifact,
        locator=locator,
        message=_normalize_message(error_output),
        repro=repro,
        severity=FailureSeverity.BLOCKER,
    )


def canonicalize_from_test_failure(
    test_name: str,
    error_output: str,
    artifact: str,
    locator: str,
    repro: str,
    expected: Optional[str] = None,
    actual: Optional[str] = None,
) -> CanonicalFailure:
    """Canonicalize a test failure."""
    return canonicalize_failure(
        kind=FailureKind.TEST_FAILURE,
        artifact=artifact,
        locator=locator,
        message=_normalize_message(error_output),
        repro=repro,
        severity=FailureSeverity.BLOCKER,
        expected=expected,
        actual=actual,
        related=[test_name] if test_name else None,
    )


def canonicalize_from_missing_artifact(
    artifact_name: str,
    locator: str,
    repro: str,
) -> CanonicalFailure:
    """Canonicalize a missing artifact failure."""
    return canonicalize_failure(
        kind=FailureKind.VERIFIER_ERROR,
        artifact=artifact_name,
        locator=locator,
        message=f"{artifact_name} missing or empty",
        repro=repro,
        severity=FailureSeverity.BLOCKER,
    )


def canonicalize_from_verifier_error(
    error_message: str,
    stack_trace: Optional[str] = None,
) -> CanonicalFailure:
    """Canonicalize a verifier internal error."""
    locator = "verifier"
    if stack_trace:
        # Extract file:line from stack trace if available
        import re
        match = re.search(r'File "([^"]+)", line (\d+)', stack_trace)
        if match:
            locator = f"{match.group(1)}:{match.group(2)}"
    
    return canonicalize_failure(
        kind=FailureKind.VERIFIER_ERROR,
        artifact="verifier",
        locator=locator,
        message=_normalize_message(error_message),
        repro="verifier_internal",
        severity=FailureSeverity.BLOCKER,
        actual=stack_trace if stack_trace else None,
    )

