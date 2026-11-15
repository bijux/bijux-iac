"""Routes describe intended authority without changing live governance."""
from __future__ import annotations

import copy
import unittest

from scripts.inventory.repositories import load_inventory
from scripts.inventory.authority import load_authority


class RepositoryAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.inventory = load_authority()
        self.repositories = {row['name']: row for row in self.inventory['repositories']}

    def test_exact_routes_retain_two_hubs_and_prepare_only_the_two_control_planes(self):
        oss = {'bijux-std', 'bijux-iac', 'bijux-core', 'bijux-atlas', 'bijux-canon',
               'bijux-ontology', 'bijux-ro-crate-node', 'bijux-gnss'}
        research = {'bijux-pollenomics', 'bijux-genomics', 'bijux-proteomics', 'bijux-phylogenetics'}
        hubs = {'bijux.github.io', 'bijux-masterclass'}
        self.assertEqual(set(self.repositories), oss | research | hubs)
        for name, repository in self.repositories.items():
            authority = repository.get('authority')
            self.assertIsInstance(authority, dict, name)
            self.assertEqual(authority['current']['host'], 'github.com')
            self.assertEqual(authority['current']['path'], 'bijux/' + name)
            if name in hubs:
                self.assertEqual(authority['status'], 'retained')
                self.assertEqual(authority['target'], authority['current'])
                self.assertEqual(authority['mirrors'], [])
            else:
                self.assertEqual(authority['target']['host'], 'gitlab.com')
                self.assertEqual(authority['target']['path'],
                                 ('bijux-oss/' if name in oss else 'bijux-edu/') + name)
                self.assertEqual(authority['status'], 'preparing' if name in {'bijux-std', 'bijux-iac'} else 'planned')
                self.assertEqual({row['path'] for row in authority['mirrors']}, {'bijux/' + name})
                self.assertEqual({row['host'] for row in authority['mirrors']}, {'github.com', 'gitlab.com'})
                self.assertTrue(all(row['execution_enabled'] is False for row in authority['mirrors']))
            self.assertIs(authority['mirror_publication']['enabled'], False)

    def test_identity_route_execution_and_activation_drift_fail_closed(self):
        from scripts.inventory.authority import validate_authority
        validate_authority(self.inventory)
        mutations = [
            lambda row: row.pop('authority'),
            lambda row: row['authority'].update(unknown=True),
            lambda row: row['authority']['current'].update(id=True),
            lambda row: row['authority']['target'].update(host='github.com'),
            lambda row: row['authority']['target'].update(path='bijux-edu/bijux-iac'),
            lambda row: row['authority']['target'].update(id=None),
            lambda row: row['authority']['target'].update(id='88949971'),
            lambda row: row['authority']['target'].update(execution_provider='github-actions'),
            lambda row: row['authority'].update(status='active'),
            lambda row: row['authority']['mirrors'][0].update(execution_enabled=True),
            lambda row: row['authority']['mirrors'][0].update(id=999),
            lambda row: row['authority']['mirrors'].pop(),
            lambda row: row['authority']['mirror_publication'].update(enabled=True),
            lambda row: row['authority']['mirror_publication'].update(writer='any-job'),
            lambda row: row['authority']['mirror_publication'].update(branches=['*']),
            lambda row: row['authority']['mirror_publication'].update(tags='all'),
        ]
        for mutate in mutations:
            inventory = copy.deepcopy(self.inventory)
            row = next(row for row in inventory['repositories'] if row['name'] == 'bijux-iac')
            mutate(row)
            with self.subTest(row=row), self.assertRaises(ValueError):
                validate_authority(inventory)

    def test_hub_routes_cannot_be_enrolled_or_assigned_mirrors(self):
        from scripts.inventory.authority import validate_authority
        for name in ('bijux.github.io', 'bijux-masterclass'):
            for mutate in (lambda row: row['authority'].update(status='preparing'),
                           lambda row: row['authority']['target'].update(host='gitlab.com'),
                           lambda row: row['authority']['mirrors'].append({'host':'gitlab.com'}),
                           lambda row: row['authority']['current'].update(execution_provider='disabled'),
                           lambda row: row['authority']['mirror_publication'].update(enabled=0)):
                inventory = copy.deepcopy(self.inventory)
                row = next(row for row in inventory['repositories'] if row['name'] == name)
                mutate(row)
                with self.subTest(repository=name), self.assertRaises(ValueError):
                    validate_authority(inventory)

    def test_rendering_ignores_intended_authority_and_preserves_existing_github_resources(self):
        import json
        from unittest.mock import patch
        from scripts.terraform.render import ROOT, render_payload
        before = json.loads((ROOT / 'infra/github/repository-rulesets/terraform.auto.tfvars.json').read_text())
        with patch('scripts.terraform.render.validated_inventory', return_value=load_inventory()):
            after = render_payload()
        for name in before['ruleset_repositories']:
            self.assertIn(name, after['ruleset_repositories'])
            self.assertEqual(before['ruleset_required_status_checks'][name], after['ruleset_required_status_checks'][name])
        self.assertEqual(after,before)
        self.assertNotIn('bijux-ontology', after['ruleset_repositories'])
        self.assertIn('bijux-ontology', self.repositories)

    def test_inventory_validation_cannot_bypass_authority_policy(self):
        from scripts.inventory.validate import validate_inventory
        from unittest.mock import patch
        inventory = copy.deepcopy(self.inventory)
        inventory['repositories'][0]['authority']['target']['path'] = 'unapproved/project'
        with patch('scripts.inventory.authority.load_authority', return_value=inventory), \
                self.assertRaisesRegex(SystemExit, 'authority identity/provider'):
            validate_inventory(load_inventory())

    def test_schema_membership_and_duplicate_keys_cannot_hide_unaccepted_roles(self):
        from scripts.inventory.authority import load_authority, validate_authority
        from unittest.mock import Mock
        for mutate in (lambda data: data.update(version=True),
                       lambda data: data.update(unknown='unapproved'),
                       lambda data: data['repositories'].append(copy.deepcopy(data['repositories'][0])),
                       lambda data: data['repositories'].pop(),
                       lambda data: data['repositories'][0].update(name='unlisted-repository')):
            inventory=copy.deepcopy(self.inventory); mutate(inventory)
            with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                validate_authority(inventory)
        path=Mock()
        path.read_text.return_value='{"version":1,"version":2,"repositories":[]}'
        with self.assertRaisesRegex(ValueError,'duplicate inventory key'):
            load_authority(path)

    def test_current_live_membership_remains_bound_to_the_accepted_standard(self):
        live={row['name'] for row in load_inventory()['repositories']}
        self.assertEqual(set(self.repositories)-live,{'bijux-ontology'})
        self.assertEqual(self.repositories['bijux-ontology']['authority']['status'],'planned')
        self.assertEqual(len(live),13)
