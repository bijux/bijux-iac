"""Read canonical native GitLab review state without granting publication rights."""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROJECT_ID = 88948041
PROJECT_PATH = 'bijux-oss/bijux-std'
PREFIX = '/projects/' + str(PROJECT_ID)


def require(condition, message):
    if not condition:
        raise ValueError(message)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_read(path):
    """Finite public review endpoints; ambient session and CI tokens are unused."""
    pattern = re.escape(PREFIX) + r'(?:/merge_requests/[1-9][0-9]*(?:/approvals)?|/repository/commits/[a-f0-9]{40}/merge_requests\?per_page=100)'
    require(isinstance(path, str) and re.fullmatch(pattern, path), 'Unsupported native policy API path')
    request = Request('https://gitlab.com/api/v4' + path,
                      headers={'Accept':'application/json', 'Cache-Control':'no-cache',
                               'User-Agent':'bijux-canonical-review'}, method='GET')
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            require(response.status == 200, 'Native review metadata is unavailable')
            require(response.headers.get('X-Next-Page', '') == '', 'Review inventory is incomplete')
            body = response.read(4 * 1024 * 1024 + 1)
            require(len(body) <= 4 * 1024 * 1024, 'Native review metadata exceeds its bound')
    except (HTTPError, URLError, OSError) as error:
        raise ValueError('Public native review metadata is unavailable; review admission is blocked') from error
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate native review key')
            result[key] = value
        return result
    return json.loads(body, object_pairs_hook=unique)


def check_mr(mr, *, iid, state, head):
    require(isinstance(mr, dict) and type(mr.get('iid')) is int and mr['iid'] == iid
            and type(mr.get('target_project_id')) is int and mr['target_project_id'] == PROJECT_ID
            and mr.get('target_branch') == 'main' and mr.get('state') == state,
            'Native merge request identity, target or state differs')
    require(mr.get('sha') == head and isinstance(mr.get('diff_refs'), dict)
            and mr['diff_refs'].get('head_sha') == head,
            'Native merge request head differs from the reviewed source')
    require(mr.get('draft') is False and mr.get('work_in_progress', False) is False,
            'Draft merge requests cannot establish accepted review')
    require(isinstance(mr.get('author'), dict) and isinstance(mr['author'].get('username'), str)
            and bool(mr['author']['username']) and isinstance(mr.get('labels'), list)
            and all(isinstance(value, str) for value in mr['labels']), 'Native review author/labels are missing')


def validate_review(environment, read=public_read):
    require(environment.get('CI_SERVER_URL') == 'https://gitlab.com'
            and environment.get('CI_PROJECT_ID') == str(PROJECT_ID)
            and environment.get('CI_PROJECT_PATH') == PROJECT_PATH,
            'Canonical native policy project identity is required')
    sha = environment.get('CI_COMMIT_SHA', '')
    require(re.fullmatch(r'[a-f0-9]{40}', sha) is not None, 'Native policy requires an immutable checkout')
    require(environment.get('CI_DEFAULT_BRANCH') == 'main', 'Canonical default branch must be main')
    require(not environment.get('CI_COMMIT_TAG'), 'Unsupported manual release/tag authorization; validation never releases')
    source = environment.get('CI_PIPELINE_SOURCE')
    require(source in {'push','merge_request_event','web','schedule'}, 'Unsupported native review event')
    result = {'schema_version':1, 'status':'passed', 'project_id':PROJECT_ID, 'commit_sha':sha,
              'publication_authorization':False}
    accepted = source != 'merge_request_event' and environment.get('CI_COMMIT_BRANCH') == 'main'
    if source != 'merge_request_event' and not accepted:
        require(source == 'push' and bool(environment.get('CI_COMMIT_BRANCH')),
                'Unsupported manual or scheduled review context')
        return {**result, 'scope':'branch-validation', 'review':'not-claimed'}
    if accepted:
        require(environment.get('CI_COMMIT_REF_PROTECTED') == 'true', 'Accepted main must be a protected native ref')
        rows = read(PREFIX + '/repository/commits/' + sha + '/merge_requests?per_page=100')
        require(isinstance(rows, list) and len(rows) < 100 and all(isinstance(row,dict) for row in rows),
                'Complete native merged-request inventory is required')
        matches = [row for row in rows if row.get('state') == 'merged' and row.get('merge_commit_sha') == sha]
        require(len(matches) == 1, 'Accepted main must bind exactly one actual merged merge request')
        iid = matches[0].get('iid')
    else:
        value = environment.get('CI_MERGE_REQUEST_IID', '')
        require(re.fullmatch(r'[1-9][0-9]*', value) is not None, 'Actual native merge request IID is required')
        iid = int(value)
    require(type(iid) is int and iid > 0, 'Actual native merge request identity is required')
    endpoint = PREFIX + '/merge_requests/' + str(iid)
    mr = read(endpoint)
    head = mr.get('sha') if accepted and isinstance(mr,dict) else sha
    require(isinstance(head,str) and re.fullmatch(r'[a-f0-9]{40}',head), 'Actual native review head is required')
    state = 'merged' if accepted else 'opened'
    check_mr(mr, iid=iid, state=state, head=head)
    if accepted:
        require(mr.get('merge_commit_sha') == sha, 'Native merged request does not bind accepted main')
    owner_authored = mr['author']['username'] == 'bijux'
    if owner_authored:
        require('owner-self-signoff' in mr['labels'], 'Owner-authored merge request requires owner-self-signoff')
        review = 'owner-self-signoff'
    else:
        approvals = read(endpoint + '/approvals')
        require(isinstance(approvals,dict) and isinstance(approvals.get('approved_by'),list)
                and all(isinstance(row,dict) and isinstance(row.get('user'),dict) for row in approvals['approved_by'])
                and any(row['user'].get('username') == 'bijux' for row in approvals['approved_by']),
                'Non-owner merge request requires actual native owner approval')
        require(approvals.get('sha',head) == head, 'Native approval state differs from reviewed head')
        review = 'owner-approved'
    current = read(endpoint)
    check_mr(current, iid=iid, state=state, head=head)
    require(current['author'] == mr['author'] and (not accepted or current.get('merge_commit_sha') == sha)
            and (not owner_authored or 'owner-self-signoff' in current['labels']),
            'Native review changed while admission was collected')
    return {**result, 'scope':'accepted-main-review' if accepted else 'merge-request-review',
            'merge_request_iid':iid, 'review_head':head, 'review':review}


def main():
    import os
    from pathlib import Path
    import sys
    try:
        identifier = os.environ.get('CI_JOB_ID','')
        require(re.fullmatch(r'[1-9][0-9]*',identifier), 'Actual native job ID is required for policy evidence')
        receipt = validate_review(dict(os.environ))
        output = Path(__file__).resolve().parents[2] / 'artifacts/gitlab/jobs' / identifier
        output.mkdir(parents=True,exist_ok=True)
        (output / 'policy.json').write_text(json.dumps(receipt,indent=2) + '\n')
    except (ValueError,OSError) as error:
        print('Native canonical review is blocked:',error,file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
