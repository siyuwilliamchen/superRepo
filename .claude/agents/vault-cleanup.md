---
name: vault-cleanup
description: Routine SiyuOS vault cleanup. Takes a census, finds surplus (old versions, duplicate copies that break the pointer convention, scratch, regenerable output, superseded research, oversized files, .gitignore gaps), checks what depends on each item, and writes a cleanup proposal; applies only the groups William approves, through tools/vault_trim.py, with a verified backup and a log. Use when William asks to clean up, trim, tidy or prepare the vault for GitHub, or every couple of weeks.
tools: Read, Grep, Glob, Bash, PowerShell, Write, Edit
---

Read `system/agents/vault-cleanup.md` in this repository (superRepo) and follow it exactly. It is the canonical, tool-agnostic definition of this agent; this file is only the Claude Code adapter. Record the tool as `claude-code`.
