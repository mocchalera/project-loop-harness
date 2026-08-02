# 0220: P1-C C2 proof workspace

- **Status:** Implemented locally; C3/C4 not authorized by this task
- **Milestone:** P1-C C2 Git isolation and typed input binding
- **Priority:** P1
- **Dependency:** C1 fixed-hash GO at
  `2d932c53cb3014277e862f5716a975d831e87e6f`
- **Schema/dependencies:** schema 8; migration 0; runtime dependency 0
- **PCL state effect:** 0; no event, Evidence, outbox, render, or lifecycle
  mutation

## Authorized C2 contract

Implement the internal `proof_workspace` service,
`verification-profile/v1`, `proof-workspace-spec/v1`,
`proof-workspace-binding/v1`, and frozen `PreparedCheck` only.

The service binds the complete C1 authority result and bootstrap profile,
recomputes the exact candidate/tree/diff in a sealed `--no-local --no-checkout`
clone, materializes only declared typed inputs, constructs complete child
environments from zero, and safely cleans only an exact successful POSIX temp
lease. Every failure/crash root is retained and never swept or adopted.

`reuse_authorized` remains false. A C1 reuse verdict other than literal true,
base unknown/no-change, opaque or unavailable allowed input, secret-shaped
environment, or unsupported compatible material can only lower the separate
disposition to fresh-only. Integrity mismatches block.

## Exclusions

No public `pcl proof` CLI, check result, proof artifact, Evidence, event, outbox,
database change, render, terminal transition, C3 anchor/reuse, C4 join, or C5
rollout. Do not change `guarded_process.py` or the meaning of
`verification-input-manifest/v1`.

## Handoff

C3 must consume the exact immutable `PreparedCheck` as its sole spawn vector.
It may not call `build_subprocess_env`, merge `os.environ`, prepend host `src`,
or reconstruct argv, cwd, environment, timeout, or output bounds. C3 also owns
all execution/result/artifact/event behavior and must independently rederive
C1 and every bound digest before spawn.

C4 owns mandated canary and role coverage. A structurally valid C2 profile is
not semantic proof that all frozen canary roles were run.

See [proof-workspace-v1.md](../docs/proof-workspace-v1.md).

## Verification boundary

Use source-tree execution and no caches:

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/test_proof_workspace.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/test_authority_surface.py tests/test_verification_manifest.py tests/test_finish_workspace.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m ruff check --no-cache .
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m pytest -q -p no:cacheprovider
```

The focused matrix covers linked worktrees, hostile Git/environment state,
exact tree modes/symlinks/gitlinks, submodule/LFS/generated/file/directory/
opaque inputs, reachability/ref races, TOCTOU, lease cleanup/refusal/crash
retention, host-import sentinel, secret/public binding separation, proof-key
stability, no C3/PCL effects, and concurrency.
