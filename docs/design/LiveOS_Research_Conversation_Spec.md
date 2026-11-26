# LiveOS research through conversation

**Design for William’s review · November 25, 2026 · Draft 1**

## 1. The experience to build

William should be able to open a conversation and find a partner who has already studied the question. He can ask for the conclusion, interrupt halfway, examine the evidence behind one sentence, challenge an inference, or connect two points in a way nobody anticipated. While they talk, the partner can commission more work. When William says the discussion is ready, the partner hands the agreed argument to a writer.

This addresses a specific failure in the current vault. The writer receives extensive findings and must simultaneously discover the argument, establish its boundaries, predict what William will value, and design a readable page. Revisions often start after all four choices have already taken shape in HTML. The redesign puts **evidence collection before interpretation, interpretation before discussion, and discussion before publication**. The discussion can reopen any earlier step.

**William’s ordinary interface has two parts:** the live conversation and the final illustrated report. Tickets, research notes, challenges, indexes, review passes, and build files remain available for inspection or debugging. Reading them is optional. The same interaction must work by voice alone, including a car session. Text provides an equivalent interface and a durable record across rounds.

| Role | Question it owns | Durable output |
|---|---|---|
| **Researcher** | What evidence can settle this bounded question, and what evidence is missing? | Cited findings and identifiable source passages or data rows |
| **Interpreter** | What follows from that evidence in this domain? Under which conditions does the conclusion change? | A map of conclusions, relationships, rival interpretations, and boundaries |
| **Conversationalist** | How does William understand the structure, what should he be shown or asked next, and what needs another round? | Conversation record, William’s working outline, precise follow-up tickets, and eventually an approved writing brief |
| **Writer** | How can the agreed structure be presented accurately, economically, and visually? | Canonical publication sources that build into HTML and PDF |

The **Coordinator** is shared infrastructure. It owns the roster, queue, receipts, lifecycle, return delivery, and maintenance routing. Each of the four roles can have its own internal workflow. All handoffs between roles go through the Coordinator. A role is a responsibility that different providers can fulfill.

## 2. One conversation, end to end

This illustrative case uses a hypothetical financing agreement. It makes no claim about a particular company or jurisdiction.

1. **Prepare.** William wants to understand who can allow or prevent a company from borrowing. The Researcher locates the board provision and a separate investor-consent clause. The Interpreter identifies three different questions: who can authorize the company to act, whose consent the contract requires, and what happens if somebody proceeds without it.
2. **Open the discussion.** The Conversationalist leads with a short finding. “There are two decisions here. The board vote answers who can authorize the borrowing. The investor clause may still constrain whether the deal can proceed on the agreed terms. Which part should we open?” The contract passages are already indexed if William asks to see them.
3. **Challenge the inference.** William asks, “Are you saying the loan is invalid, or that somebody has a remedy afterward?” The partner identifies the unsupported inference and files an **interpretation** ticket against that claim. If the relevant remedy provision is missing, the Interpreter requests **research** through the Coordinator. The partner acknowledges the recorded task and keeps discussing the board vote.
4. **Challenge the evidence.** William also asks whether a later amendment changed the consent threshold. The partner immediately records a **research** ticket specifying the agreement, amendment, threshold, relevant date, and evidence needed. The two questions have different owners and may finish at different times.
5. **Bring up D.** At a natural pause the partner adds, “There is one condition we haven’t discussed. The consent clause applies above a threshold. Crossing it changes who has to agree. Should that threshold sit beside the approval diagram?” William says, “Yes. Organize this around where the transaction can be stopped. Put remedies on a separate branch.” That establishes the organizing principle for this report.
6. **Return to an earlier question.** Twenty minutes later the amendment task finishes and the Interpreter checks the consequences. The partner says, “The amendment check you asked for earlier is back. It changes the threshold in the diagram. The distinction between approval and remedy still holds.” If William has left, the same update is waiting at his next session.
7. **Publish when asked.** William says, “Good enough. Write it.” The writer receives the approved argument, evidence references, threshold revision, separate remedy branch, and any remaining uncertainty. The resulting figure should let a reader trace what happens on either side of the threshold.

The substantive outcome of this conversation is an editorial decision that raw research could not supply: William wants a transaction organized by the points where it can be stopped, with remedies shown separately. Remembering only that he asked several questions about borrowing would lose it.

