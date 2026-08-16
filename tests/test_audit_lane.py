#!/usr/bin/env python3
"""Smoke check for the audit lane (task 6.3): an audit-shaped run opens,
records tagged findings and evidence, and closes — all inside the frozen
23-event vocabulary, stage `open` for its whole life, release untouched.
"""

import unittest

from clodex_harness import ClodexCheck


class AuditLane(ClodexCheck):
    def test_exploit_audit_run_opens_investigates_and_closes(self):
        run_dir = self.repo / ".clodex" / "r-2026-08-16-a"
        run_dir.mkdir(parents=True)
        events = [
            {"e": "run:opened", "run": "r-2026-08-16-a", "repo": str(self.repo),
             "branch": "main", "lane": "audit",
             "brief": "assess the intake stack end to end",
             "git": {"start_head": self.head(), "dirty_at_start": []}},
            {"e": "finding:recorded", "id": "a-F001", "source": "audit",
             "severity": "high",
             "summary": "the poll transport diverges from the repo's proven job pattern",
             "location": "n8n/primer-poll.json",
             "detail": "VERIFIED (read both transports): the Cloud-Run-job shape is live for the isomorphic case"},
            {"e": "verification:evidence",
             "item": {"class": "tests",
                      "how": "audit report written",
                      "result": "reports/2026-08-16-stack-audit.md sha256 deadbeef"}},
            {"e": "finding:disposed", "id": "a-F001", "disposition": "accepted",
             "note": "report content, acknowledged; routed to a feature run"},
            {"e": "run:closed"},
        ]
        for event in events:
            result = self.append(run_dir, event)
            self.assertEqual(result.returncode, 0, (event, result.stderr))

        snap = self.rebuild(run_dir)
        self.assertEqual(snap["lane"], "audit")
        self.assertEqual(snap["stage"], "closed")
        # No stage:*:entered was ever appended — the audit lived at `open`.
        self.assertEqual(snap["release"]["state"], "not-started",
                         "an audit must not touch release machinery")
        finding = snap["findings"][0]
        self.assertEqual(finding["source"], "audit")
        self.assertEqual(finding["disposition"], "accepted")
        self.assertIn("VERIFIED", finding["detail"])
        self.assertIn("routed", finding["note"])
        self.assertEqual(len(snap["verification"]["evidence"]), 1)

    def test_control_audit_skill_is_installed_beside_the_others(self):
        from clodex_harness import CATALOGUE

        skill = CATALOGUE / "skills" / "clodex-audit" / "SKILL.md"
        self.assertTrue(skill.exists())
        text = skill.read_text()
        for anchor in ("VERIFIED", "HYPOTHESIS", "Corrections to the prompt's premises",
                       "Deliberate-simplicity keeps", "Locked constraints",
                       "Routing", "not-started"):
            self.assertIn(anchor, text, anchor)


if __name__ == "__main__":
    unittest.main()
