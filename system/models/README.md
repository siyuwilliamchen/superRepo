# Exact-model profiles

Model instructions are separate from tool adapters and agent roles. Register a
profile in [registry.json](registry.json) only after the provider and exact model
ID are known. Each entry has `key`, `provider`, `model_id`, `profile`, and optional
`memory` (repository-relative file paths).

Use filesystem-safe keys, for example `provider-exact-version`, while retaining
the provider's original ID in `model_id`. A model family or a moving alias is not
a tested version. Record alias resolution and test date when available.

A profile may contain task-specific context limits, supported tool behavior, or
format constraints verified in this environment, with evidence and date. Do not
invent model rankings, current prices, access, or strengths. None are set by this
scaffold. The empty registry deliberately falls back to shared instructions.

Operational observations belong in `memory/models/<key>/`, not in shared research
facts. A model upgrade requires rechecking model-specific observations. Roles
and permission boundaries do not change with model selection.
