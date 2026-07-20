"""Phase 6 evaluation, engineering, recovery, and release loopback helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rsi_atlas_contracts import (
    BackupEncryptionStatus,
    CodexAuthorityAction,
    CodexCommandClass,
    ReleaseCheckReport,
    SafeModeCapability,
    SafeModeState,
)
from rsi_atlas_engineering import (
    authority_denial,
    build_candidate_patch,
    run_patch_quality_gate,
    sanitize_reproduction_bundle,
)
from rsi_atlas_evaluation import default_fixture_path, load_dataset, run_offline_evaluation
from rsi_atlas_recovery import (
    SafeModeController,
    create_workspace_backup,
    restore_verified,
    verify_backup,
)
from rsi_atlas_release import run_release_check

from rsi_atlas_engine.safe_mode import runtime_safe_mode


class Phase6Service:
    """In-process Phase 6 development surfaces for loopback APIs."""

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        safe_mode: SafeModeController | None = None,
    ) -> None:
        # rsi_atlas_engine -> src -> engine -> services -> repo root
        self.repo_root = repo_root or Path(__file__).resolve().parents[4]
        self.safe_mode = safe_mode or runtime_safe_mode()

    def run_evaluation(
        self,
        *,
        dataset_path: Path | None = None,
        include_judge: bool = False,
        actuals: dict[str, dict[str, Any]] | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, object]:
        path = dataset_path or default_fixture_path()
        dataset = load_dataset(path)
        run, decision = run_offline_evaluation(
            dataset,
            created_at=created_at or datetime.now(tz=UTC),
            include_judge=include_judge,
            actuals=actuals,
        )
        return {
            "dataset_id": dataset.dataset_id,
            "run": run.model_dump(mode="json"),
            "promotion": decision.model_dump(mode="json"),
        }

    def codex_gate(
        self,
        *,
        failure_summary: str,
        raw_inputs: dict[str, Any],
        expected_behavior: str,
        actual_behavior: str,
        diff_text: str,
        created_at: datetime | None = None,
    ) -> dict[str, object]:
        now = created_at or datetime.now(tz=UTC)
        bundle = sanitize_reproduction_bundle(
            failure_summary=failure_summary,
            source_versions={"engine": "0.1.0"},
            raw_inputs=raw_inputs,
            expected_behavior=expected_behavior,
            actual_behavior=actual_behavior,
            deterministic_validator_results=(),
            permitted_commands=(CodexCommandClass.READ_SOURCE, CodexCommandClass.TEST),
            worktree_hint="tmp/codex-worktrees/loopback",
            created_at=now,
        )
        patch = build_candidate_patch(bundle, diff_text=diff_text, created_at=now)
        gated, gate = run_patch_quality_gate(
            patch,
            diff_text=diff_text,
            created_at=now,
            test_evidence=(),
        )
        denials = [
            authority_denial(action).model_dump(mode="json")
            for action in (
                CodexAuthorityAction.MERGE,
                CodexAuthorityAction.PUSH,
                CodexAuthorityAction.DEPLOY,
                CodexAuthorityAction.PROMOTE_EVALUATION,
            )
        ]
        return {
            "bundle": bundle.model_dump(mode="json"),
            "patch": gated.model_dump(mode="json"),
            "gate": gate.model_dump(mode="json"),
            "authority_denials": denials,
        }

    def create_backup(
        self,
        *,
        source_root: Path,
        destination_root: Path,
        created_at: datetime | None = None,
    ) -> dict[str, object]:
        manifest = create_workspace_backup(
            source_root,
            destination_root,
            created_at=created_at or datetime.now(tz=UTC),
            encryption_status=BackupEncryptionStatus.PLAINTEXT_DEV_ONLY,
        )
        return manifest.model_dump(mode="json")

    def restore_verify(
        self, *, backup_root: Path, destination: Path | None = None
    ) -> dict[str, object]:
        if destination is None:
            verification = verify_backup(backup_root)
        else:
            verification = restore_verified(backup_root, destination)
        return verification.model_dump(mode="json")

    def enter_safe_mode(self, *, reason: str, entered_at: datetime | None = None) -> SafeModeState:
        return self.safe_mode.enter(reason=reason, entered_at=entered_at or datetime.now(tz=UTC))

    def safe_mode_state(self) -> SafeModeState:
        self.safe_mode.is_disabled(SafeModeCapability.COLLECTORS)
        return self.safe_mode.state

    def exit_safe_mode(self) -> SafeModeState:
        return self.safe_mode.exit()

    def release_check(self, *, require_release: bool = False) -> ReleaseCheckReport:
        return run_release_check(repo_root=self.repo_root, require_release=require_release)
