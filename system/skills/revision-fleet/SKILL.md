---
name: revision-fleet
description: Run the SiyuOS revision fleet on one Level 2 article (a page, a scope's pages, or a collected report) - three reviewers each read for one purpose (technical boundaries, blind reader comprehension of the boxed core path within 10 minutes per unit and 60 per article, plain language/format/back links), then one editor applies their advice. Use when William asks to review, revise, check or "run the fleet" over a page, scope or report, or after a page set is finished and before he reads it. Do not use for writing a new page (report-writer) or for research (research-agent).
---

# Revision fleet

Canonical, tool-agnostic dispatch. Host adapters: `.claude/skills/revision-fleet/SKILL.md` (Claude Code) and `.agents/skills/revision-fleet/SKILL.md` (Codex). The method, the files and the conflict rules are in `system/methods/revision-fleet.md`; read it first. The four workers are defined in `system/agents/rev-technical.md`, `rev-reader.md`, `rev-plain-format.md` and `rev-editor.md`.

## How to start a worker on your host

- **Claude Code:** the Agent tool with `subagent_type` set to the worker's name (`rev-technical` …).
- **Codex:** spawn the custom agent by name (`.codex/agents/<name>.toml`). If the host cannot invoke it by name, spawn a generic worker whose first instruction is "Read `system/agents/<name>.md` and follow it", followed by the brief.
- **Any other host, or no delegation:** run each worker in a fresh session with that instruction and the brief.
- **The blind reader must start with an empty context.** Never run stage 1 inside the session that wrote the brief or read the pages; that session is not blind.

## Steps

1. **Pick the article and the run folder.** `<Field>/reviews/<scope>/<YYYY-MM-DD>/`. Run `git status --short <scope folder>` and check that no other worker is editing the article's files. If one is, wait or choose another article.
2. **Write `brief.md`** (contents in the method): pages in reading order, units as `page#id` with names, the question and roadmap row, the evidence paths, the content source files and build command, the scope's checkers, and what William said about this article (quoted).
3. **Make the blind text** from the English twins, parts in reading order (overview first, then each unit):
   ```
   python tools/page_budget.py <part ...> --out <run>/reader-core.txt
   ```
   Note the core and full minutes the tool prints; they go in the brief as the "before" figures.
4. **Wave 1, three workers in parallel:**
   - `rev-technical`: brief path and run folder.
   - `rev-reader`: "Stage 1 (blind)". Give only the `reader-core.txt` path, the unit names and the output path. Do not give the brief, the pages or any other report.
   - `rev-plain-format`: brief path and run folder.
5. **Save refused writes.** When a final message starts with `FULL TEXT: save to <path>`, save the text unchanged at that path.
6. **Wave 2:** `rev-reader`, "Stage 2 (compare)". Give the paths of `reader-blind.md`, `technical.md`, the pages and the output path.
7. **Wave 3:** `rev-editor`, with the brief path and run folder.
8. **Retest (recommended):** remake `reader-core.txt` from the revised pages, then run a fresh `rev-reader`, stage 1 and stage 2. Compare the capture rates before and after.
9. **Report to William** in at most 12 lines:
   - what changed;
   - the capture rates before and after;
   - the core minutes per unit, before and after;
   - the link problems fixed;
   - the research requests;
   - his questions, if any.
   Link `editor.md`. Do not paste the reviews.

## Limits

- At most 5 workers at once across all runs.
- No two runs touch the same files.
- Reviewers never edit; only the editor does.
- Nothing is committed.
- The fleet's files are Level 1 records and never appear on a page.
