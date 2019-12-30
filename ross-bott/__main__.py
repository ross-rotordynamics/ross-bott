"""Script to look for stale issues and require some action from the team.
"""
import os
import time
import schedule
from github import Github as gh
from datetime import datetime


token = os.environ.get("GH_AUTH")
g = gh(token)
ross_repo = g.get_repo('ross-rotordynamics/ross')


def mark_stale_issues():
    # days limit for staled issues
    LIMIT = 45

    issues = ross_repo.get_issues(state='open')
    not_updated_issues = []
    for issue in issues:
        if issue.title == 'ross-bott-tests':
            not_updated_issues.append(issue)
        # last_update = (datetime.today() - issue.update_at).days
        # if last_update > LIMIT:
        #     not_updated_issues.append(issue)

    # fmt: off
    stale_message = (
        f'Hi there!\n'
        f'I have marked this issue as stale because it has not had activity for {LIMIT} days.\n'
        f'Consider the following options:\n'
        f'- If the issue refers to a large task, break it in smaller issues that can be solved in\n'
        f'less than {LIMIT} days;\n'
        f'- Label the issue as `wontfix` or `wontfix for now` and close it.'
    )
    # fmt: on

    for issue in not_updated_issues:
        issue.create_comment(stale_message)


if __name__ == '__main__':
    while True:
        mark_stale_issues()
        time.sleep(60)
    # schedule.every().day.at("01:00").do(mark_stale_issues)
    #
    # while True:
    #     schedule.run_pending()
    #     time.sleep(60)
