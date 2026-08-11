# opus-orchestration

**What it is.** A process skill for running large multi-deliverable tasks (document sets, research corpora, audits, migrations) with a strict division of labor: the premium main-thread model plans, holds gates between dependent phases, and does the final full review; a deterministic Workflow script plays taskmaster for free; Opus subagents inside the script do all research, drafting, adversarial verification, and fixing. Ships with `workflow-template.js`, a production-proven script skeleton.

**What it's good for.** Protecting usage limits on big delegated builds without giving up verification rigor. The verify machinery is the point: two-lens adversarial review per deliverable, then a convergence-safe fix loop (minimal edits, verify-before-writing on any comparative claim, scoped reverification) that actually terminates instead of playing whack-a-mole with fresh verifiers forever.

**Who it's for.** People whose main-thread model is the expensive one and whose deliverables have to survive hostile review. Extracted from a real five-deliverable research build where the pattern ran end to end: ~36 Opus agents, every document gated on adversarial verification before its dependents started.
