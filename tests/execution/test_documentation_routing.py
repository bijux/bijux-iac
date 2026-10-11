"""A routed manual request binds source, publisher and credential scope."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.execution import publication
from scripts.inventory.repositories import ROOT


class DocumentationRoutingTests(unittest.TestCase):
    def test_foundation_destination_is_selected_before_token_creation(self):
        with patch.object(publication, "validated_inventory", return_value={}), \
                patch.object(publication, "documentation_destination", return_value={"repository": "bijux.github.io", "path": "/standards/"}), \
                patch.object(publication, "gh_api_json", return_value={"sha": "b" * 40}) as api:
            self.assertEqual(publication.resolve_destination("bijux-std", "deploy-docs", "a" * 40),
                             {"repository": "bijux.github.io", "commit": "b" * 40, "path": "/standards/"})
        api.assert_called_once_with("repos/bijux/bijux.github.io/commits/main")

    def test_changed_or_incomplete_credential_scope_refuses(self):
        for revision in ("c" * 40, "main", None):
            with self.subTest(revision=revision), \
                    patch.object(publication, "validated_inventory", return_value={}), \
                    patch.object(publication, "documentation_destination", return_value={"repository": "bijux.github.io", "path": "/standards/"}), \
                    patch.object(publication, "gh_api_json", return_value={"sha": revision}), \
                    patch.dict(os.environ, {"PUBLICATION_DESTINATION_REPOSITORY": "bijux.github.io", "PUBLICATION_DESTINATION_COMMIT": "b" * 40}):
                with self.assertRaises(ValueError):
                    publication.resolve_destination("bijux-std", "deploy-docs", "a" * 40)

    def test_future_owned_foundation_site_preserves_its_requested_revision(self):
        with patch.object(publication, "validated_inventory", return_value={}), \
                patch.object(publication, "documentation_destination", return_value={"repository": "bijux-std", "path": "/bijux-std/"}), \
                patch.object(publication, "gh_api_json") as api:
            self.assertEqual(publication.resolve_destination("bijux-std", "deploy-docs", "a" * 40),
                             {"repository": "bijux-std", "commit": "a" * 40, "path": "/bijux-std/"})
        api.assert_not_called()

    def test_alias_admits_both_sources_and_never_reads_foundation_trust(self):
        destination = {"repository": "bijux.github.io", "commit": "b" * 40, "path": "/standards/"}
        def api(path):
            if path.endswith("/actions/variables/BIJUX_PUBLICATION_ACTOR_ID"):
                self.assertIn("/bijux.github.io/", path)
                return {"value": "123"}
            if path.endswith("/commits/main"):
                return {"sha": "a" * 40 if "/bijux-std/" in path else "b" * 40}
            self.fail(path)
        with patch.object(publication, "admit_controller", return_value="bijux-publication[bot]"), \
                patch.object(publication, "resolve_destination", return_value=destination), \
                patch.object(publication, "gh_api_json", side_effect=api), \
                patch.object(publication.runpy, "run_path", return_value={"public_api": api}), \
                patch.object(publication, "admit_repository", side_effect=[{"commit": "a" * 40}, {"commit": "b" * 40}]) as admit:
            receipt = publication.request("bijux-std", "deploy-docs", "a" * 40, "")
        self.assertEqual([call.args[:3] for call in admit.call_args_list],
                         [("bijux-std", "deploy-docs", "a" * 40), ("bijux.github.io", "deploy-docs", "b" * 40)])
        self.assertEqual(receipt["requested_source"], {"commit": "a" * 40})
        self.assertEqual(receipt["destination"], destination)
        self.assertTrue(admit.call_args_list[0].kwargs["public_source"])

    def test_denied_source_admission_cannot_dispatch(self):
        destination = {"repository": "bijux.github.io", "commit": "b" * 40, "path": "/infrastructure/"}
        with patch.object(publication, "admit_controller", return_value="bijux-publication[bot]"), \
                patch.object(publication, "resolve_destination", return_value=destination), \
                patch.object(publication, "gh_api_json", return_value={"value": "123"}), \
                patch.object(publication, "admit_repository", side_effect=ValueError("source checks failed")), \
                patch.object(publication.subprocess, "run") as write:
            with self.assertRaisesRegex(ValueError, "source checks failed"):
                publication.dispatch("bijux-iac", "deploy-docs", "a" * 40, "")
            write.assert_not_called()

    def test_either_accepted_revision_moving_cannot_dispatch(self):
        destination = {"repository": "bijux.github.io", "commit": "b" * 40, "path": "/standards/"}
        for changed in ("bijux-std", "bijux.github.io"):
            def api(path):
                if path.endswith("/actions/variables/BIJUX_PUBLICATION_ACTOR_ID"):
                    return {"value": "123"}
                if path.endswith("/commits/main"):
                    name = path.split("/")[2]
                    return {"sha": "c" * 40 if name == changed else ("a" * 40 if name == "bijux-std" else "b" * 40)}
                self.fail(path)
            with self.subTest(changed=changed), \
                    patch.object(publication, "admit_controller", return_value="bijux-publication[bot]"), \
                    patch.object(publication, "resolve_destination", return_value=destination), \
                    patch.object(publication, "admit_repository", side_effect=[{"commit": "a" * 40}, {"commit": "b" * 40}]), \
                    patch.object(publication, "gh_api_json", side_effect=api), \
                    patch.object(publication.runpy, "run_path", return_value={"public_api": api}), \
                    patch.object(publication.subprocess, "run") as write:
                with self.assertRaisesRegex(ValueError, "main changed"):
                    publication.dispatch("bijux-std", "deploy-docs", "a" * 40, "")
                write.assert_not_called()

    def test_dispatch_uses_only_the_admitted_publisher_commit(self):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as directory, \
                patch.object(publication, "ROOT", Path(directory)), \
                patch.object(publication, "request", return_value={"destination": {
                    "repository": "bijux.github.io", "commit": "b" * 40, "path": "/standards/"}}), \
                patch.dict(os.environ, {"GITHUB_SHA": "c" * 40, "GITHUB_RUN_ID": "12"}), \
                patch.object(publication.subprocess, "run") as write:
            publication.dispatch("bijux-std", "deploy-docs", "a" * 40, "")
        import json
        self.assertIn("repos/bijux/bijux.github.io/actions/workflows/deploy-docs.yml/dispatches", write.call_args.args[0])
        self.assertEqual(json.loads(write.call_args.kwargs["input"]), {"ref": "main", "inputs": {"accepted_commit": "b" * 40}})


if __name__ == "__main__":
    unittest.main()
