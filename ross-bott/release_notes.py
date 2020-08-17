"""Script to generate release notes for ROSS.

This script uses PyGithub to access the projects PRs and produce the release
notes based on the PR body text.
The texts are converted from md (used on github) to rst (with m2r), so that
any image or code block is displayed in the release notes.

Usage:
$ python release_notes.py
$ Version number x.x.x: 0.2.0
$ Start date YYYY-MM-DD: 2019-06-06
$ End date YYYY-MM-DD: 2019-11-29
"""
import click
import m2r
from pathlib import Path
from github import Github as gh
from datetime import datetime


def has_milestone(pr, milestone):
    # if milestone is not given return True
    if milestone is None:
        return True
    else:
        if pr.milestone is not None:
            if pr.milestone.title == milestone:
                return True
        else:
            return False


def has_label(pr, label):
    if label is None:
        return True
    else:
        if [l for l in pr.labels if l.name == label]:
            return True
        else:
            return False


def get_prs(repo, start_date, end_date):
    prs = repo.get_pulls(state="all")
    prs = [pr for pr in prs if pr.merged is True]
    prs = [pr for pr in prs if start_date < pr.merged_at < end_date]
    return prs


def filter_pull_requests(prs, label=None, milestone=None):
    """Filter pull requests with desired label."""
    filtered_prs = [
        pr for pr in prs if has_milestone(pr, milestone) and has_label(pr, label)
    ]

    filtered_prs = sorted(filtered_prs, key=lambda pr: pr.merged_at)

    return filtered_prs


@click.command()
@click.option("--version", prompt="Version number x.x.x")
@click.option(
    "--start_date",
    prompt="Start date YYYY-MM-DD",
    help="Date that PRs for this release started to get merged.",
)
@click.option(
    "--end_date",
    prompt="End date YYYY-MM-DD",
    help="Date that PRs for this release ended.",
)
def generate_rst(version, start_date, end_date):
    token = Path.home() / "tokens/ross-bott"
    token = token.open().read().replace("\n", "")

    g = gh(token)
    ross_repo = g.get_repo("ross-rotordynamics/ross")
    start_date = datetime(*[int(i) for i in start_date.split("-")])
    end_date = datetime(*[int(i) for i in end_date.split("-")])
    prs = get_prs(ross_repo, start_date, end_date)

    enhacement_prs = filter_pull_requests(prs, label="enhancement")
    bug_prs = filter_pull_requests(prs, label="bug")
    api_change_prs = filter_pull_requests(prs, label="api change")

    # generate rst from prs
    with open(f"version-{version}.rst", mode="w") as rst:
        rst.write(f"Version {version}\n" f'{"-" * len(f"Version {version}")}\n\n')

        rst.write(
            "The following enhancements and bug fixes were implemented for this release:\n\n"
        )
        sections = {
            "Enhancements": enhacement_prs,
            "API changes": api_change_prs,
            "Bug fixes": bug_prs,
        }
        for sec_title, sec_prs in sections.items():

            rst.write(f"{sec_title}\n" f'{"~" * len(sec_title)}\n\n')
            for pr in sec_prs:
                title = pr.title
                body = m2r.convert(pr.body)
                rst.write(
                    f"{title}" f"\n" f'{"^" * len(title)}' f"\n" f"{body}" f"\n" f"\n"
                )


if __name__ == "__main__":
    generate_rst()
