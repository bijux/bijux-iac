"""Run deterministic complete-discovery contract partitions and qualify their union."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
PARTITION_COUNT=6
MAX_CASES=100000


def require(condition,message):
    if not condition:raise ValueError(message)


def partition_number(index,count):
    require(type(count) is int and 1<=count<=64,'A bounded positive contract partition count is required')
    require(type(index) is int and 0<=index<count,'Contract partition index is outside its complete partition set')


def assigned_partition(case_id,partition_count=PARTITION_COUNT):
    partition_number(0,partition_count)
    require(isinstance(case_id,str) and 0<len(case_id)<=4096 and '\x00' not in case_id,'Complete unittest case identifier is required')
    return int.from_bytes(hashlib.sha256(case_id.encode('utf-8')).digest(),'big')%partition_count


def universe_digest(identifiers):
    return hashlib.sha256(json.dumps(identifiers,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def source_head(root):
    git=lambda *args:subprocess.check_output(['git',*args],cwd=root,text=True).strip()
    require(Path(git('rev-parse','--show-toplevel')).resolve()==root,'Contract discovery must run from its actual repository root')
    head=git('rev-parse','HEAD')
    require(re.fullmatch(r'[a-f0-9]{40}',head),'Actual immutable contract source commit is required')
    require(not git('status','--porcelain','--untracked-files=normal'),'Contract source differs from its clean immutable checkout')
    return head


def flatten(suite):
    for value in suite:
        if isinstance(value,unittest.TestSuite):yield from flatten(value)
        else:
            require(isinstance(value,unittest.TestCase),'Discovery returned a non-case unittest execution')
            yield value


class CaseResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.case_results=[]
        self._active={}

    def startTest(self,test):
        super().startTest(test)
        row={'id':test.id(),'status':'running'}
        self.case_results.append(row);self._active[id(test)]=row

    def mark(self,test,status):
        if id(test) in self._active:self._active[id(test)]['status']=status

    def addSuccess(self,test):
        self.mark(test,'passed');super().addSuccess(test)

    def addFailure(self,test,error):
        self.mark(test,'failed');super().addFailure(test,error)

    def addError(self,test,error):
        self.mark(test,'error');super().addError(test,error)

    def addSkip(self,test,reason):
        self.mark(test,'skipped');super().addSkip(test,reason)

    def addExpectedFailure(self,test,error):
        self.mark(test,'expected_failure');super().addExpectedFailure(test,error)
        if self.failfast:self.stop()

    def addUnexpectedSuccess(self,test):
        self.mark(test,'unexpected_success');super().addUnexpectedSuccess(test)

    def addSubTest(self,test,subtest,error):
        if error is not None:self.mark(test,'failed' if issubclass(error[0],test.failureException) else 'error')
        super().addSubTest(test,subtest,error)


def run_partition(root,*,partition_index,partition_count=PARTITION_COUNT,stream=None):
    partition_number(partition_index,partition_count)
    root=Path(root).resolve();head=source_head(root)
    receipt={'schema_version':1,'status':'failed','source_head':head,'partition_count':partition_count,
        'partition_index':partition_index,'universe_ids':[],'universe_sha256':universe_digest([]),
        'expected_ids':[],'executed_ids':[],'case_results':[],'failures':[],'errors':[],'skips':[],
        'expected_failures':[],'unexpected_successes':[],'discovery_errors':[],
        'limits':['Provider job, artifact and runtime provenance belong to the containing native job.']}
    previous_path=list(sys.path);previous_directory=Path.cwd()
    try:
        os.chdir(root)
        sys.path[:0]=[str(root),str(root/'tests')]
        loader=unittest.TestLoader()
        try:
            cases=list(flatten(loader.discover(start_dir=str(root/'tests'),pattern='test_*.py')))
        except (Exception,SystemExit) as error:
            receipt['discovery_errors']=[type(error).__name__+': '+str(error)]
            return receipt
        identifiers=[case.id() for case in cases]
        receipt['universe_ids']=identifiers;receipt['universe_sha256']=universe_digest(identifiers)
        receipt['discovery_errors']=list(loader.errors)
        if not identifiers or len(identifiers)>MAX_CASES:
            receipt['discovery_errors'].append('Complete bounded nonempty unittest universe is required')
        if len(set(identifiers))!=len(identifiers):
            receipt['discovery_errors'].append('Duplicate unittest case identifiers in complete discovery')
        if receipt['discovery_errors']:return receipt
        selected=[case for case in cases if assigned_partition(case.id(),partition_count)==partition_index]
        receipt['expected_ids']=[case.id() for case in selected]
        # Keeping discovery order preserves unittest's module/class fixture lifecycle.
        result=unittest.TextTestRunner(stream=stream or sys.stderr,verbosity=2,failfast=True,resultclass=CaseResult).run(unittest.TestSuite(selected))
        receipt['case_results']=result.case_results
        receipt['executed_ids']=[row['id'] for row in result.case_results]
        for key in ('failures','errors','expected_failures'):
            values=getattr(result,'expectedFailures' if key=='expected_failures' else key)
            receipt[key]=[{'id':case.id(),'detail':detail} for case,detail in values]
        receipt['skips']=[{'id':case.id(),'reason':reason} for case,reason in result.skipped]
        receipt['unexpected_successes']=[case.id() for case in result.unexpectedSuccesses]
        if (not any(receipt[key] for key in ('failures','errors','skips','expected_failures','unexpected_successes'))
                and receipt['executed_ids']==receipt['expected_ids']
                and all(row['status']=='passed' for row in result.case_results)):
            receipt['status']='passed'
        require(source_head(root)==head,'Contract source changed during partition execution')
    finally:
        sys.path[:]=previous_path;os.chdir(previous_directory)
    return receipt


def verify_coverage(receipts,expected_source,expected_partitions=PARTITION_COUNT):
    partition_number(0,expected_partitions)
    require(isinstance(expected_source,str) and re.fullmatch(r'[a-f0-9]{40}',expected_source),'Expected immutable contract source commit is required')
    require(isinstance(receipts,list) and len(receipts)==expected_partitions,'Every contract partition receipt is required exactly once')
    require(all(isinstance(row,dict) for row in receipts),'Native contract receipts must be objects')
    universe=receipts[0].get('universe_ids')
    require(isinstance(universe,list) and 0<len(universe)<=MAX_CASES,'Complete bounded unittest universe is required')
    require(all(isinstance(name,str) and name for name in universe) and len(set(universe))==len(universe),'Duplicate or malformed unittest universe')
    digest=universe_digest(universe);seen_indices=set();executed=[];partitions=[]
    for receipt in receipts:
        require(type(receipt.get('schema_version')) is int and receipt['schema_version']==1
                and receipt.get('status')=='passed','Contract partition did not qualify')
        index,count=receipt.get('partition_index'),receipt.get('partition_count')
        partition_number(index,count)
        require(count==expected_partitions and index not in seen_indices,'Missing duplicate or inconsistent contract partition')
        seen_indices.add(index)
        require(receipt.get('source_head')==expected_source and receipt.get('universe_ids')==universe
                and receipt.get('universe_sha256')==digest,'Contract partition source or complete universe differs')
        require(all(receipt.get(key)==[] for key in ('failures','errors','skips','expected_failures','unexpected_successes','discovery_errors')),
                'Failed errored skipped or incomplete discovery cannot qualify contract coverage')
        expected=[name for name in universe if assigned_partition(name,count)==index]
        require(receipt.get('expected_ids')==expected and receipt.get('executed_ids')==expected,'Contract execution differs from its complete assigned case set')
        results=receipt.get('case_results')
        require(isinstance(results,list) and len(results)==len(expected)
                and all(isinstance(row,dict) for row in results)
                and [row.get('id') for row in results]==expected
                and all(row.get('status')=='passed' for row in results),'Every assigned contract case must actually pass')
        executed.extend(expected)
        partitions.append({'partition_index':index,'expected_cases':len(expected),'executed_cases':len(results)})
    require(seen_indices==set(range(expected_partitions)) and len(executed)==len(universe)
            and len(set(executed))==len(executed) and set(executed)==set(universe),'Contract partition union is not exact disjoint complete coverage')
    return {'schema_version':1,'status':'passed','source_head':expected_source,'partition_count':expected_partitions,
        'universe_ids':list(universe),'universe_sha256':digest,'expected_cases':len(universe),'executed_cases':len(executed),
        'partitions':sorted(partitions,key=lambda row:row['partition_index'])}


def artifact_output(path,root):
    root=Path(root).resolve();path=Path(path).absolute()
    require(not any(parent.is_symlink() for parent in (path,*path.parents)),
            'Contract output must use ordinary non-symlink artifact paths')
    resolved=path.resolve()
    require(resolved.is_relative_to(root/'artifacts') and resolved!=root/'artifacts',
            'Contract output must remain under its repository artifacts directory')
    require(not path.exists(),'Preserve existing contract partition evidence')
    return path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subparsers=parser.add_subparsers(dest='operation',required=True)
    run=subparsers.add_parser('run')
    run.add_argument('--root',type=Path,default=ROOT)
    run.add_argument('--partition-index',type=int,required=True)
    run.add_argument('--partition-count',type=int,default=PARTITION_COUNT)
    run.add_argument('--output',type=Path,required=True)
    verify=subparsers.add_parser('verify')
    verify.add_argument('--source',required=True)
    verify.add_argument('--receipt',type=Path,action='append',required=True)
    verify.add_argument('--partition-count',type=int,default=PARTITION_COUNT)
    verify.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    owner=args.root if args.operation=='run' else ROOT
    try:
        output=artifact_output(args.output,owner)
    except (ValueError,OSError) as error:
        print('Contract output rejected:',error,file=sys.stderr)
        return 1
    try:
        if args.operation=='run':
            receipt=run_partition(args.root,partition_index=args.partition_index,partition_count=args.partition_count)
        else:
            receipt=verify_coverage([json.loads(path.read_bytes()) for path in args.receipt],args.source,args.partition_count)
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        receipt={'schema_version':1,'status':'failed','error':str(error)}
    artifact_output(output,owner)
    output.parent.mkdir(parents=True,exist_ok=True)
    artifact_output(output,owner)
    with output.open('x') as stream:stream.write(json.dumps(receipt,indent=2)+'\n')
    return 0 if receipt['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
