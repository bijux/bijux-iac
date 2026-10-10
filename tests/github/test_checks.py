from __future__ import annotations

import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.github import checks
from scripts.inventory.repositories import load_inventory

MAIN = "a" * 40
PR = "b" * 40


def run(context: str, commit: str = MAIN, *, identity: int = 1, conclusion: str = "success", app: int = 15368) -> dict:
    return {"id": identity, "name": context, "head_sha": commit, "app": {"id": app},
            "status": "completed", "conclusion": conclusion}


class AcceptedProducerTests(unittest.TestCase):
    def setUp(self):
        self.inventory = load_inventory()
        self.contexts = self.inventory["repositories"][0]["governance"]["branch_protection"]["required_status_checks"]
        self.inventory["repositories"] = self.inventory["repositories"][:1]

    def evidence(self, main_runs, pr_runs=(), prs=None):
        if prs is None:
            prs = [{"number": 1, "merged_at": "2026-10-10T12:00:00Z", "head": {"sha": PR}}]
        with patch.object(checks, "gh_api_json", side_effect=[{"sha": MAIN}, prs]), \
                patch.object(checks, "check_runs", side_effect=[main_runs, list(pr_runs)]):
            return checks.producer_evidence(self.inventory)

    def test_healthy_main_and_accepted_pr_only_checks_retain_source_bindings(self):
        receipt = self.evidence([run(context) for context in self.contexts], [run("policy / pr approval", PR)])
        self.assertEqual(receipt["status"], "producers-verified")
        self.assertIs(receipt["remote_writes"], False)
        observed = {item["context"]: item for item in receipt["repositories"][0]["checks"]}
        self.assertEqual(observed["policy / pr approval"]["commit"], PR)
        self.assertEqual(observed["std / report"]["commit"], MAIN)
        self.assertTrue(all(item["app_id"] == 15368 for item in observed.values()))

    def test_failed_latest_main_attempt_cannot_borrow_older_or_pr_success(self):
        for conclusion in ("failure", "cancelled", "skipped", None):
            with self.subTest(conclusion=conclusion):
                runs = [run(context) for context in self.contexts]
                retry = run("std / report", identity=2, conclusion=conclusion)
                if conclusion is None:
                    retry["status"] = "in_progress"
                receipt = self.evidence(runs + [retry], [run(context, PR) for context in self.contexts])
                self.assertEqual(len(receipt["errors"]), 1)
                self.assertIn("std / report", receipt["errors"][0])

    def test_successful_retry_supersedes_an_older_failure(self):
        runs = [run(context) for context in self.contexts]
        runs.extend([run("std / report", identity=2, conclusion="failure"), run("std / report", identity=3)])
        receipt = self.evidence(runs, [run("policy / pr approval", PR)])
        self.assertFalse(receipt["errors"])

    def test_wrong_commit_or_app_cannot_establish_a_producer(self):
        for commit, app in (("c" * 40, 15368), (MAIN, 999)):
            with self.subTest(commit=commit, app=app):
                runs = [run(context, commit, app=app) for context in self.contexts]
                receipt = self.evidence(runs)
                self.assertEqual(len(receipt["errors"]), len(self.contexts))

    def test_most_recent_merge_wins_over_pr_api_update_order(self):
        older = {"number": 1, "merged_at": "2026-10-09T12:00:00Z", "head": {"sha": "c" * 40}}
        newer = {"number": 2, "merged_at": "2026-10-10T12:00:00Z", "head": {"sha": PR}}
        receipt = self.evidence([run(context) for context in self.contexts], [run("policy / pr approval", PR)], [older, newer])
        self.assertEqual(receipt["repositories"][0]["accepted_pr"]["number"], 2)
        self.assertFalse(receipt["errors"])

    def test_malformed_check_pages_and_runs_fail_closed(self):
        valid = run("std / report")
        malformed = copy.deepcopy(valid)
        malformed["id"] = True
        for pages in ({}, [{"check_runs": {}}], [{"check_runs": [malformed]}], [{"check_runs": [None]}]):
            with self.subTest(pages=pages), patch.object(checks.subprocess, "check_output", return_value=json.dumps(pages)):
                with self.assertRaisesRegex(ValueError, "malformed"):
                    checks.check_runs("bijux-iac", MAIN)

    def test_failed_discovery_records_all_repositories_without_any_write(self):
        self.inventory = load_inventory()
        with patch.object(checks, "gh_api_json", side_effect=subprocess.CalledProcessError(1, ["gh", "api"])):
            receipt = checks.producer_evidence(self.inventory)
        self.assertEqual(len(receipt["repositories"]), 12)
        self.assertEqual(len(receipt["errors"]), 12)
        self.assertEqual(receipt["status"], "producers-unverified")
        self.assertIs(receipt["remote_writes"], False)
