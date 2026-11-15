"""Execute exact source-owned GitLab job contracts with fresh native evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from types import ModuleType
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]


def source_module(path, name):
    module = ModuleType('bijux_gitlab_execution_' + name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


PIPELINE = source_module(Path(__file__).with_name('pipeline.py'), 'pipeline')
CI = source_module(ROOT / 'tests/bijux-docs/execution/ci_context.py', 'context')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def runtime_environment(root, original):
    artifacts = root / 'artifacts'
    scratch = artifacts / 'gitlab/runtime'
    scratch.mkdir(parents=True, exist_ok=True)
    require(not scratch.is_symlink() and scratch.resolve().is_relative_to(artifacts.resolve()),
            'Runtime scratch must remain under ordinary repository artifacts')
    environment = {**original, 'TMPDIR':str(scratch), 'TMP':str(scratch), 'TEMP':str(scratch),
            'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONUNBUFFERED':'1',
            'PIP_CACHE_DIR':str(artifacts / 'gitlab/cache/pip'), 'PIP_DISABLE_PIP_VERSION_CHECK':'1',
            'UV_CACHE_DIR':str(artifacts / 'gitlab/cache/uv'),
            'UV_PYTHON_INSTALL_DIR':str(artifacts / 'gitlab/tools/python'),
            'NPM_CONFIG_CACHE':str(artifacts / 'bijux-docs/npm-cache'),
            'XDG_CACHE_HOME':str(artifacts / 'gitlab/cache'),
            'PLAYWRIGHT_BROWSERS_PATH':'/ms-playwright', 'VERIFICATION_MODE':'full',
            'EXPECTED_FRONTEND':'true'}
    # pip explicitly compiles and records bytecode even when imports do not.
    # External cache prefixes would move those declared files outside the owned
    # renderer environment. Contract tests govern their own artifact cache.
    environment.pop('PYTHONPYCACHEPREFIX',None)
    return environment


def operation_environment(operation, environment):
    if operation != 'contracts':
        return environment
    # Contract fixtures establish their own provider contexts. The containing
    # job retains its native identity and credentials outside this test child.
    return {key:value for key,value in environment.items()
            if key not in {'GITLAB_CI','BIJUX_GITLAB_READ_TOKEN','GH_TOKEN'}
            and not key.startswith(('CI_','GITHUB_'))}


def run_command(argv, root, environment, receipt, *, capture=False):
    require(isinstance(argv,list) and bool(argv) and all(isinstance(part,str) and part for part in argv),
            'Source-owned argv command is required')
    section = 'bijux-command-' + str(len(receipt['commands']) + 1)
    started = time.monotonic()
    record = {'argv':argv, 'section':section}
    receipt['commands'].append(record)
    print(f'\x1b[0Ksection_start:{int(time.time())}:{section}\r\x1b[0K' + json.dumps(argv), flush=True)
    try:
        result = subprocess.run(argv, cwd=root, env=environment, text=True,
                                stdout=subprocess.PIPE if capture else None, check=True)
        record['exit_code'] = result.returncode
        return result.stdout if capture else None
    except subprocess.CalledProcessError as error:
        record['exit_code'] = error.returncode
        raise
    except OSError:
        record['status'] = 'could-not-start'
        raise
    finally:
        record['seconds'] = time.monotonic() - started
        print(f'\x1b[0Ksection_end:{int(time.time())}:{section}\r\x1b[0K', flush=True)


def download(url, path, *, maximum):
    require(url.startswith('https://nodejs.org/dist/v' + PIPELINE.NODE_VERSION + '/'),
            'Runtime download must use the exact official Node release')
    request = Request(url, headers={'User-Agent':'bijux-gitlab-runtime'})
    with urlopen(request, timeout=30) as response:
        require(response.status == 200 and response.geturl() == url, 'Runtime transport changed its fixed official URL')
        data = response.read(maximum + 1)
    require(len(data) <= maximum, 'Runtime download exceeds its bounded archive size')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def verify_archive(data, manifest, filename):
    rows = [line.split() for line in manifest.decode('ascii').splitlines()]
    matches = [row[0] for row in rows if len(row) == 2 and row[1] == filename]
    digest = hashlib.sha256(data).hexdigest()
    require(len(matches) == 1 and re.fullmatch(r'[0-9a-f]{64}',matches[0]) is not None
            and matches[0] == digest, 'Official runtime archive SHA256 differs or is unavailable')
    return digest


def bootstrap_node(root, environment, receipt):
    require(platform.system() == 'Linux', 'Hosted runtime bootstrap supports the canonical Linux images only')
    architecture = {'x86_64':'x64', 'aarch64':'arm64'}.get(platform.machine())
    require(architecture is not None, 'Unsupported hosted Node architecture')
    tools = root / 'artifacts/gitlab/tools'
    filename = 'node-v' + PIPELINE.NODE_VERSION + '-linux-' + architecture + '.tar.xz'
    url = 'https://nodejs.org/dist/v' + PIPELINE.NODE_VERSION + '/'
    archive, sums = tools / filename, tools / 'SHASUMS256.txt'
    data = download(url + filename, archive, maximum=128 * 1024 * 1024)
    manifest = download(url + 'SHASUMS256.txt', sums, maximum=1024 * 1024)
    digest = verify_archive(data,manifest,filename)
    destination = tools / 'node'
    require(not destination.exists(), 'Preserve an existing runtime; hosted jobs require a fresh artifact tree')
    destination.mkdir(parents=True)
    run_command(['tar','-xJf',str(archive),'-C',str(destination),'--strip-components=1','--no-same-owner'],
                root,environment,receipt)
    environment['PATH'] = str(destination / 'bin') + os.pathsep + environment.get('PATH','')
    version = run_command([str(destination / 'bin/node'),'--version'],root,environment,receipt,capture=True).strip()
    require(version == 'v' + PIPELINE.NODE_VERSION, 'Installed Node runtime differs from its exact contract')
    receipt.setdefault('runtimes',{})['node'] = {'version':version, 'archive_sha256':digest,
        'archive_url':url + filename, 'manifest_url':url + 'SHASUMS256.txt',
        'executable_sha256':hashlib.sha256((destination / 'bin/node').read_bytes()).hexdigest()}


def bootstrap_uv(root, environment, receipt):
    destination = root / 'artifacts/gitlab/tools/uv'
    require(not destination.exists(), 'Preserve an existing installer runtime')
    run_command(['python3','-m','venv',str(destination)],root,environment,receipt)
    run_command([str(destination / 'bin/python'),'-m','pip','install','--disable-pip-version-check',
                 '--cache-dir',environment['PIP_CACHE_DIR'],'uv==' + PIPELINE.UV_VERSION],root,environment,receipt)
    version = run_command([str(destination / 'bin/uv'),'--version'],root,environment,receipt,capture=True).strip()
    require(version.split()[:2] == ['uv',PIPELINE.UV_VERSION], 'Installed uv differs from the exact contract')
    environment['PATH'] = str(destination / 'bin') + os.pathsep + environment['PATH']
    receipt.setdefault('runtimes',{})['uv'] = {'version':version,
        'executable_sha256':hashlib.sha256((destination / 'bin/uv').read_bytes()).hexdigest()}


def bootstrap_standalone_python(root, environment, receipt):
    bootstrap_uv(root,environment,receipt)
    run_command(['make','ui-test-install-catalogue-interpreter'],root,environment,receipt)
    directory = root / 'artifacts/bijux-docs/catalogue/interpreter'
    python = Path((directory / 'python-path.txt').read_text().strip())
    require(python.is_file() and python.resolve().is_relative_to((root / 'artifacts').resolve()),
            'Standalone recipe interpreter must remain under repository artifacts')
    source = root / 'tests/bijux-docs/catalogue/python_runtime.py'
    recipe = source_module(source,'standalone_python_recipe')
    actual = recipe.observe(python,directory)
    receipt.setdefault('runtimes',{})['standalone_python'] = {
        **actual,'recipe_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'uv_version':PIPELINE.UV_VERSION}
    return python


def bootstrap_contracts_python(root, environment, receipt, standalone_python):
    directory = root / 'artifacts/gitlab/contracts/python'
    run_command(['make','ui-test-install-catalogue','UI_CATALOGUE_BASE_PYTHON='+str(standalone_python),
                 'UI_CATALOGUE_PYTHON_DIR='+str(directory)],root,environment,receipt)
    python = directory / 'bin/python'
    require(python.is_file() and python.resolve().is_relative_to((root / 'artifacts').resolve()),
            'Contract interpreter must belong to its artifact-owned standalone recipe')
    code = ('import inspect,json,sys,tarfile,yaml; print(json.dumps(dict(version=list(sys.version_info[:3]), '
            'implementation=sys.implementation.name, executable=sys.executable, prefix=sys.prefix, '
            'base_prefix=sys.base_prefix, yaml_version=yaml.__version__, yaml_file=yaml.__file__, '
            'data_filter=callable(getattr(tarfile,"data_filter",None)) and '
            '"filter" in inspect.signature(tarfile.TarFile.extractall).parameters)))')
    actual = json.loads(run_command([str(python),'-B','-I','-c',code],root,environment,receipt,capture=True))
    require(actual.get('version') == [3,14,4] and actual.get('implementation') == 'cpython'
            and actual.get('data_filter') is True,
            'Contract tests require exact CPython 3.14.4 with the safe tar data filter')
    require(Path(actual['executable']).absolute() == python.absolute()
            and Path(actual['prefix']).resolve() == directory.resolve()
            and Path(actual['base_prefix']).resolve() == Path(receipt['runtimes']['standalone_python']['prefix']).resolve()
            and Path(actual['base_prefix']).resolve() != directory.resolve()
            and Path(actual['yaml_file']).resolve().is_relative_to(directory.resolve()),
            'Contract Python or PyYAML escaped its owned verification environment')
    receipt['runtimes']['contracts_python'] = {**actual,
        'resolved_executable':str(python.resolve()),
        'executable_sha256':hashlib.sha256(python.resolve().read_bytes()).hexdigest(),
        'lock_sha256':hashlib.sha256((root / 'tests/bijux-docs/catalogue/requirements.lock.txt').read_bytes()).hexdigest()}
    environment['PATH'] = str(python.parent) + os.pathsep + environment['PATH']
    return python


def operation_commands(root, contract, *, catalogue_python=None, job_id=None):
    operation, args = contract['operation'], contract['args']
    python = ['python3','-B']
    docs = 'tests/bijux-docs/'
    execution = docs + 'execution/'
    renderer_python = 'artifacts/bijux-docs/python/bin/python'
    if operation == 'plan':
        return [python + [execution + 'input_planning/cli.py','plan']]
    if operation == 'standard':
        return [['ruby','-ryaml','-rjson','-e',
                 'abort "Ruby 3.3.12 required" unless RUBY_VERSION == "3.3.12"; abort "Psych structural parser required" unless YAML.respond_to?(:parse_stream) && YAML.respond_to?(:safe_load); puts JSON.generate({ruby: RUBY_VERSION, psych: Psych::VERSION})'],
                ['sha256sum','--check','.github/bijux-std-shared.sha256'],
                python + ['.github/scripts/check_pinned_actions.py','--manifest-managed',
                          '.github/standards/repo-config.manifest.json','.github/workflows'],
                ['make','bijux-std-checks'], python + ['shared/bijux-gitlab/pipeline.py','--check']]
    if operation == 'contracts':
        require(isinstance(args, list) and len(args) == 1 and type(args[0]) is int
                and 0 <= args[0] < PIPELINE.CONTRACT_PARTITION_COUNT,
                'Contract operation requires its source-owned partition index')
        require(isinstance(job_id, str) and re.fullmatch(r'[1-9][0-9]*', job_id),
                'Contract artifacts require the validated native job ID')
        return [['make', 'contract-tests' if args[0] == 0 else 'contract-unit-tests',
                 'CONTRACT_UNIT_PARTITION=' + str(args[0]),
                 'CONTRACT_UNIT_PARTITION_COUNT=' + str(PIPELINE.CONTRACT_PARTITION_COUNT),
                 'CONTRACT_ARTIFACT_ROOT=artifacts/gitlab/jobs/' + job_id + '/contracts']]
    if operation == 'policy':
        return [python + ['shared/bijux-gitlab/policy.py']]
    if operation == 'catalogue':
        require(catalogue_python is not None, 'Catalogue commands require the owned CPython recipe')
        base = 'UI_CATALOGUE_BASE_PYTHON=' + str(catalogue_python)
        commands = [['make','ui-test-install-catalogue',base]]
        if args == ['tracked-entrypoint']:
            commands.append(['make','ui-test-install-catalogue-default',base])
        return commands + [['make','ui-test-catalogue','UI_CATALOGUE_GROUP=' + args[0]]]
    if operation == 'commands':
        return [['make','ui-test-install-docs'], python + [execution + 'publication_gate.py','run',
                '--python',renderer_python,'--output','artifacts/bijux-docs/publication-commands']]
    if operation == 'renderer':
        return [['make','ui-test-install','ui-test-install-docs'], python + [execution + 'renderer_controls.py',
                'run','--python',renderer_python,'--node',str(root / 'artifacts/gitlab/tools/node/bin/node'),
                '--group',args[0],'--output','artifacts/bijux-docs/renderer-controls/' + args[0]]]
    if operation == 'fixtures':
        return [['make','ui-test-install','ui-test-install-docs','ui-test-fixtures'],
                [renderer_python,'-B','shared/bijux-docs/tooling/security/renderer_fingerprints.py',
                 '--output','artifacts/bijux-docs/renderer-source-observation.json'],
                [renderer_python,'-B',docs + 'generated/build.py','--output','artifacts/bijux-docs/contrast-generated',
                 '--base-url','http://127.0.0.1:62599'], python + [execution + 'browser_gate.py','prepare']]
    if operation == 'browser':
        return [python + [execution + 'browser_gate.py','run','--batch',args[0],'--engine',args[1]]]
    if operation == 'persisted':
        return [python + [execution + 'persisted_reader.py','run']]
    if operation == 'browser-faults':
        return [python + [execution + 'frontend_faults.py','browser','--engine',args[0]]]
    if operation == 'public-faults':
        return [['make','ui-test-install-docs'], python + [execution + 'frontend_faults.py',
                'public','--python',renderer_python]]
    if operation in {'navigation','report'}:
        return [python + [execution + 'frontend_faults.py','aggregate'],
                python + [execution + 'browser_gate.py','aggregate'],
                python + [execution + 'renderer_controls.py','verify','--output','artifacts/bijux-docs/renderer-controls'],
                python + [execution + 'input_planning/cli.py','verify']] + (
                    [['bash','shared/bijux-checks/scripts/run-bijux-check-suite.sh',
                      '--consumer','.bijux/checks.consumer.json','--artifacts-dir','artifacts/bijux-checks']]
                    if operation == 'report' else [])
    raise ValueError('Unsupported native GitLab operation: ' + str(operation))


def result_flags(root, admission, excluded):
    contracts = PIPELINE.job_contracts(root)
    expected = {name for name,row in contracts.items() if row['operation'] not in excluded}
    selected = admission.get('selected_jobs',{})
    require(admission.get('status') == 'passed' and set(selected) == expected,
            'Complete admitted native prerequisite jobs are required')
    for name, selected_job in selected.items():
        raw = selected_job.get('raw_job',{})
        require(type(selected_job.get('job_id')) is int and selected_job['job_id'] > 0
                and raw.get('id') == selected_job['job_id'] and raw.get('status') == 'success'
                and raw.get('allow_failure') is False, 'Native prerequisite is not actual terminal success: ' + name)
    mapping = {'PLAN_RESULT':{'plan'}, 'CHECK_RESULT':{'standard','contracts'},
               'FIXTURE_RESULT':{'fixtures'}, 'BROWSER_RESULT':{'browser'}, 'COMMAND_RESULT':{'commands'},
               'RENDERER_RESULT':{'renderer'}, 'CATALOGUE_RESULT':{'catalogue'}, 'PERSISTED_RESULT':{'persisted'},
               'FAULT_BROWSER_RESULT':{'browser-faults'}, 'FAULT_PUBLIC_RESULT':{'public-faults'}}
    for variable, operations in mapping.items():
        require(any(contracts[name]['operation'] in operations for name in selected),
                'Missing actual prerequisite owner for ' + variable)
    return {**{name:'success' for name in mapping}, 'EXPECTED_FRONTEND':'true', 'VERIFICATION_MODE':'full'}


def validate_context(root, job, environment):
    identity = CI.execution_identity()
    require(identity['server_url'] == 'https://gitlab.com' and identity['project_id'] == '88948041'
            and identity['project_path'] == 'bijux-oss/bijux-std', 'Canonical native standards project is required')
    require(environment.get('GITLAB_CI') == 'true' and environment.get('CI_JOB_NAME') == job
            and environment.get('CI_PROJECT_DIR') == str(root.resolve()),
            'Actual canonical native physical job name is required')
    head = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    require(head == identity['commit_sha'], 'Native checkout differs from the exact job source')
    require(environment.get('VERIFICATION_MODE','full') == 'full',
            'Unsupported retained/manual observation mode; full fresh validation is required')
    require(environment.get('CI_PIPELINE_SOURCE') in {'push','merge_request_event','web','schedule'},
            'Unsupported native pipeline source')
    require(environment.get('CI_COMMIT_REF_PROTECTED') in {'true','false'}
            and bool(environment.get('CI_COMMIT_REF_NAME')), 'Actual ref/protection identity is required')
    return identity


def contract_coverage(root, identity, admission):
    """Bind the complete unit union to independently admitted physical owners."""
    root = Path(root).resolve()
    identity = CI.validate(identity)
    require(admission.get('status') == 'passed'
            and admission.get('project_id') == int(identity['project_id'])
            and admission.get('pipeline_id') == int(identity['pipeline_id'])
            and admission.get('commit_sha') == identity['commit_sha'],
            'Contract coverage requires admitted native project, pipeline and source')
    runner = source_module(Path(__file__).with_name('contracts.py'), 'contract_coverage')
    require(runner.PARTITION_COUNT == PIPELINE.CONTRACT_PARTITION_COUNT,
            'Contract partition declarations disagree')
    require(runner.source_head(root) == identity['commit_sha'],
            'Contract coverage checkout differs from its native source')
    contracts = {name: row for name, row in PIPELINE.job_contracts(root).items() if row['operation'] == 'contracts'}
    require(len(contracts) == PIPELINE.CONTRACT_PARTITION_COUNT
            and all(isinstance(row.get('args'), list) and len(row['args']) == 1 and type(row['args'][0]) is int
                    for row in contracts.values())
            and {row['args'][0] for row in contracts.values()} == set(range(PIPELINE.CONTRACT_PARTITION_COUNT)),
            'Every source-owned contract partition is required exactly once')
    jobs = source_module(Path(__file__).with_name('evidence') / 'jobs.py', 'contract_owners')
    selected = admission.get('selected_jobs', {})
    artifacts = admission.get('artifacts', {})
    union_hashes = admission.get('files_sha256', {})
    require(isinstance(selected, dict) and isinstance(artifacts, dict) and isinstance(union_hashes, dict),
            'Contract coverage requires independently admitted artifact hashes')
    receipts, owners, seen = [], [], set()
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate contract receipt JSON key')
            result[key] = value
        return result
    for name, contract in contracts.items():
        record = selected.get(name, {})
        job_id = record.get('job_id')
        require(type(job_id) is int and job_id > 0 and job_id not in seen,
                'Distinct actual contract executor IDs are required')
        seen.add(job_id)
        raw = jobs.validate_identity(record.get('raw_job'), project_id=int(identity['project_id']),
            pipeline_id=int(identity['pipeline_id']), commit_sha=identity['commit_sha'])
        require(raw['id'] == job_id and raw['name'] == name and raw.get('status') == 'success'
                and raw.get('allow_failure') is False, 'Contract executor does not match its successful physical owner')
        relative = f'artifacts/gitlab/jobs/{job_id}/contracts/unit-results.json'
        path = root / relative
        require(not any(parent.is_symlink() for parent in (path, *path.parents))
                and path.is_file() and path.stat().st_nlink == 1 and 0 < path.stat().st_size <= 16 * 1024 * 1024,
                'Actual bounded contract partition receipt is missing or aliased')
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        artifact = artifacts.get(name, {})
        require(isinstance(artifact, dict) and artifact.get('job_id') == job_id
                and isinstance(artifact.get('files_sha256'), dict)
                and artifact['files_sha256'].get(relative) == digest and union_hashes.get(relative) == digest,
                'Contract receipt bytes differ from the admitted native artifact owner')
        try:
            receipt = json.loads(body, object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise ValueError('Contract partition receipt JSON is invalid') from None
        require(isinstance(receipt, dict) and receipt.get('partition_index') == contract['args'][0],
                'Contract receipt partition differs from its source-owned physical executor')
        receipts.append(receipt)
        owners.append({'partition_index': contract['args'][0], 'job_name': name, 'job_id': job_id,
                       'receipt_path': relative, 'receipt_sha256': digest})
    coverage = runner.verify_coverage(receipts, identity['commit_sha'], expected_partitions=PIPELINE.CONTRACT_PARTITION_COUNT)
    coverage.update(provider='gitlab', server_url=identity['server_url'], project_id=int(identity['project_id']),
                    project_path=identity['project_path'], pipeline_id=int(identity['pipeline_id']),
                    native_owners=sorted(owners, key=lambda row: row['partition_index']))
    return coverage


def acceptance_record(root, identity, environment, admission):
    identity = CI.validate(identity)
    require(identity['server_url'] == 'https://gitlab.com' and identity['project_id'] == '88948041'
            and identity['project_path'] == 'bijux-oss/bijux-std', 'Acceptance requires the canonical native project')
    require(admission.get('project_id') == int(identity['project_id'])
            and admission.get('pipeline_id') == int(identity['pipeline_id'])
            and admission.get('commit_sha') == identity['commit_sha'],
            'Admitted prerequisites do not bind the acceptance project, pipeline and source')
    result_flags(root,admission,{'report'})
    jobs = source_module(Path(__file__).with_name('evidence') / 'jobs.py','acceptance_jobs')
    for row in admission['selected_jobs'].values():
        jobs.validate_identity(row['raw_job'],project_id=int(identity['project_id']),
                               pipeline_id=int(identity['pipeline_id']),commit_sha=identity['commit_sha'])
    require(environment.get('CI_COMMIT_REF_PROTECTED') in {'true','false'}
            and bool(environment.get('CI_COMMIT_REF_NAME'))
            and environment.get('CI_PIPELINE_SOURCE') in {'push','merge_request_event','web','schedule'},
            'Acceptance requires the actual native source event and ref protection')
    return {'schema_version':1, 'server_url':identity['server_url'],
            'project_id':int(identity['project_id']), 'project_path':identity['project_path'],
            'commit_sha':identity['commit_sha'], 'pipeline_id':int(identity['pipeline_id']),
            'pipeline_source':environment['CI_PIPELINE_SOURCE'], 'ref':environment['CI_COMMIT_REF_NAME'],
            'ref_protected':environment['CI_COMMIT_REF_PROTECTED'] == 'true',
            'validation':{'status':'passed','jobs':admission['selected_jobs'],
                          'contract_coverage':contract_coverage(root,identity,admission)},
            'publication':{'status':'pending'}}


def execute_job(root, job):
    contracts = PIPELINE.job_contracts(root)
    require(job in contracts, 'Unsupported physical GitLab job')
    original = dict(os.environ)
    identity = validate_context(root,job,original)
    environment = runtime_environment(root,original)
    folder = root / 'artifacts/gitlab/jobs' / identity['job_id']
    require(not folder.is_symlink(), 'Job runtime receipts must use ordinary artifact directories')
    folder.mkdir(parents=True,exist_ok=True)
    receipt = {'schema_version':1, 'status':'running', 'job':job, 'ci_context':identity, 'commands':[],
               'runtimes':{'python':{'version':sys.version.split()[0], 'executable':sys.executable,
                   'executable_sha256':hashlib.sha256(Path(sys.executable).resolve().read_bytes()).hexdigest()}},
               'publication_authorization':False}
    target = folder / 'runtime.json'
    require(not target.exists() and not target.is_symlink(), 'Preserve an existing native job runtime receipt')
    def retain():
        target.write_text(json.dumps(receipt,indent=2) + '\n')
    retain()
    try:
        run_command(['git','remote','set-url','origin','https://gitlab.com/bijux-oss/bijux-std.git'],root,environment,receipt)
        operation = contracts[job]['operation']
        environment['EXPECTED_BASELINE'] = identity['commit_sha']
        environment['BIJUX_CI_OUTPUT'] = str(folder / 'input-selection.env')
        if operation not in {'standard','plan','policy'}:
            bootstrap_node(root,environment,receipt)
        catalogue_python = None
        if operation in {'catalogue','contracts'}:
            catalogue_python = bootstrap_standalone_python(root,environment,receipt)
            if operation == 'contracts':
                bootstrap_contracts_python(root,environment,receipt,catalogue_python)
        admission = None
        if operation in {'navigation','report'}:
            excluded = {'navigation','report'} if operation == 'navigation' else {'report'}
            collector = source_module(Path(__file__).with_name('evidence') / 'collect.py','collector')
            admission = collector.collect(root,exclude_operations=excluded)
            environment.update(result_flags(root,admission,excluded))
            receipt['admitted_jobs'] = {name:row['job_id'] for name,row in admission['selected_jobs'].items()}
            if operation == 'report':
                coverage = contract_coverage(root,identity,admission)
                with (folder / 'contract-coverage.json').open('x') as stream:
                    stream.write(json.dumps(coverage,indent=2) + '\n')
        for argv in operation_commands(root,contracts[job],catalogue_python=catalogue_python,job_id=identity['job_id']):
            run_command(argv,root,operation_environment(operation,environment),receipt)
            retain()
        if operation == 'report':
            acceptance = acceptance_record(root,identity,environment,admission)
            output = root / 'artifacts/gitlab/acceptance'
            output.mkdir(parents=True,exist_ok=True)
            (output / 'acceptance.json').write_text(json.dumps(acceptance,indent=2) + '\n')
            (output / 'contract-coverage.json').write_text(json.dumps(acceptance['validation']['contract_coverage'],indent=2) + '\n')
        receipt['status'] = 'passed'
    except BaseException as error:
        receipt.update(status='failed',error_type=type(error).__name__)
        raise
    finally:
        retain()
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job',required=True)
    args = parser.parse_args()
    try:
        execute_job(ROOT,args.job)
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        print('Native GitLab execution failed:',error,file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
