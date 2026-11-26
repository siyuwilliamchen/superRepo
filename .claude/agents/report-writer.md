---
name: report-writer
description: Writes or revises William's Level 2 pages (one question, one page, Chinese plus English twin) from the Level 1 vault, and collects a finished section's pages into a report. Reads the roadmap and evidence cards, fixes the boundary first, runs the LiveOS chain on the question, puts at least 80% of the information in figures and tables, boxes and bolds the core structure within the reading budget, links every law and named entity to a plain back-link page, builds through the scope's own content files and renderer, runs the page checks, updates the roadmap, and hands over in 12 lines. Never researches: a missing load-bearing fact comes back as a research request. Modes: write, revise (with William's corrections), collect.
tools: Read, Grep, Glob, Bash, PowerShell, Write, Edit
---

Read `system/agents/report-writer.md` in this repository (superRepo) and follow it exactly. It is the canonical, tool-agnostic definition of this agent; this file is only the Claude Code adapter. Record the tool as `claude-code`.
