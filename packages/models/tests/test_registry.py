from __future__ import annotations

import hashlib
import os
import stat
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import rsi_atlas_models.registry as registry_module
from rsi_atlas_contracts.models import ModelArtifact, ModelCapability, ModelLifecycle
from rsi_atlas_models.registry import (
    ModelRegistry,
    ModelRegistryError,
    ModelRegistryErrorCode,
)

MODEL_BYTES = b"atlas-local-model-fixture\n"

ALLOWED_TRANSITIONS = {
    ModelLifecycle.IMPORTED: {ModelLifecycle.QUARANTINED, ModelLifecycle.RETIRED},
    ModelLifecycle.QUARANTINED: {ModelLifecycle.BENCHMARKING, ModelLifecycle.REJECTED},
    ModelLifecycle.BENCHMARKING: {ModelLifecycle.CANDIDATE, ModelLifecycle.REJECTED},
    ModelLifecycle.CANDIDATE: {ModelLifecycle.PRODUCTION, ModelLifecycle.REJECTED},
    ModelLifecycle.PRODUCTION: {ModelLifecycle.DEGRADED, ModelLifecycle.DEPRECATED},
    ModelLifecycle.DEGRADED: {ModelLifecycle.PRODUCTION, ModelLifecycle.DEPRECATED},
    ModelLifecycle.DEPRECATED: {ModelLifecycle.RETIRED},
    ModelLifecycle.RETIRED: set(),
    ModelLifecycle.REJECTED: set(),
}

PATH_TO_STATE = {
    ModelLifecycle.IMPORTED: (),
    ModelLifecycle.QUARANTINED: (ModelLifecycle.QUARANTINED,),
    ModelLifecycle.BENCHMARKING: (
        ModelLifecycle.QUARANTINED,
        ModelLifecycle.BENCHMARKING,
    ),
    ModelLifecycle.CANDIDATE: (
        ModelLifecycle.QUARANTINED,
        ModelLifecycle.BENCHMARKING,
        ModelLifecycle.CANDIDATE,
    ),
    ModelLifecycle.PRODUCTION: (
        ModelLifecycle.QUARANTINED,
        ModelLifecycle.BENCHMARKING,
        ModelLifecycle.CANDIDATE,
        ModelLifecycle.PRODUCTION,
    ),
    ModelLifecycle.DEGRADED: (
        ModelLifecycle.QUARANTINED,
        ModelLifecycle.BENCHMARKING,
        ModelLifecycle.CANDIDATE,
        ModelLifecycle.PRODUCTION,
        ModelLifecycle.DEGRADED,
    ),
    ModelLifecycle.DEPRECATED: (
        ModelLifecycle.QUARANTINED,
        ModelLifecycle.BENCHMARKING,
        ModelLifecycle.CANDIDATE,
        ModelLifecycle.PRODUCTION,
        ModelLifecycle.DEPRECATED,
    ),
    ModelLifecycle.RETIRED: (ModelLifecycle.RETIRED,),
    ModelLifecycle.REJECTED: (ModelLifecycle.QUARANTINED, ModelLifecycle.REJECTED),
}


def _write_model(path: Path, content: bytes = MODEL_BYTES) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _artifact(
    path: Path,
    *,
    artifact_id: UUID | None = None,
    content: bytes = MODEL_BYTES,
    sha256: str | None = None,
    lifecycle: ModelLifecycle = ModelLifecycle.IMPORTED,
) -> ModelArtifact:
    return ModelArtifact(
        artifact_id=artifact_id or uuid4(),
        sha256=sha256 or hashlib.sha256(content).hexdigest(),
        provider_family="local_mlx",
        upstream_id="rsitech/atlas-model.v1",
        architecture="transformer_v2",
        parameter_class="small_7b",
        quantization="q4_k_m",
        tokenizer_sha256="b" * 64,
        context_tokens=131_072,
        license_id="Apache-2.0",
        source_manifest_artifact_id="sha256:" + "c" * 64,
        local_path=path,
        capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
        capability_results=frozenset({"schema_valid_v1"}),
        approved_tasks=frozenset({"research_planner"}),
        lifecycle=lifecycle,
    )


def _assert_error(code: ModelRegistryErrorCode, operation: object) -> None:
    with pytest.raises(ModelRegistryError) as error:
        operation()  # type: ignore[operator]
    assert error.value.code is code
    assert str(error.value) == code.value


