"""Script to look for stale issues and require some action from the team.
"""
import os
import time
import csv
import schedule
import logging
import aiohttp
import asyncio
import threading
import sentry_sdk
import boto3
from smart_open import open
from github import Github as gh
from datetime import datetime
from aiohttp import web
from gidgethub import routing, sansio
from gidgethub import aiohttp as gh_aiohttp
from sentry_sdk.integrations.logging import LoggingIntegration
from bokeh.plotting import figure, ColumnDataSource, output_file, save
from bokeh.models import Range1d, LinearAxis, HoverTool
from bokeh.resources import CDN
from bokeh.embed import file_html

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
    views_plot()
    return web.FileResponse(status=200, path="views_plot.html")


def aiohttp_server():
    app = web.Application()
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


def views_statistics():
    """Get views statistics from GitHub."""
    # first load saved statistics from s3 bucket
    s3_bucket = os.environ.get("S3_BUCKET", default="ross-bott")
    file_name = "views.csv"

    views_dict = {"timestamp": [], "count": [], "uniques": []}
    with open(f"s3://{s3_bucket}/{file_name}") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            views_dict["timestamp"].append(
                datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
            )
            views_dict["count"].append(int(row["count"]))
            views_dict["uniques"].append(int(row["uniques"]))

        # add today if not in there
    if datetime.today().date() not in [d.date() for d in views_dict["timestamp"]]:
        views = ross_repo.get_views_traffic(per="day")["views"]
        for view in views:
            if view.timestamp.date() == datetime.today().date():
                views_dict["timestamp"].append(view.timestamp)
                views_dict["count"].append(view.count)
                views_dict["uniques"].append(view.uniques)
        with open(file_name, "w") as views_file:
            dict_list = [dict(zip(views_dict, t)) for t in zip(*views_dict.values())]
            writer = csv.DictWriter(views_file, ["timestamp", "count", "uniques"])
            writer.writeheader()
            for item in dict_list:
                writer.writerow(item)
        upload_to_S3(file_name)

    return views_dict


def views_plot():
    views_dict = views_statistics()
    source = ColumnDataSource(views_dict)
    hover = HoverTool(
        renderers=[],
        tooltips=[
            ("Count", "@count"),
            ("Unique", "@uniques"),
            ("Time", "@timestamp{%Y-%m-%d}"),
        ],
        formatters={"timestamp": "datetime"},
        mode="vline",
    )
    p = figure(
        title="Views",
        x_axis_type="datetime",
        y_axis_label="Count",
        y_range=(0, max(views_dict["count"]) + 1),
        tools=[hover, "pan", "wheel_zoom", "reset"],
    )
    p.extra_y_ranges["uniques"] = Range1d(0, max(views_dict["uniques"]) + 1)
    p.add_layout(LinearAxis(y_range_name="uniques", axis_label="Uniques"), "right")
    line_count = p.line("timestamp", "count", source=source)
    p.line("timestamp", "uniques", source=source, y_range_name="uniques", color="green")
    p.circle("timestamp", "count", source=source)
    p.circle(
        "timestamp", "uniques", source=source, y_range_name="uniques", color="green"
    )
    hover.renderers.append(line_count)
    output_file("views_plot.html")
    save(p)

    return file_html(p, CDN, "Views plot")


def upload_to_S3(file_name):
    S3_BUCKET = os.environ.get("S3_BUCKET")
    s3 = boto3.client("s3")
    s3.upload_file(file_name, S3_BUCKET, file_name)


def scheduled_tasks():
    schedule.every().day.at("10:30").do(mark_stale_issues)
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
