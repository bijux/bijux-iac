"""Reconcile real provider-shaped observations without inventing hidden settings."""

import copy
import unittest

from scripts.governance import reconciliation


def snapshot(row):
    def grant(values):
        return {"user_id": None, "group_id": None, "deploy_key_id": None, **values}

    main = lambda push, merge: {
        "push_access_levels": [grant(value) for value in push],
        "merge_access_levels": [grant({"access_level": merge})],
        "allow_force_push": False,
        "unprotect_access_levels": [],
    }
    github = row["github_mirror"]
    canonical = row["canonical"]
    personal = row["personal_mirror"]
    return {
        "github": {
            "repository": {
                "id": github["id"],
                "full_name": github["path"],
                "default_branch": "main",
            },
            "actions": {"enabled": False},
            "history_guard": {
                "id": github["history_ruleset_id"],
                "target": "branch",
                "enforcement": "active",
                "bypass_actors": [],
                "conditions": {
                    "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}
                },
                "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}],
            },
            "admission": {
                "id": github["admission_ruleset_id"],
                "target": "branch",
                "enforcement": "active",
                "bypass_actors": github["admission_bypass"],
                "conditions": {
                    "ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}
                },
                "rules": [
                    {"type": "update"},
                    {
                        "type": "pull_request",
                        "parameters": {
                            "allowed_merge_methods": ["merge"],
                            "required_approving_review_count": 0,
                            "dismiss_stale_reviews_on_push": True,
                            "required_review_thread_resolution": True,
                            "require_code_owner_review": False,
                            "require_last_push_approval": False,
                            "require_extra_approval_for_unattributed_changes": True,
                            "required_reviewers": [],
                        },
                    },
                    {
                        "type": "required_status_checks",
                        "parameters": {
                            "strict_required_status_checks_policy": True,
                            "do_not_enforce_on_create": False,
                            "required_status_checks": [github["required_check"]],
                        },
                    },
                ],
            },
        },
        "canonical": {
            "project": {
                "id": canonical["id"],
                "path_with_namespace": canonical["path"],
                "default_branch": "main",
                "builds_access_level": "enabled",
            },
            "main": main([{"access_level": 0}], 40),
            "environment": {
                "name": "publication",
                "deploy_access_levels": [grant({"access_level": 40})],
            },
        },
        "personal": {
            "project": {
                "id": personal["id"],
                "path_with_namespace": personal["path"],
                "default_branch": "main",
                "builds_access_level": "disabled",
                "jobs_enabled": False,
                "shared_runners_enabled": False,
                "group_runners_enabled": False,
                "auto_devops_enabled": False,
            },
            "main": main(
                [{"access_level": 40, "deploy_key_id": personal["deploy_key_id"]}], 0
            ),
        },
    }


class MirrorReconciliationTests(unittest.TestCase):
    def test_exact_provider_shapes_match_without_authorizing_application(self):
        m = reconciliation
        from scripts.inventory.authority_governance import load_governance

        for row in load_governance()["repositories"]:
            result = m.reconcile(row["name"], snapshot(row))
            self.assertEqual(result["status"], "matched")
            self.assertEqual(result["unavailable"], [])
            self.assertIs(result["application_ready"], False)
            self.assertIs(result["remote_writes"], False)

    def test_public_projection_cannot_certify_private_settings_or_hidden_bypass(self):
        m = reconciliation
        from scripts.inventory.authority_governance import load_governance

        row = load_governance()["repositories"][0]
        observed = snapshot(row)
        observed["github"].pop("actions")
        observed["github"]["history_guard"].pop("bypass_actors")
        observed["personal"]["project"] = {
            "id": row["personal_mirror"]["id"],
            "path_with_namespace": row["personal_mirror"]["path"],
        }
        result = m.reconcile(row["name"], observed)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["differences"], [])
        self.assertIn("github.actions.enabled", result["unavailable"])
        self.assertIn("github.history_guard.bypass_actors", result["unavailable"])
        self.assertIn("personal.project.builds_access_level", result["unavailable"])

    def test_hidden_gitlab_grant_actors_are_unavailable_rather_than_absent(self):
        from scripts.inventory.authority_governance import load_governance

        row = load_governance()["repositories"][0]
        observed = snapshot(row)
        observed["canonical"]["main"]["merge_access_levels"][0].pop("user_id")
        result = reconciliation.reconcile(row["name"], observed)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("canonical.main.merge_access_levels", result["unavailable"])

    def test_legacy_actions_producer_force_push_and_ci_reenable_are_drift(self):
        m = reconciliation
        from scripts.inventory.authority_governance import load_governance

        row = load_governance()["repositories"][0]
        for change in [
            lambda s: s["github"]["actions"].update(enabled=True),
            lambda s: s["github"]["history_guard"].update(
                bypass_actors=row["github_mirror"]["admission_bypass"]
            ),
            lambda s: s["github"]["admission"]["rules"][2]["parameters"].update(
                required_status_checks=[
                    {"context": "std / report", "integration_id": 15368}
                ]
            ),
            lambda s: s["canonical"]["main"].update(allow_force_push=True),
            lambda s: s["github"]["admission"]["rules"][1]["parameters"].update(
                require_extra_approval_for_unattributed_changes=False
            ),
            lambda s: s["github"]["admission"]["rules"][0].update(
                parameters={"update_allows_fetch_and_merge": True}
            ),
            lambda s: s["canonical"]["main"]["merge_access_levels"][0].update(
                user_id=123
            ),
            lambda s: s["canonical"]["main"]["push_access_levels"][0].update(
                access_level=40
            ),
            lambda s: s["personal"]["project"].update(jobs_enabled=True),
            lambda s: s["personal"]["main"]["push_access_levels"].append(
                {
                    "access_level": 40,
                    "deploy_key_id": None,
                    "user_id": None,
                    "group_id": None,
                }
            ),
            lambda s: s["canonical"]["environment"]["deploy_access_levels"][0].update(
                access_level=30
            ),
        ]:
            observed = snapshot(row)
            change(observed)
            with self.subTest(observed=observed):
                self.assertEqual(m.reconcile(row["name"], observed)["status"], "drift")