def _registry_at_state(tmp_path: Path, state: ModelLifecycle) -> tuple[ModelRegistry, UUID]:
    path = _write_model(tmp_path / f"{state.value}.gguf")
    artifact = _artifact(path)
    registry = ModelRegistry()
    registry.register(artifact)
    for transition in PATH_TO_STATE[state]:
        registry.transition(artifact.artifact_id, transition)
    return registry, artifact.artifact_id


def test_registers_descriptor_bound_artifact_without_mutating_file(tmp_path: Path) -> None:
    path = _write_model(tmp_path / "model.gguf")
    before = path.stat()
    artifact = _artifact(path)
    registry = ModelRegistry()

    registered = registry.register(artifact)

    after = path.stat()
    assert registered == artifact
    assert registry.get(artifact.artifact_id) == artifact
    assert (after.st_dev, after.st_ino, after.st_mode, after.st_size) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
    )


@pytest.mark.parametrize(
    ("prepare", "code"),
    [
        (lambda root: root / "missing.gguf", ModelRegistryErrorCode.ARTIFACT_UNAVAILABLE),
        (
            lambda root: _write_model(root / "wrong-hash.gguf"),
            ModelRegistryErrorCode.ARTIFACT_HASH_MISMATCH,
        ),
    ],
)
def test_registration_rejects_missing_or_hash_mismatched_file(
    tmp_path: Path,
    prepare: object,
    code: ModelRegistryErrorCode,
) -> None:
    path = prepare(tmp_path)  # type: ignore[operator]
    artifact = _artifact(path, sha256="0" * 64)
    registry = ModelRegistry()

    _assert_error(code, lambda: registry.register(artifact))
    assert registry.snapshot() == ()


def test_registration_rejects_symlinked_file_and_ancestor(tmp_path: Path) -> None:
    target = _write_model(tmp_path / "target.gguf")
    symlink = tmp_path / "model-link.gguf"
    symlink.symlink_to(target)
    real_parent = tmp_path / "real-parent"
    model = _write_model(real_parent / "model.gguf")
    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(real_parent, target_is_directory=True)
    registry = ModelRegistry()

    _assert_error(
        ModelRegistryErrorCode.UNSAFE_ARTIFACT_PATH,
        lambda: registry.register(_artifact(symlink)),
    )
    _assert_error(
        ModelRegistryErrorCode.UNSAFE_ARTIFACT_PATH,
        lambda: registry.register(_artifact(parent_link / model.name)),
    )


def test_registration_rejects_hardlink_fifo_device_and_mutable_mode(tmp_path: Path) -> None:
    source = _write_model(tmp_path / "source.gguf")
    hardlink = tmp_path / "hardlink.gguf"
    os.link(source, hardlink)
    fifo = tmp_path / "model.fifo"
    os.mkfifo(fifo, 0o600)
    mutable = _write_model(tmp_path / "mutable.gguf")
    mutable.chmod(0o620)
    registry = ModelRegistry()

    for path in (hardlink, fifo, Path("/dev/null"), mutable):
        _assert_error(
            ModelRegistryErrorCode.UNSAFE_ARTIFACT_FILE,
            lambda path=path: registry.register(_artifact(path.resolve(strict=False))),
        )


def test_registration_rejects_wrong_file_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_model(tmp_path / "owner.gguf")
    artifact = _artifact(path)
    registry = ModelRegistry()
    real_fstat = registry_module.os.fstat

    def different_file_owner(descriptor: int) -> os.stat_result:
        result = real_fstat(descriptor)
        if stat.S_ISREG(result.st_mode):
            fields = list(result)
            fields[4] = os.getuid() + 1
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(registry_module.os, "fstat", different_file_owner)

    _assert_error(
        ModelRegistryErrorCode.UNSAFE_ARTIFACT_FILE,
        lambda: registry.register(artifact),
    )


def test_registration_rejects_oversized_file_and_bounds_hash_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"x" * (2 * 1024 * 1024 + 17)
    path = _write_model(tmp_path / "large.gguf", content)
    artifact = _artifact(path, content=content)

    _assert_error(
        ModelRegistryErrorCode.ARTIFACT_TOO_LARGE,
        lambda: ModelRegistry(max_bytes=len(content) - 1).register(artifact),
    )

    read_sizes: list[int] = []
    original_read = registry_module.os.read

    def bounded_read(descriptor: int, size: int) -> bytes:
        read_sizes.append(size)
        return original_read(descriptor, size)

    monkeypatch.setattr(registry_module.os, "read", bounded_read)
    assert ModelRegistry(max_bytes=len(content)).register(artifact) == artifact
    assert read_sizes
    assert max(read_sizes) <= 1024 * 1024


