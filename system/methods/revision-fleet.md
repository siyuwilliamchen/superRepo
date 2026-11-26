# Revision fleet: read every article for one purpose each, then one editor applies

Set by William on 2026-11-12. Every Level 2 article (a page set or a collected report) can be
read by three reviewers, each with one purpose. A fourth agent, the editor, takes their advice
and makes the changes. Reviewers advise; only the editor edits. The LifeOS method, the Learning
Architecture and Standing Preferences still govern what a page must be. This file sets how the
fleet runs, where its files go, and how conflicts are settled.

| Agent | Reads for | Result |
|---|---|---|
| `rev-technical` | The real, enforceable boundaries in money, power, responsibility, legal authority and information, followed from the sources | `technical.md`: the ranked structural list and advice on the deduction from source to structure |
| `rev-reader` | What a reader with no background takes away from the boxed core path, read in at most 10 minutes per unit and 60 minutes for the article | Stage 1 `reader-blind.md`: synopsis and summary, read blind. Stage 2 `reader-compare.md`: capture against the structural list, LiveOS check, clarity advice |
| `rev-plain-format` | Plain language to the standard below, tables and figures, back links | `plain-format.md`: findings with exact fixes, link report |
| `rev-editor` | All three reports | Edited content and rebuilt pages, `editor.md` decision log, research requests |

Agent definitions (any tool, any model): `system/agents/rev-*.md`. Dispatch steps:
`system/skills/revision-fleet/SKILL.md`. Host adapters point back to them: `.claude/agents/`,
`.claude/skills/` (Claude Code); `.codex/agents/`, `.agents/skills/` (Codex).

## Terms

- **Article:** what William reads as one piece: one page, a scope's pages, or a collected report.
- **Unit:** one self-contained unit of information inside the article, for example one trading
  platform, one place of formation, or one document. A unit is a page or one element of a page
  (`page.html#element-id`). The brief lists the units.
- **Structural item:** one boundary the article must make clear, for example "who can sell your
  holdings without asking, when, and what stops them". The technical reviewer numbers them S1, S2…
- **Core box:** the important structural content, boxed and bold, in an element with class `core`
  and `data-s="S3"` (the structural items it carries). Style: a visible border, bold text. Read in
  order, the core boxes are the **core path**.

## The reading budget (William, 2026-11-12)

- The core path fits the budget: **at most 10 minutes per unit and 60 minutes for the whole
  article** (at 200 words a minute plus 15 seconds a figure, measured on the English twin).
- **Do not cut the page until it fits.** The full page keeps its detail. Meet the budget by
  choosing what goes in the core boxes: the top structural items, each stated to its real boundary,
  in figures and tables where possible. Everything else stays on the page, outside the boxes, or
  moves to a back-link page.
- Repetition, narration and off-question material are still cut, because they are waste, not to
  meet a number.

## Files

All fleet files for one run go in `<Field>/reviews/<scope>/<YYYY-MM-DD>/` (add `-2`, `-3` for a
second run that day). They are Level 1 working records for the AI. They never appear on a page.

| File | Written by |
|---|---|
| `brief.md` | the coordinator, before dispatch |
| `reader-core.txt` | the coordinator, with `tools/page_budget.py` |
| `technical.md` | `rev-technical` |
| `reader-blind.md`, `reader-compare.md` | `rev-reader` |
| `plain-format.md`, `links.json` | `rev-plain-format` |
| `editor.md` | `rev-editor` |

Subagent writes are often refused by the harness. A refused agent returns its whole file as text
under a first line `FULL TEXT: save to <path>`. The coordinator saves it unchanged at that path.

## The brief (`brief.md`)

1. The article: its scope folder, its pages (Chinese and English twin), the reading order, and the
   units, each with a short name and its `page#id`.
2. The question the article answers and its row in `<Field>/pages/ROADMAP.md`.
3. The evidence: the scope's `prompts/` brief, the research cards and the `sources/` folders the
   pages draw on.
4. The build: the content source files (pages are generated; never hand-edit generated HTML), the
   build command and its order, and the scope's own checkers.
5. Write ownership: the editor owns the content files, the rebuilt pages and the scope's roadmap
   row for this run. The reviewers own only their review files.
6. Anything William said about this article that the reviewers must know (quote it).

## Order

1. **Prepare.** Write the brief. Make the blind reading text from the English twin, with the parts
   in reading order (an overview page first if the article has one, then each unit):
   `python tools/page_budget.py <part …> --out <run>/reader-core.txt`
   It holds each part's core path, cut at 10 minutes, and stops at 60 minutes in total. A part with
   no core boxes yet contributes its first 10 minutes of full text, marked as such.
