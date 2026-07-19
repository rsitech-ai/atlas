"""Codex command approval policy."""

from __future__ import annotations

from rsi_atlas_contracts import (
    CodexApprovalDecision,
    CodexApprovalStatus,
    CodexCommandClass,
)

_POLICY: dict[CodexCommandClass, CodexApprovalStatus] = {
    CodexCommandClass.READ_SOURCE: CodexApprovalStatus.ALLOWED,
    CodexCommandClass.INSPECT: CodexApprovalStatus.ALLOWED,
    CodexCommandClass.FILE_CHANGE: CodexApprovalStatus.REQUIRES_EXPLICIT_APPROVAL,
    CodexCommandClass.TEST: CodexApprovalStatus.ALLOWED,
    CodexCommandClass.DEPENDENCY_INSTALL: CodexApprovalStatus.REQUIRES_EXPLICIT_APPROVAL,
    CodexCommandClass.NETWORK: CodexApprovalStatus.DENIED,
    CodexCommandClass.COMMIT: CodexApprovalStatus.REQUIRES_EXPLICIT_APPROVAL,
}


def decide_approval(command_class: CodexCommandClass) -> CodexApprovalDecision:
    status = _POLICY[command_class]
    reasons = {
        CodexApprovalStatus.ALLOWED: "policy_allowed",
        CodexApprovalStatus.REQUIRES_EXPLICIT_APPROVAL: "requires_explicit_approval",
        CodexApprovalStatus.DENIED: "denied_by_strict_policy",
    }
    return CodexApprovalDecision(
        command_class=command_class,
        status=status,
        reason=reasons[status],
    )