def test_registration_rejects_file_replacement_after_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_model(tmp_path / "model.gguf")
    moved = tmp_path / "moved.gguf"
    artifact = _artifact(path)
    registry = ModelRegistry()
    original_hash = registry._hash_descriptor

    def replace_after_hash(descriptor: int) -> str:
        digest = original_hash(descriptor)
        path.rename(moved)
        _write_model(path)
        return digest

    monkeypatch.setattr(registry, "_hash_descriptor", replace_after_hash)

    _assert_error(
        ModelRegistryErrorCode.ARTIFACT_IDENTITY_CHANGED,
        lambda: registry.register(artifact),
    )
    assert registry.snapshot() == ()


def test_registration_rejects_ancestor_replacement_after_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "models"
    path = _write_model(parent / "model.gguf")
    moved_parent = tmp_path / "moved-models"
    artifact = _artifact(path)
    registry = ModelRegistry()
    original_hash = registry._hash_descriptor

    def replace_ancestor_after_hash(descriptor: int) -> str:
        digest = original_hash(descriptor)
        parent.rename(moved_parent)
        parent.mkdir(mode=0o700)
        _write_model(parent / path.name)
        return digest

    monkeypatch.setattr(registry, "_hash_descriptor", replace_ancestor_after_hash)

    _assert_error(
        ModelRegistryErrorCode.ARTIFACT_IDENTITY_CHANGED,
        lambda: registry.register(artifact),
    )


def test_duplicate_uuid_and_hash_have_exact_distinct_semantics(tmp_path: Path) -> None:
    first_path = _write_model(tmp_path / "first.gguf", b"first")
    second_path = _write_model(tmp_path / "second.gguf", b"second")
    first = _artifact(first_path, content=b"first")
    duplicate_id = _artifact(second_path, artifact_id=first.artifact_id, content=b"second")
    duplicate_hash = _artifact(second_path, content=b"first", sha256=first.sha256)
    registry = ModelRegistry()
    registry.register(first)

    _assert_error(
        ModelRegistryErrorCode.DUPLICATE_ARTIFACT_ID,
        lambda: registry.register(duplicate_id),
    )
    _assert_error(
        ModelRegistryErrorCode.DUPLICATE_ARTIFACT_HASH,
        lambda: registry.register(duplicate_hash),
    )
    assert registry.snapshot() == (first,)


def test_registry_snapshots_and_history_are_immutable_and_deterministic(tmp_path: Path) -> None:
    low_path = _write_model(tmp_path / "low.gguf", b"low")
    high_path = _write_model(tmp_path / "high.gguf", b"high")
    low = _artifact(low_path, artifact_id=UUID(int=1), content=b"low")
    high = _artifact(high_path, artifact_id=UUID(int=2), content=b"high")
    registry = ModelRegistry()
    registry.register(high)
    registry.register(low)

    assert registry.snapshot() == (low, high)
    current = registry.transition(low.artifact_id, ModelLifecycle.QUARANTINED)
    history = registry.history(low.artifact_id)
    assert history == (low, current)
    assert history[0] is not history[1]
    with pytest.raises(TypeError):
        history[0] = current  # type: ignore[index]


@pytest.mark.parametrize(
    ("source", "target"),
    [(source, target) for source, targets in ALLOWED_TRANSITIONS.items() for target in targets],
)
def test_every_allowed_lifecycle_edge(
    tmp_path: Path,
    source: ModelLifecycle,
    target: ModelLifecycle,
) -> None:
    registry, artifact_id = _registry_at_state(tmp_path, source)

    assert registry.transition(artifact_id, target).lifecycle is target


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (source, target)
        for source, targets in ALLOWED_TRANSITIONS.items()
        for target in ModelLifecycle
        if target not in targets
    ],
)
def test_every_forbidden_lifecycle_edge(
    tmp_path: Path,
    source: ModelLifecycle,
    target: ModelLifecycle,
) -> None:
    registry, artifact_id = _registry_at_state(tmp_path, source)

    _assert_error(
        ModelRegistryErrorCode.INVALID_LIFECYCLE_TRANSITION,
        lambda: registry.transition(artifact_id, target),
    )
    assert registry.get(artifact_id).lifecycle is source


