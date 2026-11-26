# Project skills

| Workflow | Canonical entry | Use |
|---|---|---|
| Context and handoff | [liveos-context](liveos-context/SKILL.md) | Start or resume scoped work and leave reusable state |
| Content intake | [vault-intake](vault-intake/SKILL.md) | Connect an authorized batch to sources, notes, memory and retrieval |
| Agent evaluation | [agent-evaluate](agent-evaluate/SKILL.md) | Review actual system use from traces and outputs; no self-certified pass |
| Revision fleet | [revision-fleet](revision-fleet/SKILL.md) | Three single-purpose reviews of an article, then one editor's changes |
| Research filing | [checkin](../../.claude/skills/checkin/SKILL.md) | File finished research when requested |
| News | [news](../../.claude/skills/news/SKILL.md) | Requested news workflow |
| Document breakdown | [legal-document-breakdown](../../.claude/skills/legal-document-breakdown/SKILL.md) | Analyse an important legal document |
| Reorganise an explanation | [imprint](../../.claude/skills/imprint/SKILL.md) | Requested imprint workflow; only its still-valid vault maintenance parts |

The linked legacy workflows stay in place. Do not copy them into each tool's
folder and let the copies drift. Their learned states, probes, and learning
check-ins remain abolished by the learning architecture.

These links make workflows accessible to all agents. Native automatic discovery
is host-specific and is not installed by this scaffold. Add a thin host adapter
only when needed, pointing back to the canonical workflow.

Agent definitions live in `system/agents/` (see [roles](../agents/roles.md)): `research-agent`,
`report-writer`, `rev-technical`, `rev-reader`, `rev-plain-format`, `rev-editor`,
`law-boundary-research`, `legal-document-breakdown`, `evaluator`.

Host adapters (thin; they only point to the canonical file):

| Host | Agents | Skills |
|---|---|---|
| Claude Code | `.claude/agents/<name>.md` (frontmatter `name`, `description`, `tools`) | `.claude/skills/<name>/SKILL.md` |
| Codex | `.codex/agents/<name>.toml` (`name`, `description`, `developer_instructions`) | `.agents/skills/<name>/SKILL.md` |

To add a workflow or agent: write the canonical file, then one adapter per host with the same
`name` and `description`. Never put instructions only in an adapter.