## 3. What each role must produce

### Researcher — establish the evidence

- Accept one bounded research card. It identifies the question, the topic, the alternatives or missing fact, what evidence could distinguish them, and an expected return. The subsystem can assign a dispatcher, general workers, legal specialists, or document specialists. William does not manage that decomposition.
- Start at the topic directory. Reuse evidence with the right scope, date, and provenance. A stale record, a conflicting source, or a different product or legal regime justifies reopening the search. Record what prompted it.
- Keep source identity, edition or date, precise locator, and the observation it supports. Retain the existing tags for law text `[R]`, primary documents `[S]`, secondary sources `[W]`, vault cards `[V]`, general knowledge `[G]`, inference `[I]`, and unresolved searches `[U]`. A vault citation should resolve to the underlying evidence where available. “Not found” includes the scope actually checked.
- Return the evidence that discriminates between the alternatives, contradictory observations, gaps, and links to supporting material. A worker can suggest an inference and mark it as such. The Interpreter owns the project’s conclusion. Repeated claims from the same underlying source count as one line of evidence.

### Interpreter — work out what the evidence means

The Interpreter runs before a prepared discussion and again whenever findings or reasoning are challenged. Its first lines identify the domain, its governing question, the domain-specific method applied, and the source revisions covered. The Conversationalist can inspect every material outcome of that method.

| Domain | What the Interpreter must distinguish |
|---|---|
| Corporate law | Formal authority, practical ability to act or block action, who can enforce, available remedies, and what observed enforcement actually establishes. An absence of observed cases alone cannot establish permission. |
| Quantitative research | What information was available at decision time, how the signal was constructed, what assumptions drove the test, and whether costs or a different sample would change the conclusion. |
| Lean or formal mathematics | The exact statement, hypotheses, dependencies, and proof status. A checked proof, an informal argument, and an open obligation get distinct labels. |

These are examples of replaceable domain instructions. The routing protocol stays the same. A compound project can refer to more than one domain with an explicit question for each.

For each consequential point, record a stable ID, a short conclusion, evidence references, the inference connecting them, the applicable scope, and the condition or missing fact that would change the conclusion. Represent connections explicitly where they carry meaning, for example **requires**, **qualifies**, **contradicts**, **competes with**, or **changes the consequence of**. A small edge table is sufficient. The ID lets a speaker challenge one link without reopening the entire topic.

**Debate has a stopping condition.** When two interpretations would yield materially different answers, state the strongest evidence-backed version of each, identify their differing assumption, and check what observation could distinguish them. Return the supported interpretation, the live alternatives, or a bounded request for missing evidence. Keep a compact, checkable rationale and the surviving objections. A transcript of a staged debate adds no value to the handoff. Routine cases can use one interpretation pass.

For every point marked important, state **what William would misunderstand if he missed it**. That gives the Conversationalist a reason to raise point D. Disclose material dissent even when the writer will ultimately keep the discussion brief.

### Conversationalist — discuss the findings and learn their form

This is a learning partner. At the start of a prepared session it loads the current question, domain method, interpretation summary and relationships, William’s latest outline, and outstanding tickets. Evidence and prior turns are reachable by reference during the discussion. When a new topic lacks prepared analysis, it can scope the question with William and commission the first pass immediately. It identifies provisional answers while that work runs.

**A normal turn is sized for interruption.** Answer what was asked, give the condition or relationship needed to understand it, and offer the next detail when useful. Pull a known passage on demand. Delegate work that requires a fresh investigation or a substantial new inference. The voice session keeps accepting turns throughout. In hands-free use, speak the consequence and say a source or figure is available without requiring a screen.

Maintain three distinct views:

| View | Contents | Authority |
|---|---|---|
| **Interpreter’s map** | Supported conclusions, competing readings, qualifiers, source links, missing evidence, and consequences of omission | Revisioned by the Interpreter |
| **William’s working outline** | What he wants foregrounded, what he already grasps, which points he connects, how he orders the explanation, and what he wants set aside | Explicit statements and confirmed corrections outrank inferences about preference |
| **Discussion coverage** | Important points still unraised, raised and understood, contested, deferred, or commissioned for further work | Maintained by the Conversationalist against both maps |

