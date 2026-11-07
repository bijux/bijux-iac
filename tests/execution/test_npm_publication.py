"""Keep first-publication admission separate from observed delivery history."""
from __future__ import annotations

import copy
import json
import os
import unittest
from unittest.mock import patch

from scripts.execution import publication
from scripts.inventory import publication as inventory


class NpmPublicationTests(unittest.TestCase):
    def test_initial_planned_delivery_requires_explicit_enablement_and_candidate(self):
        model={'repositories':[{'name':'bijux-ro-crate-node','delivery':{'documentation':'not-applicable','packages':'planned'}}]}
        declared={'bijux-ro-crate-node':{'release-npm':{'mode':'manual-only','controller':'iac'}}}
        with patch.object(inventory,'publisher_declarations',return_value=declared):
            with patch.object(inventory,'npm_enabled',return_value=False):
                with self.assertRaisesRegex(ValueError,'disabled'):
                    inventory.validate_request(model,'bijux-ro-crate-node','release-npm','a'*40,'v0.1.0',candidate_run='12')
            with patch.object(inventory,'npm_enabled',return_value=True):
                inventory.validate_request(model,'bijux-ro-crate-node','release-npm','a'*40,'v0.1.0',candidate_run='12')
                for value in ['', '-1', 'main', '0']:
                    with self.subTest(candidate=value),self.assertRaisesRegex(ValueError,'candidate'):
                        inventory.validate_request(model,'bijux-ro-crate-node','release-npm','a'*40,'v0.1.0',candidate_run=value)
        self.assertEqual(model['repositories'][0]['delivery']['packages'],'planned')

    def test_candidate_is_bound_to_successful_same_repo_manual_source(self):
        name='bijux/bijux-ro-crate-node'
        run={'id':123,'repository':{'full_name':name},'head_repository':{'full_name':name},'workflow_id':12,
             'head_sha':'a'*40,'head_branch':'main','event':'workflow_dispatch','status':'completed','conclusion':'success'}
        for change in [{},{'head_sha':'b'*40},{'head_branch':'feature'},{'event':'pull_request'},
                       {'head_repository':{'full_name':'outside/fork'}},{'conclusion':'failure'}]:
            with patch.dict(os.environ,{'PUBLICATION_TARGET_CANDIDATE_RUN':'123'}), \
                 patch.object(publication,'gh_api_json',side_effect=[{'id':12,'path':'.github/workflows/package-candidate.yml'},{**run,**change}]):
                if not change:
                    self.assertEqual(publication.npm_candidate('bijux-ro-crate-node','a'*40)['run_id'],123)
                else:
                    with self.subTest(change=change),self.assertRaises(ValueError):
                        publication.npm_candidate('bijux-ro-crate-node','a'*40)

    def test_dispatch_carries_only_the_admitted_candidate_and_immutable_inputs(self):
        receipt={'repository':'bijux-ro-crate-node','commit':'a'*40,'npm_candidate':{'run_id':123},
                 'destination':{'repository':'bijux-ro-crate-node','commit':'a'*40}}
        with patch.object(publication,'preflight',return_value=copy.deepcopy(receipt)), \
             patch.object(publication,'write_receipt'),patch.object(publication.subprocess,'run') as write:
            publication.dispatch('bijux-ro-crate-node','release-npm','a'*40,'v0.1.0')
        payload=json.loads(write.call_args.kwargs['input'])
        self.assertEqual(payload,{'ref':'main','inputs':{'accepted_commit':'a'*40,'release_tag':'v0.1.0','candidate_run_id':'123'}})

    def test_npm_only_audit_checks_its_own_trust_without_a_docs_route(self):
        from scripts.github import publication as audit
        model={'repositories':[{'name':'bijux-ro-crate-node'}]}
        declared={'bijux-ro-crate-node':{'release-npm':{'mode':'manual-only','controller':'iac'}}}
        with patch.object(audit,'publisher_declarations',return_value=declared), \
             patch.object(audit,'documentation_destination') as docs, \
             patch.object(audit,'gh_api_json',side_effect=[{'sha':'a'*40},{'truncated':False,'tree':[]},{'value':'123'}]) as api:
            receipt=audit.audit(model,'123')
        docs.assert_not_called()
        self.assertEqual(api.call_args.args,('repos/bijux/bijux-ro-crate-node/actions/variables/BIJUX_PUBLICATION_ACTOR_ID',))
        self.assertEqual(receipt['status'],'drift')
        self.assertIs(receipt['remote_writes'],False)
        self.assertTrue(receipt['mismatches'])
