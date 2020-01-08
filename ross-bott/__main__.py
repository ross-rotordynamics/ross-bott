"""Script to look for stale issues and require some action from the team.
"""
import asyncio
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import aiohttp
import schedule
import sentry_sdk
from aiohttp import web

from gidgethub import aiohttp as gh_aiohttp, routing, sansio
from github import Github as gh
from jinja2 import Environment, FileSystemLoader
from sentry_sdk.integrations.logging import LoggingIntegration

from .statistics import stats_plot, stars_plot

sentry_logging = LoggingIntegration(
    level=logging.INFO,  # Capture info and above as breadcrumbs
    event_level=logging.INFO,  # Send errors as events
)
sentry_sdk.init(dsn=os.environ.get("SENTRY_DSN"), integrations=[sentry_logging])

token = os.environ.get("GH_AUTH")
g = gh(token)
ross_repo = g.get_repo("ross-rotordynamics/ross")

routes = web.RouteTableDef()
router = routing.Router()


@router.register("issues", action="opened")
async def issue_opened_event(event, gh, *args, **kwargs):
    """
    Whenever an issue is opened, greet the author and say thanks.
    """
    pass


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
        gh = gh_aiohttp.GitHubAPI(session, "ross-bott", oauth_token=oauth_token)

        # call the appropriate callback for the event
        await router.dispatch(event, gh)

    # return a "Success"
    return web.Response(status=200)


@routes.get("/")
async def web_page(request):
    return web.FileResponse(status=200, path="ross-bott/static/main.html")


def aiohttp_server():
    app = web.Application()
    app.router.add_static('/static/', (Path.cwd() / 'ross-bott/static'))
    app.add_routes(routes)
    runner = web.AppRunner(app)
    return runner


def run_server(runner):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(runner.setup())

    port = os.environ.get("PORT")
    if port:
        port = int(port)
    site = web.TCPSite(runner, port=port)
    loop.run_until_complete(site.start())
    loop.run_forever()


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

    for issue in not_updated_issues:
        issue.create_comment(stale_message)
        issue.add_to_labels("stale")
    print(not_updated_issues)


def generate_html():
    env = Environment(loader=FileSystemLoader('ross-bott/templates'))
    template = env.get_template('template.html')
    views_plot_script, views_plot_div = stats_plot('views', ross_repo)
    clones_plot_script, clones_plot_div = stats_plot('clones', ross_repo)
    stars_plot_script, stars_plot_div = stars_plot(ross_repo)
    output = template.render(views_plot_div=views_plot_div,
                             views_plot_script=views_plot_script,
                             clones_plot_div=clones_plot_div,
                             clones_plot_script=clones_plot_script,
                             stars_plot_div=stars_plot_div,
                             stars_plot_script=stars_plot_script)

    with open('ross-bott/static/main.html', 'w') as f:
        f.write(output)


def scheduled_tasks():
    schedule.every().day.at("10:30").do(mark_stale_issues)
    schedule.every().day.at("11:00").do(generate_html)
    while True:
        schedule.run_pending()
        time.sleep(5 * 60)
        print(f"App is up. Waiting to run {mark_stale_issues}")


if __name__ == "__main__":
    print("Started app.")
    scheduled_tasks_thread = threading.Thread(target=scheduled_tasks)
    wep_app = threading.Thread(target=run_server, args=(aiohttp_server(),))

    scheduled_tasks_thread.start()
    wep_app.start()