Point IDs connect these views without copying the underlying research. Discussion frequency is a clue. Five turns on A may mean A is finally clear and needs one line. One sentence connecting C and D may determine the shape of the entire report. Likewise, two rival explanations must survive as alternatives if William sees them as the organizing question and the evidence leaves both open.

The Conversationalist should infer quietly when a choice is low-stakes and ask when ambiguity changes meaning, order, or design. A useful confirmation is “I heard C as a condition on D. Did you mean that, or that C and D are two explanations for the same outcome?” At a natural pause, surface a material point the user has missed and explain in one sentence what changes if it holds. Keep track of the rest and group related points across turns. William can lower a point’s prominence. An indispensable factual qualification stays attached to any claim that needs it.

Each important editorial choice stores its originating turn, scope, disposition, and whether it was explicit, confirmed, or inferred. Start with project-local learning. A candidate cross-project preference should carry examples and remain revisable. One session about control rights should not cause every future report to be organized around vetoes.

A compact outline entry could read `turn u-46 | explicit | foreground C-07 | place condition C-12 at the decision it changes | draw remedy C-19 as a separate branch`. That line can guide an illustration, survive a provider switch, and be corrected in a later round. It records the form of the explanation in William’s terms.

At the writing handoff, reconcile the Interpreter’s important points with discussion coverage. If a still-unheard point would change the proposed main conclusion, surface its consequence before freezing the brief. If William wants to finish immediately, carry it as an explicit qualification or narrow the conclusion. Respect points already understood or deliberately deferred. The reconciliation should take one short exchange in the ordinary case.

### Writer — turn an agreed argument into a report

Publication starts on William’s explicit instruction. The Conversationalist freezes a **writing brief** containing the governing question, audience and reading budget, ordered claims and relationships, required qualifications, evidence and interpretation revisions, requested comparisons, figure ideas, deliberate omissions, outstanding disagreements, and the conversation revision authorizing it. An outline might read “decision sequence, threshold at the relevant step, remedies as a separate branch.” The writer need not recover that instruction from 100 turns.

If an outstanding ticket could invalidate the proposed lead, the partner names the exact dependency. William can wait, narrow the report, or authorize publication with that limitation. Unrelated tickets keep running. A later material result generates a revision proposal linked to the published edition. It cannot silently change the approved argument.

The Writer controls wording, pacing, figures, tables, links, and presentation review. Internal reviewers may challenge accuracy or readability. They return advice to the Writer subsystem. One editor applies changes to the canonical content during revision. A newly discovered factual gap goes through the Coordinator to Researcher, a disputed inference to Interpreter, and a consequential editorial ambiguity to Conversationalist. Stage reviewers should be able to stop a materially misleading sentence without independently rewriting it.

## 4. Routes, tickets, and results during a live session

The Coordinator is the sole owner of the workflow ledger. A role submits a request naming its identity, the desired capability, the question or action, and where to return the result. The Coordinator validates scope, records the request in Git, returns a receipt, and assigns an eligible worker. Make predictable operations ordinary code: validate, persist, claim, retry, reconcile, and deliver. Use an agent for a diagnosis or an ambiguous research decision.

| Signal | Coordinator route | What the Conversationalist eventually gets back |
|---|---|---|
| New question or incomplete evidence | Researcher → Interpreter → session inbox | New evidence, resulting conclusion, limits, and affected prior claims |
| Disputed inference with evidence already available | Interpreter → session inbox | Which premise or inference survived, changed, or remains disputed |
| Evidence and inference both disputed | Researcher → Interpreter, linked to the same challenge | One coherent update on the challenge with references to both jobs |
| New connection, emphasis, or preferred ordering | Update working outline; send to Interpreter if it introduces a factual or logical claim | Recorded editorial choice, plus verification where needed |
| “Good enough, write it” | Freeze writing brief → Writer and its reviewers → build | Report edition linked to the approved brief and sources |
| Worker detects a stall or loses a capability | Coordinator → diagnostic worker or compatible replacement | Recovery outcome or one actionable blocker |

An arrow crossing a role boundary always denotes a Coordinator-mediated handoff. Every completion names the original question and destination. No worker needs the addresses or credentials of its peers.

