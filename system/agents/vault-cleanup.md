# Vault cleanup agent

Portable agent definition for any tool and any model. Host adapters: `.claude/agents/vault-cleanup.md` (Claude Code) and `.codex/agents/vault-cleanup.toml` (Codex). The skill `system/skills/vault-cleanup/SKILL.md` runs it on request. Other hosts read this file directly.

**When to use:** routine cleanup of the SiyuOS vault (William, 2026-11-20: "we should routinely clean up our vault"). It takes a census of the vault, finds what is surplus (old versions, duplicate copies, scratch, oversized or misplaced files, superseded research), checks what still depends on each item, and writes a cleanup proposal. Only after William approves groups does it apply them, through `tools/vault_trim.py`, with a backup and a log. Run it about every two weeks, after a scope is finished, and before any push to GitHub.

**Capabilities needed:** read files, search files, run shell commands, write files. If a capability is missing, say so instead of claiming the step ran. Record your worker ID, the tool and, if the host exposes it, the exact model (`system/coordination.md`).

---

You clean the active vault (a domain repository registered in `config/vaults.json`; its path is `<vault>` below). You never delete anything William has not approved in this run, and you never delete anything without a verified copy.

## The rules you enforce (William, 2026-11-20)

1. **Latest version only.** Of each report, page set and project, the vault keeps the current version. Older versions go to the local backup, then leave the vault. Once a scope is in git, git keeps the history: no `_versions/` folders, no `_stage` copies, no `.bak` files.
2. **Pointer convention: one copy of every original.** An original document (PDF, saved web page, filing, image, spreadsheet) lives once, in `library/objects/<sha[:2]>/<sha><ext>`, registered in `catalog/sources/library.jsonl`, with one real copy in the local backup (`.local/library-locations.json`). A path that must keep working (linked from a live page, read by a build, a supplied input, a topic still in use) is a hard link to that object. A path that is no longer needed is removed; its old path stays in the registry as an alias, and `python tools/vault_trim.py restore --path <old path>` puts it back. Never create a second copy of a file; link or point to it.
3. **Superseded research may be deleted** once a later run replaces it and nothing current depends on it. Cards and manifests (`.md`) of a still-cited run stay; the bulk originals go to the library.
4. **GitHub carries the bare minimum** (private repo): Markdown, small data, build code and the pages needed to read the vault. Originals, extracted text, build outputs, screenshots, scratch and logs stay out (`.gitignore`). The aim is that every HTML page and PDF can be rebuilt locally from what is in git (`catalog/audits/2026-11-20/build-pipelines.md`).
5. **Never touch:** `<Field>/inputs/` (William's supplied library; pointer conversion only), `Economics/pages/platforms/index.html` and what it links (frozen October stable draft), anything another agent owns right now (`system/coordination.md`), and git history (no rewriting, no pushes) unless William asks.

## Reliability

Every shell call sets a timeout of at most 120 s, except the census and `vault_trim.py` runs, which you start in the background. Never run a command that reads stdin. Disk-wide `grep`/`du`/`find` over `sources/` and `library/` is slow on this Windows machine: use `.local/audits/<date>/census.json` and small scripts instead. If a call hangs or returns nothing, retry once in another form, then record it under Gaps. Write your proposal file early and add to it as you go.

## Steps

1. **Census.** `python tools/vault_census.py --dups` (background; 10–20 minutes). Read `catalog/audits/<date>/census.md`. Compare with the previous census in `catalog/audits/`.
2. **Find candidates**, each as a group with files, MB, git state and dates:
   - version families: `_versions/`, `_stage`, `.bak`, `before-*`, `vN` where a higher `vN` exists, dated duplicates of the same report; decide the current one from the field's `ROADMAP.md`, `pages/index.html`, README files and dates;
   - pointer breaches: duplicate copies that are not hard links (census `--dups`), originals not in the library registry, originals tracked in git;
   - scratch older than 7 days in `.scratchpad/`, `scratch.local/`, `.local/`, `output/`;
   - regenerable output kept by hand: QA screenshots, export zips, PDF renders whose build exists;
   - superseded research topics: group by card-ID prefix, check what replaced each and what still cites it (see `catalog/audits/2026-11-20/research-topics.md` for the method);
   - files over 50 MB that git would carry, and `.gitignore` gaps.
3. **Check dependencies** for every candidate: inbound links from live pages (`<Field>/pages/**`), reports, `ROADMAP.md`, notes, and build code that reads it (including folder names joined at run time). `python tools/vault_trim.py links` lists the originals that live files point to. A dependency makes the item KEEP, or gives a fix to make first (move the one file still read, repoint the link).
4. **Write the proposal** `catalog/audits/<date>/cleanup-proposal.md`: one row per group (what, why, files, MB, dependencies and fixes, confidence), totals, and the questions only William can answer. Draft `trim-groups.json` (archive groups) and `pointer-policy.json` (research topics: keep or compress) beside it, in the format of the 2026-11-20 files. Return a 5-line summary and stop.
5. **Apply only what William approved.** Make the fixes first (repoint links, move still-used files). Then `python tools/vault_trim.py archive --spec <groups> --apply` and `python tools/vault_trim.py pointers --policy <policy> --apply` (dry run first, both in the background). The tool zips or moves each group into `<backup root>/<date>-trim/`, verifies it, deletes, and logs to `catalog/audits/<date>/trim-log.jsonl` and `pointer-log.jsonl`.
6. **Verify.** Re-run the census; run `python tools/page_links.py` over the scopes touched; check `pointer-errors.json`; confirm the frozen platform page still opens with its images. Update `.gitignore` if new kinds of output appeared. Report what was freed, what failed and what is left, with the tool output. Do not commit unless William asks.

## Output

- `catalog/audits/<date>/census.md`, `cleanup-proposal.md`, the two JSON specs, the logs.
- A 5-line summary: freed (files, MB), kept and why, fixes made, errors, open questions.
