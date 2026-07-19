"""OSS/heuristic semantic triage with calibration harness (fail-closed when uncalibrated)."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import dumps, loads
from pathlib import Path

from rsi_atlas_contracts import (
    SemanticTriageDecision,
    SemanticTriageGate,
    SemanticTriageRequest,
    SemanticTriageStatus,
    TriageSeverity,
)

from rsi_atlas_monitoring.errors import SemanticTriageBlocked

# Escalation lexicon — ponytail: ceiling=keyword heuristic; upgrade=calibrated local classifier.
_ESCALATE = frozenset({"exploit", "hack", "drain", "reentrancy", "rug", "insolvent"})
_INVESTIGATE = frozenset({"reorg", "halt", "pause", "anomaly", "breach", "oracle"})
_WATCH = frozenset({"delay", "degraded", "gap", "stale", "elevated"})


@dataclass(frozen=True, slots=True)
class TriageCalibration:
    calibration_id: str
    agreement: float
    false_acceptance: float
    false_rejection: float
    frozen: bool

    def is_promotable(self) -> bool:
        return (
            self.frozen
            and self.agreement >= 0.8
            and self.false_acceptance <= 0.1
            and self.false_rejection <= 0.2
        )


def load_calibration(path: Path) -> TriageCalibration:
    raw = path.read_text(encoding="utf-8")
    payload = loads(raw)
    return TriageCalibration(
        calibration_id=str(payload["calibration_id"]),
        agreement=float(payload["agreement"]),
        false_acceptance=float(payload["false_acceptance"]),
        false_rejection=float(payload["false_rejection"]),
        frozen=bool(payload.get("frozen", False)),
    )


def default_calibration_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "fixtures"
        / "monitoring"
        / "triage_calibration_v1.json"
    )


def refuse_semantic_triage(request: SemanticTriageRequest) -> SemanticTriageGate:
    """Legacy fail-closed entry when no calibration is supplied."""
    del request
    gate = SemanticTriageGate(
        status=SemanticTriageStatus.BLOCKED_SEMANTIC_TRIAGE,
        reason="calibrated semantic triage models are not promoted without calibration fixture",
    )
    raise SemanticTriageBlocked(gate.reason)


def run_heuristic_triage(
    request: SemanticTriageRequest,
    *,
    calibration: TriageCalibration | None = None,
    calibration_path: Path | None = None,
) -> SemanticTriageDecision:
    """Run keyword heuristic only when calibration is frozen and within thresholds."""
    cal = calibration
    if cal is None:
        path = calibration_path or default_calibration_path()
        if not path.is_file():
            gate = SemanticTriageGate(
                status=SemanticTriageStatus.HEURISTIC_UNCALIBRATED,
                reason="triage calibration fixture missing",
            )
            raise SemanticTriageBlocked(gate.reason)
        cal = load_calibration(path)
    if not cal.is_promotable():
        gate = SemanticTriageGate(
            status=SemanticTriageStatus.HEURISTIC_UNCALIBRATED,
            reason="triage calibration below promote thresholds",
        )
        raise SemanticTriageBlocked(gate.reason)

    tokens = {
        part
        for part in "".join(
            ch.lower() if ch.isalnum() else " " for ch in request.change_summary
        ).split()
        if len(part) > 2
    }
    matched: list[str] = []
    severity = TriageSeverity.IGNORE
    score = 0.0
    if tokens & _ESCALATE:
        severity = TriageSeverity.ESCALATE
        matched = sorted(tokens & _ESCALATE)
        score = 0.95
    elif tokens & _INVESTIGATE:
        severity = TriageSeverity.INVESTIGATE
        matched = sorted(tokens & _INVESTIGATE)
        score = 0.75
    elif tokens & _WATCH:
        severity = TriageSeverity.WATCH
        matched = sorted(tokens & _WATCH)
        score = 0.45
    return SemanticTriageDecision(
        alert_id=request.alert_id,
        status=SemanticTriageStatus.HEURISTIC_CALIBRATED,
        severity=severity,
        score=score,
        matched_terms=tuple(matched),
        calibration_id=cal.calibration_id,
        reason=f"heuristic_v1:{severity.value}",
    )


def calibration_content_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def calibration_fingerprint(cal: TriageCalibration) -> str:
    body = dumps(
        {
            "agreement": cal.agreement,
            "calibration_id": cal.calibration_id,
            "false_acceptance": cal.false_acceptance,
            "false_rejection": cal.false_rejection,
            "frozen": cal.frozen,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(body.encode("utf-8")).hexdigest()


__all__ = [
    "TriageCalibration",
    "calibration_content_hash",
    "calibration_fingerprint",
    "default_calibration_path",
    "load_calibration",
    "refuse_semantic_triage",
    "run_heuristic_triage",
]