### Repo-backed queue

The following paths are a proposed convention to map onto existing vault paths during implementation. Each represents one owner and one canonical copy. A topic worktree or runtime database may cache results.

| Location | Contract |
|---|---|
| `system/agents/` and a machine-readable roster | Canonical role definitions with supported capabilities, adapters, allowed read/write scopes, input/output types, and fallback rules |
| `workflow/outbox/<kind>/<ticket-id>.json` | Immutable request. The `research/` and `interpret/` directories are the two outgoing lists William described. Other kinds include `write/` and `diagnose/`. |
| `workflow/events/<ticket-id>/<sequence>.json` | Small ordered lifecycle records. Store transitions and output references once. Pending lists and dashboards are derived views. |
| `sessions/<session-id>/` | Ordered text turns, compact round checkpoints, William’s outline, and inbox delivery state. Store durable turns in bounded segments, with stable turn IDs. |
| `topics/<topic-id>/index.md` | One navigational entry point per topic. It points to canonical evidence, interpreter profile, current interpretation, and related topics. |
| Existing field research directories, plus topic interpretation records | Evidence by ID, cited observations, and revisioned conclusions. Keep existing field paths where stable IDs can resolve them. |
| `reports/<report-id>/` | Approved brief, publication Markdown, data references, figure/table definitions, and build manifest. Generated editions use a separate output directory excluded from Git. |

**Minimum ticket contract.** Version the schema. Use stable identifiers across providers. The question and completion test must be understandable to a new worker without the conversation transcript.

```json
{
  "schema_version": 1,
  "id": "T-0142",
  "kind": "research",
  "from": "conversationalist",
  "project": "financing-example",
  "topic": "borrowing-consent",
  "origin": {"session": "S-08", "turn": "u-41", "round": 2},
  "request_key": "S-08/u-41/amendment-check",
  "question_revision": 2,
  "input_revision": "git:<resolved-source-commit>",
  "claim_refs": ["C-07"],
  "question": "Did an effective amendment change the investor-consent threshold?",
  "scope_ref": "topics/borrowing-consent/index.md",
  "evidence_needed": "Executed amendment, effective date, and superseded clause.",
  "done_when": "Return the old and new thresholds with locators, or identify exactly which document is unavailable.",
  "after_success": "interpret",
  "return_to": {"session": "S-08", "topic": "borrowing-consent"}
}
```

The Coordinator adds timestamps, parent/dependency IDs, priority, assigned worker and attempt ID, and the effective model/tool identity in lifecycle records. A result carries the question revision, input and output revisions, outcome, claim IDs changed, source references, uncertainty, next action, and return destination. For interpretation, include the compact difference from the previous conclusion. The voice client receives that difference and pointers to the full result.

### Timing decision

**Use an immediate event on ticket creation and completion, plus a 60-second reconciliation check.** A successful Git write wakes the continuously running Coordinator or sends it a change event. Each minute it also checks the authoritative queue for missed work, abandoned leases, and undelivered results. A no-change tick performs no model call and creates no commit. Run this service on an available host independent of the active conversation or phone.

With polling alone and arrivals uniformly distributed between checks, a one-minute interval adds about **30 seconds on average** to discovery; five minutes adds about **2½ minutes**, before any work begins. Immediate events handle the normal case. The minute check is a recovery target for a healthy service, not a guarantee about model runtime or network outages. Measure ticket persistence, queue pickup, worker duration, and result-to-session delivery separately. This reveals where a 20-minute wait actually occurred.

**Durable acceptance and continuous speech are separate.** The voice handler submits work asynchronously and can take the next turn while Git is slow. A successful acknowledgment requires a committed request at the shared remote and includes its stable ID. A client may first show “saving.” If disconnected, it retains a local pending request where supported and states that shared dispatch is pending. Retry with the same request key. The user can continue discussing other claims in every case.

**Result delivery is also asynchronous.** After research, queue the linked interpretation automatically. After interpretation, persist the return event into the project/session inbox and send a lightweight notification to the active adapter. The partner uses the question, time, and what changed to frame a one- or two-sentence re-entry at the next natural pause. Avoid talking over William. Group simultaneous returns and prioritize those affecting the current argument. A closed session retains unread results for the next conversation on any supported host.

