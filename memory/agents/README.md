# Worker-specific memory

Use a unique lowercase ID for each concurrent worker assignment. Its
`current.md` records role, tool, exact model if known, owned paths, completed work,
source versions, checks, remaining uncertainty, and handoff dependency.

Two agents using the same model do not share scratch state. Reuse an ID only when
resuming that worker's assignment. Durable findings belong in the relevant
module/card, with this handoff linking to them.
