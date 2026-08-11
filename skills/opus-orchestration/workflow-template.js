// Workflow script template for the opus-orchestration skill.
// Ran in production 2026-08-04 (five-deliverable research build, 36 Opus agents, all gates passed).
// API available inside scripts: agent(), parallel(), pipeline(), phase(title), log(), args, budget, workflow().
// NOT available: bash(), Date.now(), Math.random(), filesystem. Shell work goes through an agent.
// Adapt the ALL-CAPS placeholders; keep the schemas, VERIFY_COMMON, fixLoop, and runDoc as they are.

export const meta = {
  name: 'NAME-ME',
  description: 'ONE LINE: what this run produces',
  phases: [
    { title: 'Doc1', detail: 'research fan-out, writer, verify, fix loop', model: 'opus' },
    { title: 'Doc2', detail: 'writer, verify, fix loop (gated on Doc1)', model: 'opus' },
  ],
}

const REPO = '/ABSOLUTE/PATH/TO/REPO'
const TODAY = 'STAMP THE DATE HERE (no Date.now() in scripts)'

const WRITER_SCHEMA = {
  type: 'object',
  required: ['summary', 'deviations'],
  properties: {
    summary: { type: 'string', description: 'Max 200 words, what the document concludes' },
    deviations: { type: 'array', items: { type: 'string' }, description: 'Every place a specific number or claim tempted you and what you wrote instead' },
    notes: { type: 'string' },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['pass', 'issues', 'summary'],
  properties: {
    pass: { type: 'boolean', description: 'false if any substantive issue exists' },
    issues: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'description'],
        properties: {
          severity: { type: 'string', enum: ['substantive', 'minor'] },
          description: { type: 'string' },
          location: { type: 'string' },
        },
      },
    },
    summary: { type: 'string' },
  },
}

const VERIFY_COMMON = 'You are an adversarial verifier. Your job is to find problems, not to approve. Default to reporting an issue when uncertain. A substantive issue is anything that could mislead the decision this document informs or violate a binding repo rule; everything else is minor. pass is false if any substantive issue exists.'

// Convergence-safe fix loop: minimal-edit fixer with verify-before-writing, then a
// reverify SCOPED to the edits (never a fresh full-document expedition). Two rounds max;
// unresolved issues return to the main thread for judgment.
async function fixLoop(doc, initialIssues, evidenceNote, phaseLabel) {
  let allIssues = initialIssues
  let finalVerdict = null
  const rounds = []
  for (let i = 0; i < 2 && allIssues.length > 0; i++) {
    await agent([
      'You are making MINIMAL corrections to ' + doc + '. Everything not listed below is verified and must not be touched.',
      'Read the repo rule file(s) first, then the document sections around each issue.',
      'CRITICAL PROCESS RULE: before writing ANY replacement sentence that makes a comparison, asserts a pattern, or asserts an absence, verify it against the evidence base (' + evidenceNote + ') or the primary source (load web tools via ToolSearch "select:WebSearch,WebFetch"). Print inputs, never derive numbers. When a fix changes a claim reused elsewhere in the doc, update the reuse sites.',
      'Issues (JSON):',
      JSON.stringify(allIssues, null, 2),
      'Fix every issue. Decline only with fetched evidence quoted in your return text. Return before and after text of each edit.',
    ].join('\n\n'), { label: 'fix:' + phaseLabel + '-r' + (i + 1), model: 'opus', phase: phaseLabel })

    finalVerdict = await agent([
      VERIFY_COMMON,
      'Target: ' + doc + '. This is a SCOPED reverification after a fix round. Confirm each issue below is resolved faithfully and no surrounding text was damaged (read 10 lines either side of each edit). Treat any newly rewritten comparative or absence claim as guilty until verified against the evidence base (' + evidenceNote + '). Then a mechanical style sweep of the whole file. Do not launch a new full-document investigation.',
      'Issues that were to be fixed (JSON):',
      JSON.stringify(allIssues, null, 2),
    ].join('\n\n'), { label: 'reverify:' + phaseLabel + '-r' + (i + 1), model: 'opus', phase: phaseLabel, schema: VERDICT_SCHEMA })

    rounds.push({ round: i + 1, pass: finalVerdict ? finalVerdict.pass : null })
    if (finalVerdict && finalVerdict.pass) break
    allIssues = finalVerdict ? finalVerdict.issues : []
  }
  return { rounds, finalVerdict }
}