### Failure and recovery rules

- A single logical Coordinator serializes authoritative writes. Use atomic Git ref updates against the expected revision, re-read on conflict, and retry idempotently. Stage worker outputs in scoped worktrees or uploads, then land validated changes. Workers cannot overwrite the ledger.
- A request progresses through queued, claimed/running, and a terminal outcome such as completed, failed, canceled, or superseded. Record dependencies and temporary blockers explicitly. A lease and attempt ID bind the right to complete. Jobs may execute more than once after a crash. Only the current authorized attempt can publish an effective result.
- Recover the next action from the recorded state. A crash after research lands and before interpretation is scheduled must lead to exactly one effective interpretation request. Use a deterministic child request key. Apply the same principle to result notifications. A shared cursor records which returns the session has incorporated. If a device dies mid-sentence, a replacement can offer to resume the update.
- When William revises the question, record what the new revision supersedes. A late answer to the old version remains attributable to that version. Reuse valid evidence, but suppress outdated conclusions as current voice updates.
- Each worker reports progress at meaningful milestones and can return “stalled” with its last successful step, repeated attempts, missing input or capability, and suggested diagnostic. An **independent watchdog** detects a dead worker that cannot report itself. Separate liveness from progress: a 20-minute job can be healthy, and a worker can remain responsive while repeating the same search. Use capability-specific deadlines, bounded retries, then route to diagnostics. Record transitions in Git; keep heartbeat traffic in runtime state.

## 5. Memory, topic directories, and provider independence

**Across conversation rounds.** Persist text turns once, with timestamps, speaker, and stable order; corrections point back to the corrected turn. At round close or handoff, write a checkpoint containing the governing question, current map versions, confirmed connections, unresolved disagreements, deferred points, open tickets, and the last delivered event. Build the next session’s starting context from that checkpoint plus newer events. Retrieve exact prior wording when needed. This works when a new round uses a different provider. Raw audio need not be part of the repository.

**Bound what a role reads.** The per-topic index gives aliases, scope and exclusions, the domain method, canonical sources and useful sections, existing research cards, current claim map, related topic indexes, and known gaps. Keep this file short enough for routine startup. Index maintenance runs behind the scenes when accepted findings or relationships change. A move or rename must preserve stable IDs and update or redirect the path.

1. Give a worker its role contract, assigned card, and topic index. Follow exact file, section, claim, or data-row references first.
2. If the known sources cannot settle the question, allow scoped search of the topic, then an explicitly related topic or permitted external collection. Record the scope expansion and reason. Give each domain configurable read, time, and work budgets, with automatic escalation through the Coordinator where authorized.
3. Implement boundaries in the tool adapter or scoped workspace. A prompt telling an unrestricted agent to read less provides little control. Keep permissions separate from relevance. An agent may have authority to search the Delaware material and still need only one statute and two cited decisions.
4. Preserve a route for unexpected evidence. Workers can propose a new source or cross-topic connection. The Coordinator can grant a bounded expansion; the interpreter can test its significance. A topic index should guide discovery without freezing earlier assumptions.

**Provider adapters.** Keep the canonical role definitions and existing thin Claude Code and Codex adapters. Use the same envelope for a proposed Grok/Grokbot adapter. A worker advertises its capabilities, actual model identity where exposed, permissions, and limits. Record unknown model identity honestly. Route by capability and scope so changing models does not fork the project’s memory or protocol.

Voice clients additionally declare whether they can submit tickets, read durable session state, receive a background event mid-session, insert updates at turn boundaries, and resume across devices. Verify each target client with a small end-to-end test before claiming support. If the intended Grokbot client supports only turn-triggered tools, it can retrieve the inbox on the next turn. For the full hands-free experience, use a voice client or bridge that supports event delivery and speech at a natural pause. Keep provider-specific session IDs behind the adapter.

## 6. Publication, graphs, and storage

The Writer’s creative step ends when it commits the publication sources. **Everything from those sources to the delivered HTML and PDF is a deterministic build.** A fresh machine with the declared inputs should be able to reconstruct the text, tables, charts, and diagrams without asking a model to redraw or rewrite them.