2. **Wave 1, in parallel:** `rev-technical`, `rev-reader` stage 1 (blind), `rev-plain-format`.
   The blind reader gets only `reader-core.txt` and the unit names, not the brief, the pages, the
   vault or any other report.
3. **Wave 2:** `rev-reader` stage 2 (compare). It receives `reader-blind.md`, `technical.md`, the
   pages and the LifeOS method.
4. **Wave 3:** `rev-editor`, with the brief and all four reports.
5. **Retest (recommended):** remake the reading texts from the revised pages and run stage 1 and
   stage 2 again with a fresh reader. The run is finished when the top structural items are
   captured, or the editor's log says why one cannot be.

At most 20 agents run at once (standing preference, 2026-11-05, raised to 20 on 2026-11-14). Several articles may be in the
pipeline together if the total stays at 5 and no two runs share files.

## How the editor settles conflicts

Higher rows win. Advice that breaks a binding rule is rejected and logged with the rule.

1. **Accuracy and evidence.** A wrong or unsupported claim is fixed or removed. A missing fact is
   never invented: it becomes a research request.
2. **The real boundary.** The top structural items (by the technical reviewer's ranking) must be
   on the page, followed to the enforceable line.
3. **What the reader can take away.** Box and bold the top structural items so the core path
   carries each unit's principal story within its 10 minutes (60 for the article). Reorder so the
   core comes first in each unit. Cut repetition and narration because they are waste; never cut
   detail to meet the budget.
4. **Plain language and format.**

When "shorter" meets "complete": the core path gets shorter by choosing better; the page keeps
every layer, condition and technical detail, outside the boxes or on a back-link page. A
revision grows the main page by no more than about 15% (standing preference, 2026-11-05); back-
link pages may grow.

## The plain-language standard (adopted by William, 2026-11-12)

William asked for a standard that keeps the virtues of ASD-STE100 Simplified Technical English
(written for aircraft maintenance procedures, with a closed dictionary that cannot carry legal and
financial ideas) but fits technical legal and money subjects. Three published standards, layered:

1. **ISO 24495-1:2023, Plain language, Part 1: Governing principles and guidelines** (first
   edition, June 2023). Four principles that test the whole page: the reader gets what they need
   (relevant), can find it (findable), can understand it (understandable), and can use it
   (usable). Most of its guidance is about structure and findability rather than word choice
   (secondary sources put the word-choice share at about 7%; the paid full text was not read).
2. **SEC, *A Plain English Handbook: How to create clear SEC disclosure documents*** (Office of
   Investor Education and Assistance, August 1998; free at sec.gov/pdf/handbook.pdf). Written for
   prospectuses and other disclosure documents, so it covers the legal and financial writing these
   pages deal with. It accompanied the SEC's 1998 plain-English rule, under which Rule 421(d)
   requires plain English in a prospectus's cover page, summary and risk factors. Techniques:
   active voice, short sentences, everyday words, concrete verbs instead of noun phrases, no legal
   jargon, no stacked negatives, tables and graphics for complex material, address the reader as
   "you".
3. **Federal Plain Language Guidelines** (PLAIN, March 2011, revision 1 May 2011; the official
   guidelines for the Plain Writing Act of 2010; removed from plainlanguage.gov in 2025 and reposted
   by the Center for Plain Language). The detailed checklist: write for the reader, organise around
   the reader's questions, headings, short sections, "must" instead of "shall", define each term,
   give examples, use tables for complex material.

Kept from STE and William's rule of 2026-10-30: one fixed plain word for each thing, the word list
(plain word → official name → meaning), one idea per sentence, at most 20 words a sentence, the
official name only in brackets after the plain words, and no technical detail dropped. Where
William has set a second-grade level for a product (the company-story decks), that level stands.

The Chinese pages follow the same rules: short sentences, one fixed word for each thing, each term
explained where it first appears. No Chinese national plain-language standard was found in a
search on 2026-11-12.

## Tools

- `tools/page_budget.py`: per part, the core-path minutes against 10 (and 60 in total), the
  structural items boxed (`data-s`), full-page minutes, share of words in figures and tables,
  sentences over 20 words, and the blind reading text (200 words a minute plus 15 seconds a figure;
  Brysbaert 2019 puts English non-fiction at about 238).
- `tools/page_links.py`: broken links and anchors, missing or one-way twins, one term linked to two
  back-link pages, duplicate back-link pages across scopes, orphan and dead-end back-link pages.
- `tools/page_render.cjs`: light, dark and phone rendering, console errors, missing files,
  overflow, and every linked page opened once.
- The scope's own checkers named in the brief.

## Limits

Reviewers are models reading for a purpose; their reports are advice, not proof. The blind reader
only approximates a human: it may know terms a beginner would not, so it must report any term it
understood only from its own knowledge. The fleet does not decide what William has learned and
keeps no record of his learning. Nothing is committed.