// One deliverable end to end: writer -> parallel verifiers -> fix loop. Returns a gate result.
async function runDoc(cfg) {
  const draft = await agent(cfg.writerPrompt, { label: 'write:' + cfg.key, model: 'opus', phase: cfg.phase, schema: WRITER_SCHEMA })
  if (!draft) return { file: cfg.file, cleared: false, reason: 'writer agent died' }

  const verdicts = (await parallel(cfg.verifiers.map(v => () =>
    agent(v.prompt, { label: 'verify:' + cfg.key + '-' + v.key, model: 'opus', phase: cfg.phase, schema: VERDICT_SCHEMA })
  ))).filter(Boolean)

  const allIssues = verdicts.flatMap(v => v.issues)
  const failedInitially = verdicts.some(v => !v.pass) || allIssues.some(i => i.severity === 'substantive')

  let loop = { rounds: [], finalVerdict: null }
  if (failedInitially) {
    log(cfg.key + ': ' + allIssues.filter(x => x.severity === 'substantive').length + ' substantive issues, running fix loop')
    loop = await fixLoop(cfg.file, allIssues, cfg.evidenceNote, cfg.phase)
  }

  return {
    file: cfg.file,
    cleared: failedInitially ? !!(loop.finalVerdict && loop.finalVerdict.pass) : true,
    summary: draft.summary,
    deviations: draft.deviations,
    initialVerdicts: verdicts.map(v => ({ pass: v.pass, summary: v.summary, issueCount: v.issues.length })),
    fixRounds: loop.rounds,
    finalVerdict: loop.finalVerdict ? { pass: loop.finalVerdict.pass, summary: loop.finalVerdict.summary, issues: loop.finalVerdict.issues } : { note: failedInitially ? 'fix loop did not conclude; main thread decides' : 'passed on first verify' },
  }
}

// ---- Example run: research fan-out for doc 1, then doc 2 gated on doc 1 ----

phase('Doc1')

const research = (await parallel([
  'ANGLE 1 RESEARCH PROMPT',
  'ANGLE 2 RESEARCH PROMPT',
].map((p, i) => () => agent([
  p,
  'Method: load web tools first via ToolSearch query "select:WebSearch,WebFetch". Favor sources from the last twelve months as of ' + TODAY + '; older seminal sources allowed with dates stated. Every nontrivial claim needs a URL and a date. Label vendor versus third-party versus paper sources.',
  'Your final text is raw data for a writer agent, not a human-facing message. Return a dense cited markdown report. No preamble, no filler.',
].join('\n\n'), { label: 'research:' + (i + 1), model: 'opus', phase: 'Doc1' })))).filter(Boolean)

const doc1 = await runDoc({
  key: 'doc1',
  file: REPO + '/PATH/TO/doc1.md',
  phase: 'Doc1',
  evidenceNote: 'the research reports embedded in the writer prompt',
  writerPrompt: [
    'Read the binding rule files in full first: LIST THEM.',
    'Task: write ' + REPO + '/PATH/TO/doc1.md with the Write tool. REQUIRED CONTENT SPEC HERE.',
    'Number discipline: no committed targets; ranges only with labeled assumptions; never derive numbers from cited ones, print the inputs; every reused figure keeps its source; unknowns become open questions. Log every temptation in deviations.',
    'Return structured output: summary, deviations, notes.',
    '=== RESEARCH REPORTS ===',
    research.join('\n\n--- NEXT REPORT ---\n\n'),
  ].join('\n'),
  verifiers: [
    { key: 'grounding', prompt: VERIFY_COMMON + '\n\nTarget: ' + REPO + '/PATH/TO/doc1.md. Read it in full. Spot-check at least 8 load-bearing cited claims against their actual sources (load web tools via ToolSearch). Flag uncited claims, citations that do not support the claim, stale sources presented as current, and vendor claims stated as fact.' },
    { key: 'rules', prompt: VERIFY_COMMON + '\n\nTarget: ' + REPO + '/PATH/TO/doc1.md. Read the binding rule files, then the document. Check rule compliance, style, confidentiality, required coverage, and that every number is cited or framed as an open question.' },
  ],
})

// GATE: doc 2 builds on doc 1 only if it cleared. If not, return and let the main thread decide.
if (!doc1.cleared) return { doc1, halted: 'doc1 failed verification; main thread review required' }

phase('Doc2')

const doc2 = await runDoc({
  key: 'doc2',
  file: REPO + '/PATH/TO/doc2.md',
  phase: 'Doc2',
  evidenceNote: REPO + '/PATH/TO/doc1.md',
  writerPrompt: 'READS doc1 FROM DISK AS VERIFIED EVIDENCE BASE; SPEC HERE. Same number discipline and structured output as doc 1.',
  verifiers: [
    { key: 'grounding', prompt: VERIFY_COMMON + '\n\nTarget: ' + REPO + '/PATH/TO/doc2.md. First read ' + REPO + '/PATH/TO/doc1.md in full (the verified evidence base), then the target. Every claim citing the evidence base must match it exactly: no drift, no strengthening, no derived numbers. Spot-check external citations by fetching.' },
    { key: 'rules', prompt: VERIFY_COMMON + '\n\nTarget: ' + REPO + '/PATH/TO/doc2.md. Rule compliance, style, coverage, as for doc 1.' },
  ],
})

return { doc1, doc2 }