| Source retained | Intended use |
|---|---|
| Markdown with stable section and claim references | Narrative, headings, captions, accessibility text, source links, and reading order |
| Small CSV or typed Parquet plus schema and units | CSV for small tables worth reviewing in a diff. Parquet for larger typed datasets where columnar storage is useful. Reuse the same source for every view. |
| Relationship table, declarative figure definition, or short versioned script | Reconstruct control-flow diagrams, evidence relationships, quantitative plots, and their labels. A table or figure can show a structural relationship more economically than prose. |
| Essential original image or primary document | Preserve once when its visual or evidentiary content cannot be regenerated. Keep identifiers, locators and hashes; reuse by reference. |
| Build manifest and pinned environment | Ordered inputs, data hashes, scripts, dependency versions, fonts, page dimensions, and renderer settings for both formats |

**Build and delivery.** Resolve and verify immutable inputs → validate figure IDs, units, source links, and references → generate tables and figures → render HTML and print PDF from the same content → check links, clipping, table breaks, and chart legibility → publish the edition outside the working Git tree. Semantic revisions edit the source. A layout-only edit to the shared theme can rebuild any supported edition.

Pin fonts, browser or renderer, locale, timezone, data ordering, and any layout seeds. Keep clocks and live URLs out of the generation path. A source URL identifies provenance; regeneration additionally requires the actual bytes. For oversized source data, store one retained, immutable, hash-verified object outside Git and commit its manifest. Preserve all transitive inputs needed by approved editions. Prefer compact Git-native sources whenever practical. A clean-build comparison must reproduce text, figures, tables, and pagination. If byte-identical PDFs are required, normalize volatile metadata and compare hashes across two isolated builds.

Use temporary previews during revision, then expire them. Keep generated HTML, PDF, intermediate images, dependency caches, and bulky worker traces out of ordinary Git commits. Store substantive review decisions as small deltas. The reported census of **17,179 MB in paths, 8,335 MB on disk, and 33,350 hard-linked paths** is the starting observation; those measures alone cannot attribute the duplication to any one role. Track canonical source growth, derived-output size, and retained external assets separately.

**Cleanup.** The Coordinator schedules the existing cleanup process. It first finds duplicates and unreferenced derivatives, then follows references from published editions, active jobs, manifests, topic indexes, and protected paths. Retain one recoverable copy of required evidence and test rebuildability before proposing removal. Preserve the vault’s existing protected list, backup, approval, and log for removal of vault material. Disposable previews and caches can expire under a declared retention policy. Routine maintenance stays invisible unless it needs a decision or encounters a broken dependency.

## 7. Fit the design to the agents already in the vault

Treat the supplied roster as the migration baseline. Before implementation, inspect the actual repository, its current shell-job ledger and renderer, and a representative topic. Reuse working contracts and code where their guarantees match. These proposed paths and assignments describe the target; the inventory and current behavior still need verification in the repository.

| Existing component | Place in the new system |
|---|---|
| `research-agent`, `law-boundary-research`, `legal-document-breakdown` | Researcher workers. Preserve their source practices and specialist tools. Supply their evidence and marked candidate interpretations to the domain Interpreter. Retain one owner for the adopted conclusion. |
| New Interpreter and domain profiles | Own the reasoning and debate currently scattered across research, writing, and technical revision. Draw on the existing six-layer document method and practical-boundary analysis. |
| New Conversationalist | Own the live rounds, working outline, proactive challenges, and authorized writing handoff. It can request any destination through the roster. |
| `report-writer`, `rev-technical`, `rev-reader`, `rev-plain-format`, `rev-editor` | Writer subsystem. Preserve the blind reader pass, independent source challenge, rendering checks, and one editing authority per revision. Compare the reader’s reconstruction against both the approved argument and its necessary qualifications. Apply existing visual/reading budgets within the scope of each publication. |
| `evaluator` / `structure-evaluator` | Independent verification shared across stages. Assess the actual inputs, outputs, and trace references on consequential handoffs and replay tests. Record a short verdict or a specific repair ticket. An author cannot approve its own output as independently reviewed. |
| `vault-cleanup`, diagnostics, watchdog, project maintenance | Coordinator-routed supporting capabilities. Maintenance also keeps indexes fresh and detects abandoned work, dangling references, and unavailable build inputs. |
| Canonical-plus-adapter layout, skills, `roles.md`, task instances | Retain the canonical role and skill definitions. Make role, adapter, assignment, and run distinct objects. Map old instance records to ledger IDs and preserve historical references before considering retirement of any old directory. |

