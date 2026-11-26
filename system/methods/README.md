# Methods and pipelines

This is the shared methods index for every tool, worker and model. Existing
procedures remain canonical where linked; their abolished learning-state steps
do not apply. These methods evaluate the AI's work, never William's learning.

| Work | Entry | Result |
|---|---|---|
| Start/resume a task | [Context skill](../skills/liveos-context/SKILL.md) | Scoped rules, memory, cards, evidence and a worker handoff |
| Add supplied material or file finished research | [Content intake](content-intake.md) | Sources registered, notes connected, indexes and memory updated, dated receipt |
| Reason from evidence | [LifeOS method](<../../Project_Management/LifeOS Method.md>) | A bounded judgment with competing explanation and a test |
| Create/revise a reading page | [Learning architecture](<../../Project_Management/Learning Architecture.md>) | One question, linked bilingual pages and an updated roadmap |
| Take apart a legal document | [Document breakdown](<../../Project_Management/Document Breakdown Procedure.md>) | Rights, money, powers, limits and correction paths traced to the document |
| Check whether an agent used this system | [Agent evaluation](agent-evaluation.md) | Trace-based process checks and a separate review of actual behavior |
| Research one card | [Research agent](../agents/research-agent.md) | Findings with tagged evidence, a source manifest and a 5-line summary |
| Write, revise or collect reading pages | [Report writer](../agents/report-writer.md) | One-question bilingual pages, checks run, roadmap updated, 12-line handover |
| Review and revise a reading article | [Revision fleet](revision-fleet.md), [dispatch](../skills/revision-fleet/SKILL.md) | Three single-purpose reviews (technical boundaries, blind reader of the boxed core path, plain language and links), then one editor's changes and decision log |
| Hand work between roles | [Coordinator](coordinator.md) | One ticket per request key, a receipt, one authorised attempt, exactly-once follow-on, delivery to the session inbox, stall guard |
| Talk a researched question through with William | [Conversationalist](conversationalist.md), [role](../agents/conversationalist.md) | Durable turns and corrections, his working outline, tickets with their true acknowledgment level, delayed results brought back once with provenance, checkpoint, frozen writing brief |
| Work out what the evidence means | [Interpreter](../agents/interpreter.md), `tools/claimmap.py`, `topics/<topic>/claims/FORMAT.md` | A revisioned claim map: conclusions with evidence refs, inference, scope and breaking condition; edge table; rivals and their deciding observation; the compact difference per interpret ticket |
| Watch the watchers | [Watchdog](watchdog.md) | Dead or late Coordinator service and relays, interrupted jobs, overdue attempts by kind; reconcile or one diagnose ticket through the Coordinator; idle ticks write nothing |
| Publish an approved brief | [Publication](publication.md) | Package of sources under `reports/`, deterministic HTML and PDF edition outside git, byte-for-byte verify, revision proposals |
| Keep and clean durable material (scratch pilot) | [Ledger and Housekeeper](ledger.md) | Records with stable ids, required-input chain, eligible / held / unresolved, approval bound to versions, verified retire and restore; fixture-tested, vault read-only |

The existing filing pipeline is `Project_Management/Check-in Procedure.md`, its
Claude `checkin` skill, and `Project_Management/tools/vault.py`. The new intake
entry connects those to module memory, key cards and scoped search. It does not
mean that every old file has already been filed or every host auto-loads skills.

Originals, research, distilled notes, working memory and reader pages are different
things. Copying a source into a folder completes only the first part of intake.
