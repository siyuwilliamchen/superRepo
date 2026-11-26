# Development prompt · LiveOS vault ledger and Housekeeper

Read this alongside `LiveOS_Research_Conversation_Spec.md`. This is a handoff for the future development session. In a design-review session, return the proposed changes only. Once William authorizes development, use the repository’s normal development entry points and carry the pilot through its acceptance tests. Production cleanup is a separate operation.

## Outcome

William should be able to say, “Remove the superseded research drafts on this topic and keep the evidence behind my published reports.” The Housekeeper should query a domain ledger, identify exact candidates, explain exceptions, and apply the authorized changes with a recovery record. A different agent should be able to ask, “Where is our evidence about investor consent thresholds?” and find the relevant files even if they live in several folders. William interacts with the Conversationalist; maintaining the ledger is a consequence of doing work.

Preserve four distinct responsibilities. The **roster** describes who can do work. The **ticket ledger** records what was requested and what happened. The **artifact ledger** records what durable material exists, why, where, and which retained work requires it. The **topic directory** is the short Markdown entry point agents navigate. Connect these by stable IDs. Move a file without changing its identity; replace a file with an unrelated artifact and give the replacement a new identity.

## 1. Survey before choosing a representation

Inspect the current shell-job ledger, Coordinator if present, canonical agent definitions and thin adapters, role write scopes, existing field/topic indexes, Markdown linking convention and plugin configuration, report manifests, backup/restore and `vault_trim.py`, protected paths, and one representative domain. Identify actual entry points that write into the vault, including human edits, agent tools, maintenance jobs, and renderers. Map what can bypass a broker and how those writes become visible. Document briefly where existing guarantees suffice and where they end.

Choose one real domain for read-only baseline checks and one isolated fixture/worktree for mutation tests. Include a second domain in the fixture to exercise cross-domain references. Reuse existing IDs, paths, ledgers, and SQLite indexes if suitable. A new engine, service, paid model, full-vault rewrite, and working voice integration are unnecessary dependencies for this pilot.

## 2. One logical ledger, hierarchical views

Use one registration contract and one authoritative representation of each managed artifact. Expose domain ledgers, bounded topic directories, and a root directory pointing to domains. A domain can own an artifact stored elsewhere. Additional topic memberships are references. Preserve a folder-local guide where useful. Generate managed navigation lists from the catalog and preserve any separately authored explanatory text. Update affected entries on change; keep an explicit rebuild command for recovery. Avoid copying every child entry into every ancestor or making all workers append to a common Markdown file.

Default if no existing representation fits: use small machine-readable records partitioned by domain and keyed by artifact ID in Git. Use Git commits for revision history and the existing operation ledger for receipts. Build a local, disposable lookup index for artifact ID, path, topic, ticket, status, and incoming dependency. The index records the repository revision it covers. An incremental update should be sufficient on a normal write. Validate that the index can be rebuilt without guessing metadata from prose. A pilot may use another representation if the implementer demonstrates the same guarantees with less machinery.

Each record should carry enough information to make a decision:

| Recorded by the worker or owning subsystem | Recorded or checked by the integrating code |
|---|---|
| Short purpose, domain and stable topic IDs, artifact kind, owning role, originating ticket, direct required inputs or a reference to the canonical manifest | Artifact ID, current path or external object locator, content version or digest, operation and run identity, creation and last-change provenance, current lifecycle state, applicable retention policy, and dependency-coverage status |

Typical kinds include original evidence, findings, interpretation, approved report source, dataset, and disposable derivative. Use a short controlled vocabulary and allow an unknown value during migration. Keep only metadata that agents can query or the Housekeeper can act on. A purpose sentence should distinguish “compares thresholds in two executed amendments” from “research notes.” No agent can unilaterally lift a repository protection by writing a favorable retention label.

### Dependencies required for the first release

For a new retained report, evidence package, or dataset-derived figure, capture the **direct inputs needed to reproduce it or substantiate it**. Reuse references already declared in the agreed brief, source manifest, graph script, or renderer. Pin a version where a historical edition depends on specific bytes. For an active job, register a temporary hold on required inputs and release it on completion or cancellation. Preserve retained external objects by locator and integrity hash, with a means to access the bytes.

Derive the reverse lookup from those same records. The question “Who requires this input?” must work across domains and through intermediate artifacts. Record whether the relevant consumers and dependency types have been reconciled. A file can have perfect metadata about its own inputs while a legacy report that consumes it remains unregistered.

Use the vault’s verified Markdown link syntax for ordinary navigation. A related page, a hyperlink, and a required build input have different consequences for deletion. Put optional related-topic links in the directory where already known. Defer automatic semantic link discovery, universal backlinks, graph visualization, and plugin-specific automation. Preserve the Interpreter’s existing claim relationships separately from file-retention dependencies.

## 3. Make registration part of the write

Implement one mutation interface around the existing integration point. It supports create, modify, move/rename, retire/delete, and restore. A worker stages a change with its ticket, role/run identity, operation key, target, expected artifact version, purpose or metadata delta, and changed dependencies. One ticket can cover a coherent batch. Temporary worktree files, caches, generated previews, and the catalog’s own bookkeeping do not recursively require tickets.

