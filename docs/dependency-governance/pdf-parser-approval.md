# PDF parser dependency approval

Status: **approved** (Tier-0 only)

This record separates the product design decision from authority to change the accepted Python
dependency set. The governance capture is bound to manifest
`62c8ab9a66d13189b5788d2f57269685c49e38c932dafca68a232cc6e9305472` and to the unchanged
workspace `pyproject.toml` and `uv.lock` hashes recorded there.

## Decision

Approved on 2026-07-19 by actor `andrzej:continue-development-instruction` under the user's
instruction to continue Phase 2B development without stopping. Approval authorizes only the
narrow Tier-0 set below for the isolated document-worker package on CPython 3.12, macOS arm64.

Approved:

- `pypdf==6.14.2`, base package only, no extras: one reviewed BSD-3-Clause universal wheel.
- `pdfminer-six==20260107`, base package only, no `image` extra: five reviewed wheels comprising
  `pdfminer-six==20260107`, `charset-normalizer==3.4.9`, `cryptography==49.0.0`, `cffi==2.1.0`, and
  `pycparser==3.0`.

Not approved: `docling==2.113.0`. It remains benchmark-only and blocked. Its standard graph has
123 external components, includes source-only `antlr4-python3-runtime==4.9.3`, and has ungoverned
model downloads, remote-code configuration, native-load and deserialization surfaces, and
incomplete model/license evidence.

There are no accepted advisory, license, source-build, remote-code, or model-artifact exceptions.
Approval authorizes only the later lockfile change for the document-worker package. It does
not authorize Docling, OCR/VLM models, runtime downloads, candidate promotion, network egress,
push, or a production release. Rollback is removal of the two direct requirements and
deterministic regeneration of the accepted lock.

The JSON below is authoritative; prose is explanatory.

<!-- RSI_ATLAS_PDF_PARSER_APPROVAL_BEGIN -->
```json
{
  "accepted_exceptions": [],
  "actor_id": "andrzej:continue-development-instruction",
  "approval_sha256": "a3ec8086fe3287fafe0eb23f9e648dc01f7af66bb6ca43be1abe6ac1701b35f4",
  "authority": {
    "allows_commit_or_push": false,
    "allows_dependency_lock_change": true,
    "allows_model_artifacts": false,
    "allows_production_promotion": false,
    "allows_runtime_network": false,
    "package_scope": "document-worker-only"
  },
  "blocked_candidates": [
    {
      "id": "docling-standard-benchmark",
      "reason": "blocked_dependency_governance",
      "requirement": "docling==2.113.0"
    }
  ],
  "decided_at": "2026-07-19T08:18:00Z",
  "decision": "approved",
  "manifest_sha256": "96f9f4278320f0ac09d08335fb53e3561831e198f413d40ee5c116bbe91f9b45",
  "model_artifacts": [],
  "proposed_candidates": [
    {
      "artifact_sha256": [
        "3f07891af76dc002657e04993ab9b4de81de29f9013b9761d0b7968bff12e946"
      ],
      "components": [
        "pkg:pypi/pypdf@6.14.2"
      ],
      "extras": [],
      "id": "pypdf-base",
      "requirement": "pypdf==6.14.2"
    },
    {
      "artifact_sha256": [
        "366585ba97e80dffa8f00cebe303d2f381884d8637af4ce422f1df3ef38111a9",
        "45b0cc4e3556cd875e09102988d1ab8356c998b596c9fced84547c8138b487a0",
        "78474632761faa0fb96f30b1c928c84ebcf68713cbb80d15bab09dfe61640fde",
        "966fe0e9c67490071f14c0d2b1cb2dfb3023c5ce39457343931415f08382f2db",
        "b727414169a36b7d524c1c3e31839a521725078d7b2ff038656844266160a992"
      ],
      "components": [
        "pkg:pypi/cffi@2.1.0",
        "pkg:pypi/charset-normalizer@3.4.9",
        "pkg:pypi/cryptography@49.0.0",
        "pkg:pypi/pdfminer-six@20260107",
        "pkg:pypi/pycparser@3.0"
      ],
      "extras": [],
      "id": "pdfminer-six-base",
      "requirement": "pdfminer-six==20260107"
    }
  ],
  "rollback": {
    "action": "remove both direct parser requirements and regenerate uv.lock from the accepted baseline",
    "baseline_uv_lock_sha256": "d0aa24974d293ac09edb19ef1296154d1ce2beec4464014833db13c26f1f495c"
  },
  "schema_version": "rsi-atlas.pdf-parser-approval.v1",
  "target_environment": {
    "implementation": "CPython",
    "machine": "arm64",
    "platform": "macOS",
    "python_version": "3.12.13"
  }
}
```
<!-- RSI_ATLAS_PDF_PARSER_APPROVAL_END -->