def test_registration_requires_imported_lifecycle(tmp_path: Path) -> None:
    path = _write_model(tmp_path / "candidate.gguf")
    registry = ModelRegistry()

    _assert_error(
        ModelRegistryErrorCode.INVALID_INITIAL_LIFECYCLE,
        lambda: registry.register(_artifact(path, lifecycle=ModelLifecycle.CANDIDATE)),
    )


def test_registration_requires_exact_model_artifact_type(tmp_path: Path) -> None:
    class ExtendedModelArtifact(ModelArtifact):
        reviewer_note: str

    path = _write_model(tmp_path / "extended.gguf")
    values = _artifact(path).model_dump()
    extended = ExtendedModelArtifact(**values, reviewer_note="untrusted extension")
    registry = ModelRegistry()

    _assert_error(
        ModelRegistryErrorCode.INVALID_ARTIFACT,
        lambda: registry.register(extended),
    )
    assert registry.snapshot() == ()


def test_lookup_and_transition_require_exact_uuid_and_enum(tmp_path: Path) -> None:
    path = _write_model(tmp_path / "model.gguf")
    artifact = _artifact(path)
    registry = ModelRegistry()
    registry.register(artifact)

    _assert_error(
        ModelRegistryErrorCode.INVALID_ARTIFACT_ID,
        lambda: registry.get(str(artifact.artifact_id)),
    )
    _assert_error(
        ModelRegistryErrorCode.INVALID_LIFECYCLE,
        lambda: registry.transition(artifact.artifact_id, "quarantined"),
    )
    _assert_error(
        ModelRegistryErrorCode.ARTIFACT_NOT_FOUND,
        lambda: registry.get(uuid4()),
    )


def test_concurrent_duplicate_registration_is_atomic(tmp_path: Path) -> None:
    path = _write_model(tmp_path / "model.gguf")
    artifact = _artifact(path)
    registry = ModelRegistry()
    barrier = threading.Barrier(8)

    def register_once() -> ModelArtifact | ModelRegistryErrorCode:
        barrier.wait(timeout=5)
        try:
            return registry.register(artifact)
        except ModelRegistryError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: register_once(), range(8)))

    assert results.count(artifact) == 1
    assert results.count(ModelRegistryErrorCode.DUPLICATE_ARTIFACT_ID) == 7
    assert registry.snapshot() == (artifact,)


def test_concurrent_duplicate_hash_registration_is_atomic(tmp_path: Path) -> None:
    artifacts = [_artifact(_write_model(tmp_path / f"model-{index}.gguf")) for index in range(8)]
    registry = ModelRegistry()
    barrier = threading.Barrier(len(artifacts))

    def register_once(
        artifact: ModelArtifact,
    ) -> ModelArtifact | ModelRegistryErrorCode:
        barrier.wait(timeout=5)
        try:
            return registry.register(artifact)
        except ModelRegistryError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=len(artifacts)) as executor:
        results = list(executor.map(register_once, artifacts))

    assert sum(isinstance(result, ModelArtifact) for result in results) == 1
    assert results.count(ModelRegistryErrorCode.DUPLICATE_ARTIFACT_HASH) == 7
    assert len(registry.snapshot()) == 1


def test_concurrent_transition_retains_one_consistent_history(tmp_path: Path) -> None:
    registry, artifact_id = _registry_at_state(tmp_path, ModelLifecycle.IMPORTED)
    barrier = threading.Barrier(8)

    def transition_once() -> ModelArtifact | ModelRegistryErrorCode:
        barrier.wait(timeout=5)
        try:
            return registry.transition(artifact_id, ModelLifecycle.QUARANTINED)
        except ModelRegistryError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: transition_once(), range(8)))

    assert sum(isinstance(result, ModelArtifact) for result in results) == 1
    assert results.count(ModelRegistryErrorCode.INVALID_LIFECYCLE_TRANSITION) == 7
    assert [record.lifecycle for record in registry.history(artifact_id)] == [
        ModelLifecycle.IMPORTED,
        ModelLifecycle.QUARANTINED,
    ]
