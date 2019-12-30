"""Script to look for stale issues and require some action from the team.
"""
import os
import time
import logging
import schedule
import aiohttp
import threading
import sentry_sdk
from github import Github as gh
from datetime import datetime
from aiohttp import web
from gidgethub import routing, sansio
from gidgethub import aiohttp as gh_aiohttp
from sentry_sdk.integrations.logging import LoggingIntegration

sentry_logging = LoggingIntegration(
    level=logging.INFO,        # Capture info and above as breadcrumbs
    event_level=logging.INFO   # Send errors as events
)
sentry_sdk.init(
    dsn="https://de5148635d84489d9451f404e2d8fb17@sentry.io/1868960",
    integrations=[sentry_logging]
)

sentry_sdk.init(dsn=os.environ.get("SENTRY_DSN"))


routes = web.RouteTableDef()
router = routing.Router()


@router.register("issues", action="opened")
async def issue_opened_event(event, gh, *args, **kwargs):
    """
    Whenever an issue is opened, greet the author and say thanks.
    """
    pass
    # url = event.data["issue"]["comments_url"]
    # author = event.data["issue"]["user"]["login"]
    #
    # message = f"Thanks for the report @{author}! I will look into it ASAP! (I'm a bot)."
    # await gh.post(url, data={"body": message})


@routes.post("/")
async def main(request):
    # read the GitHub webhook payload
    logging.debug("Running main.")
    body = await request.read()

    # our authentication token and secret
    secret = os.environ.get("GH_SECRET")
    oauth_token = os.environ.get("GH_AUTH")

    # a representation of GitHub webhook event
    event = sansio.Event.from_http(request.headers, body, secret=secret)
    async with aiohttp.ClientSession() as session:
        gh = gh_aiohttp.GitHubAPI(session, "ross-bott",
                                  oauth_token=oauth_token)

        # call the appropriate callback for the event
        await router.dispatch(event, gh)

    # return a "Success"
    return web.Response(status=200)

token = os.environ.get("GH_AUTH")
g = gh(token)
ross_repo = g.get_repo("ross-rotordynamics/ross")


def mark_stale_issues():
    # days limit for staled issues
    print(f'Running "mark_stale_issues" at {datetime.now()}')
    logging.debug(f'Running "mark_stale_issues" at {datetime.now()}')

    LIMIT = 45

    issues = ross_repo.get_issues(state="open")
    not_updated_issues = []
    for issue in issues:
        last_update = (datetime.today() - issue.updated_at).days
        if last_update > LIMIT:
            not_updated_issues.append(issue)

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

    # for issue in not_updated_issues:
    #     issue.create_comment(stale_message)
    #     issue.add_to_labels("stale")
    print(not_updated_issues)
    time.sleep(10)


if __name__ == "__main__":
    print("Started app.")
    # schedule.every(1).minutes.do(mark_stale_issues)
    stale_issues_task = threading.Thread(target=mark_stale_issues)
    stale_issues_task.start()

    app = web.Application()
    app.add_routes(routes)
    port = os.environ.get("PORT")
    if port:
        port = int(port)

    web.run_app(app, port=port)

    # while True:
    #     schedule.run_pending()
    #     time.sleep(10)