- Validate the role’s write scope and the repository’s existing protections. Compare actual staged changes with declared operations. Reject mismatches on managed paths at integration or mark them as drift if they arrived through an external/manual edit. Do this in code; update canonical agent instructions to call the interface.
- For Git-managed material, integrate file bytes, catalog changes including removed dependencies, and the receipt reference as one accepted change against the expected revision. Preserve retry keys. Never allow a stale writer to resurrect retired content or overwrite a new artifact reusing an old path. A cross-domain move keeps the ID and updates both domain views from the same accepted operation.
- Treat Git plus an external store as two systems. Stage and verify reversible external changes, persist intent and progress, and finalize or recover idempotently. Keep a deleted record as a compact tombstone with its reason and restore reference. Verify the intended object before completing a pending removal.
- Inspect the actual vault’s hard-link behavior. For an edit intended to affect one path, use a verified isolated copy or an atomic replacement appropriate to the host. An in-place write through a hard link can change its aliases and even invalidate a purported backup. Test that a backup is independently recoverable. Leave existing hard-link groups undisturbed outside the requested mutation.
- Refresh derived indexes and Markdown views after successful integration. If a refresh fails, mark the view stale and replay it. A stale view can aid browsing; deletion decisions must validate against current authoritative state.

## 4. Migrate coverage honestly

Begin with a cheap inventory using Git paths and filesystem metadata. Cover untracked and external material where relevant. Record which domains, manifests, and consumer classes have been inventoried at which revision. Import reliable metadata and dependency declarations mechanically. Seed the pilot’s protected roots and report inputs before enabling deletion.

Existing files may start as **inventoried, purpose unknown, dependencies unverified**. Enrich them when touched, when needed for retrieval, or when included in a cleanup request. Periodically reconcile changed paths and known consumers, including changes made outside the agent workflow. Use targeted source reads when a classification matters. Report gaps that genuinely require a wider one-time inspection. Routine Housekeeper operation should never depend on a model reading every document.

## 5. Housekeeper workflow

1. Translate a request into explicit domain/topic, kinds, states, and exclusions. For example, distinguish “remove the superseded drafts from this project” from “erase every mention of this subject.” The second request may require a scoped content search and a different retention decision.
2. Resolve candidates through indexed metadata. Group the result into eligible artifacts, items retained by named dependencies or policy, and unresolved cases. Show the minimum information William needs to decide. An unknown incoming dependency is meaningful even if the visible backlink count is zero.
3. Check direct and transitive consumers, approved editions, live job holds, shared assets, and the vault’s protected list. Preserve the existing rules for `inputs/`, the frozen October platform page, other agents’ owned material, and Git history. A retained external source may outlive its local convenience copy. Determine which one the consumer actually requires. If coverage is inadequate, investigate the specific consumer or quarantine only where doing so preserves live access. Otherwise leave it in place and give a concrete reason.
4. Bind any approval to exact IDs, expected versions, scope, and an operation receipt. Use existing group approval/backup policy. Revalidate at application time, including new consumers since the plan. Serialize finalization with concurrent registrations or perform a guarded revision check. Preserve unrelated changes. A changed case gets a fresh disposition.
5. Apply through the existing verified cleanup mechanism where it meets the contract. Record what moved, was retired, was removed, or remained held. Test a restore, including dependencies and ID/path conflicts. Distinguish removed paths, logical bytes, and measured physical savings. No history rewriting, remote purge, or vault-wide production deletion is part of the pilot.

## 6. Update every writing agent at the canonical layer

Extend the shared contract once. Any role that creates or modifies durable managed material must use the ticketed write path. Research workers declare sources and purpose. The Interpreter declares evidence inputs. The Conversationalist and Coordinator register durable session segments, briefs, or checkpoint batches within their existing scopes. The Writer declares report/build inputs. The revision editor submits changed files and dependencies under one revision ticket. Reviewers remain read-only for article content; if they persist a review record, that record uses their own allowed scope. The structural evaluator can compare actual changed paths with receipts. The Housekeeper owns authorized retirement and restore. Keep Claude/Codex adapters thin and expose the same protocol to future hosts. List every discovered writer and any still-unmanaged path in the implementation handoff.

## 7. Demonstrate the guarantees

| Exercise in the pilot | Evidence required |
|---|---|
| Create two files on one ticket, retry after a lost acknowledgment, modify one and rename it across domains | One effective change per operation, stable identity, correct content and current domain/topic results. |
| A published report in domain B requires a figure built from a CSV owned by domain A. An unrelated page merely links to a draft. | Housekeeper gives the actual dependency chain for the CSV; the navigation link to the draft receives a separate disposition. |
| A legacy consumer lacks a manifest; a human edits a registered file outside the normal path | Gaps or drift are visible. No unverified deletion is approved from an empty index. Scope and cost of reconciliation are reported. |
| A job pins an input after cleanup was proposed. Another worker replaces a file at a reused path. | Apply-time checks preserve both the active input and the replacement. Replaying an old receipt cannot affect either. |
| Interrupt between staging and acceptance; interrupt before refreshing views; restore a retired artifact | Recovery converges to one correct state. Current paths, content digests, reverse dependencies, and receipt history agree. |
| Two paths share a hard link; edit one and retire it. Rebuild an approved report from retained sources. | The sibling and recovery copy retain their intended bytes. The report’s data and figures regenerate. Physical savings are reported only if measured. |
| Ask for an item by subject across folders, then request cleanup of that subject’s expired previews | Capture index queries, number of file bodies opened, bytes read and model calls. Distinguish one-time bootstrap cost from steady-state work. A fully registered case uses metadata and targeted verification; repeated whole-vault content scans fail this gate. |

Return the actual files and agent contracts changed, one example operation and receipt, one Housekeeper result with a cross-domain hold, test results, and remaining coverage gaps. Expand beyond the pilot once the normal write route, recovery, and retention behavior are demonstrated.
