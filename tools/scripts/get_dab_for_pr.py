#!/usr/bin/env python3
import os
import re

import requests

pr_body = os.environ.get('PR_BODY', '')

print(f"Scanning {pr_body}")

requires_re = re.compile('requires.*ansible/django-ansible-base(?:#|/pull/)([0-9]+)', re.IGNORECASE)

matches = requires_re.search(pr_body)
if matches:
    required_pr = matches.group(1)
    print(f"This PR requires DAB PR {required_pr}")
    url = f'https://api.github.com/repos/ansible/django-ansible-base/pulls/{required_pr}'
    headers = {}
    if os.environ.get('GH_TOKEN', None):
        headers['Authorization'] = f"Bearer {os.environ.get('GH_TOKEN')}"
    response = requests.get(url)
    pr_data = response.json()
    repo_url = pr_data['head']['repo']['html_url']
    branch = pr_data['head']['ref']
    merged = pr_data['merged']
    if not merged:
        print(f"Checking out {branch} from {repo_url}")
        os.system(f'git clone {repo_url} -b {branch} --depth=1')
    else:
        print(f"The referenced PR {required_pr} has been merged already, no need to check out the branch")
else:
    print("PR body does not match")
