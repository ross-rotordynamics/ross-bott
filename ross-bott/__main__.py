"""Script to look for stale issues and require some action from the team.
"""
import asyncio
import csv
import logging
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
import boto3
import schedule
import sentry_sdk
from aiohttp import web
from bokeh.embed import components
from bokeh.models import HoverTool, LinearAxis, Range1d
from bokeh.plotting import ColumnDataSource, figure
from gidgethub import aiohttp as gh_aiohttp, routing, sansio
from github import Github as gh
from jinja2 import Environment, FileSystemLoader
from sentry_sdk.integrations.logging import LoggingIntegration
from smart_open import open

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
    generate_html()
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


def statistics(stats_type):
    """Get views or clones statistics from GitHub."""
    # first load saved statistics from s3 bucket
    s3_bucket = os.environ.get("S3_BUCKET", default="ross-bott")
    file_name = f"{stats_type}.csv"

    stats_dict = {"timestamp": [], "count": [], "uniques": []}
    with open(f"s3://{s3_bucket}/{file_name}") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            stats_dict["timestamp"].append(row['timestamp'])
            stats_dict["count"].append(int(row["count"]))
            stats_dict["uniques"].append(int(row["uniques"]))

        # add today if not in there
    # check days without update
    last_update = datetime.strptime(stats_dict['timestamp'][-1], "%Y-%m-%dT%H:%M:%SZ")
    days_without_update = (datetime.today() - last_update).days
    dates_not_included = [datetime.today().date() - timedelta(days=x) for x in range(days_without_update)]
    stats = getattr(ross_repo, f'get_{stats_type}_traffic')(per='day')[stats_type]
    for s in stats:
        if s.timestamp.date() in dates_not_included:
            stats_dict["timestamp"].append(s.raw_data['timestamp'].timestamp)
            stats_dict["count"].append(s.count)
            stats_dict["uniques"].append(s.uniques)
    with open(file_name, "w") as views_file:
        dict_list = [dict(zip(stats_dict, t)) for t in zip(*stats_dict.values())]
        writer = csv.DictWriter(views_file, ["timestamp", "count", "uniques"])
        writer.writeheader()
        for item in dict_list:
            writer.writerow(item)
    upload_to_S3(file_name)

    for i, item in enumerate(stats_dict['timestamp']):
        stats_dict['timestamp'][i] = datetime.strptime(item, "%Y-%m-%dT%H:%M:%SZ")

    return stats_dict


def stats_plot(stats_type):
    stats_dict = statistics(stats_type)
    source = ColumnDataSource(stats_dict)
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
        title=f"{stats_type.capitalize()}",
        x_axis_type="datetime",
        y_axis_label="Count",
        y_range=(0, max(stats_dict["count"]) + 1),
        tools=[hover, "pan", "wheel_zoom", "reset"],
        width=719,
        height=243,
    )
    p.extra_y_ranges["uniques"] = Range1d(0, max(stats_dict["uniques"]) + 1)
    p.add_layout(LinearAxis(y_range_name="uniques", axis_label="Uniques"), "right")
    line_count = p.line("timestamp", "count", source=source)
    p.line("timestamp", "uniques", source=source, y_range_name="uniques", color="green")
    p.circle("timestamp", "count", source=source)
    p.circle(
        "timestamp", "uniques", source=source, y_range_name="uniques", color="green"
    )
    hover.renderers.append(line_count)

    script, div = components(p)

    return script, div


def stars_statistics():
    pass
    """Get stars statistics from GitHub."""
    # first load saved statistics from s3 bucket
    s3_bucket = os.environ.get("S3_BUCKET", default="ross-bott")
    file_name = "stars.csv"

    stars_dict = {"user": [], "starred_at": []}
    with open(f"s3://{s3_bucket}/{file_name}") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            stars_dict["starred_at"].append(row["starred_at"])
            stars_dict["user"].append(row["user"])

    # check new stargazers
    stargazers = ross_repo.get_stargazers_with_dates()
    stars_not_included = [s for s in stargazers if s.user.login not in stars_dict["user"]]
    for star in stars_not_included:
        stars_dict['user'].append(star.user.login)
        stars_dict['starred_at'].append(star.raw_data['starred_at'])
    with open(file_name, "w") as stars_file:
        dict_list = [dict(zip(stars_dict, t)) for t in zip(*stars_dict.values())]
        writer = csv.DictWriter(stars_file, ["user", "starred_at"])
        writer.writeheader()
        for item in dict_list:
            writer.writerow(item)
    upload_to_S3(file_name)

    return stars_dict


def stars_plot():
    stars_dict = stars_statistics()
    stars_count_dict = {'timestamp': [], 'count': []}
    for i, data in enumerate(stars_dict['starred_at']):
        stars_count_dict['timestamp'].append(datetime.strptime(data, "%Y-%m-%dT%H:%M:%SZ"))
        stars_count_dict['count'].append(i)

    source = ColumnDataSource(stars_count_dict)
    hover = HoverTool(
        renderers=[],
        tooltips=[
            ("Count", "@count"),
            ("Time", "@timestamp{%Y-%m-%d}"),
        ],
        formatters={"timestamp": "datetime"},
        mode="vline",
    )
    p = figure(
        title="Stars",
        x_axis_type="datetime",
        y_axis_label="Count",
        y_range=(0, max(stars_count_dict["count"]) + 1),
        tools=[hover, "pan", "wheel_zoom", "reset"],
        width=719,
        height=243,
    )
    line_count = p.line("timestamp", "count", source=source)
    p.circle("timestamp", "count", source=source)
    hover.renderers.append(line_count)
    script, div = components(p)

    return script, div


def generate_html():
    env = Environment(loader=FileSystemLoader('ross-bott/templates'))
    template = env.get_template('template.html')
    views_plot_script, views_plot_div = stats_plot('views')
    clones_plot_script, clones_plot_div = stats_plot('clones')
    stars_plot_script, stars_plot_div = stars_plot()
    output = template.render(views_plot_div=views_plot_div,
                             views_plot_script=views_plot_script,
                             clones_plot_div=clones_plot_div,
                             clones_plot_script=clones_plot_script,
                             stars_plot_div=stars_plot_div,
                             stars_plot_script=stars_plot_script)

    with open('ross-bott/static/main.html', 'w') as f:
        f.write(output)


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