Keep the existing shared agent contract for when to use a role, required capabilities, missing-capability reporting, write authority, worker/tool/model attribution, and final handoff shape. A five-line worker return is a machine-facing receipt. The user-facing voice summary is composed from verified changes and conversation state.

## 8. Implementation order and acceptance

Build a narrow end-to-end case before generalizing. One topic, one research worker, one interpreter profile, one voice client, and the existing writer are enough to demonstrate the essential interaction.

| Phase | Deliverable | Gate before expanding |
|---|---|---|
| 1. Contracts and durable loop | Topic index, claim/evidence IDs, role roster, ticket/receipt/result schemas, Coordinator, text session and inbox | Submit the same request twice, interrupt the worker, restart the Coordinator, and see one effective result with its provenance. |
| 2. Live voice and delayed return | Spoken turns, durable ticket submission, event delivery, checkpoints, and hands-free result handling | Simulate a 20-minute task. William can keep speaking, change subject, disconnect, and receive the dated result in the active or resumed conversation. Test ordinary speech continuing while the Git acknowledgment is delayed. |
| 3. Interpretation and judgment | One real domain profile, competing interpretations, challenges, coverage, and working outline | On a historical question, the partner distinguishes a missing fact from a disputed inference, raises a previously unmentioned consequential condition, and retains William’s chosen relationship and order. |
| 4. Authorized publication | Frozen brief, writer/revision integration, compact sources, deterministic HTML/PDF renderer, cleanup protections | One approval produces both illustrated formats. A fresh build reproduces them from retained inputs. Work completed before approval produces zero publication drafts. |
| 5. Portability and expansion | Additional Claude/Codex/Grok-capable adapters as verified, domains, scope controls, maintenance and diagnostics | Open a session from a second adapter, recover the working outline and outstanding ticket, and receive its result. Replace a worker provider without changing topic files or upstream ticket format. |

**Acceptance cases an implementer should carry into the tests**

1. **Taste and structure.** William discusses A five times, links C to D once, and overlooks E. E changes the main conclusion. The partner raises E, preserves the C–D relationship, and lets William give A one line. The frozen brief preserves all three decisions.
2. **Evidence versus preference.** William asks to background a condition he already understands. The writer can reduce its prominence while preserving its effect on the claim. If William disputes its truth, a ticket tests it against evidence.
3. **Two kinds of challenge.** With a source missing, a bounded research job precedes interpretation. With all cited facts accepted and only the inference disputed, existing evidence goes directly to interpretation. The resulting update identifies the original objection and what changed.
4. **Late results and shared memory.** Revision 1 finishes after William has reframed the question as revision 2. The earlier result remains recoverable under revision 1. Switching from desktop to a voice client loads the latest revision, open tickets, confirmed structure, and unread returns.
5. **Liveness without noise.** Miss a queue event, simulate a crashed worker, then simulate a healthy worker doing prolonged work. The reconciliation check recovers the missed event, the watchdog escalates the dead worker, and healthy work continues. Empty ticks create no Git traffic beyond checks and consume no model tokens.
6. **Bounded retrieval.** Give the legal worker a one-clause task in a large vault. Verify from the read trace that it began at the topic index, retrieved relevant passages, and justified any wider search. An inaccessible source results in an explicit gap.
7. **Rebuild and recovery.** Delete only disposable build outputs in a test workspace. Rebuild the approved edition and compare its text, graph relationships, chart values, table contents, and pagination. Simulate a missing immutable input and require the build to identify precisely what is missing.
8. **Reading burden.** Replay a question William previously critiqued. Compare the new spoken exchange and final report with the old page using the same evidence. Record which consequential distinctions he recovered, what he cut, and how often he had to correct the structure. A shorter result that loses a decisive condition fails.

**The first live demonstration should end with a recognizable moment.** William disputes a conclusion, hears that the challenge has been recorded, keeps talking about something else, and later hears exactly which part of the original argument changed. When he asks for the report, its structure reflects a connection he made during that discussion. That demonstrates why the four responsibilities belong in this order.
