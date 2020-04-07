"""ROSS' repository statistics."""
import csv
import os
from datetime import datetime, timedelta

from bokeh.embed import components
from bokeh.models import HoverTool, LinearAxis, Range1d
from bokeh.plotting import ColumnDataSource, figure
from smart_open import open

from .utils import upload_to_s3


def statistics(stats_type, repo):
    """Get views or clones statistics from GitHub."""
    # first load saved statistics from s3 bucket
    s3_bucket = os.environ.get("S3_BUCKET", default="ross-bott")
    file_name = f"{stats_type}.csv"

    stats_dict = {"timestamp": [], "count": [], "uniques": []}
    with open(f"s3://{s3_bucket}/{file_name}") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            stats_dict["timestamp"].append(row["timestamp"])
            stats_dict["count"].append(int(row["count"]))
            stats_dict["uniques"].append(int(row["uniques"]))

        # add today if not in there
    # check days without update
    last_update = datetime.strptime(stats_dict["timestamp"][-1], "%Y-%m-%dT%H:%M:%SZ")
    days_without_update = (datetime.today() - last_update).days
    dates_not_included = [
        datetime.today().date() - timedelta(days=x) for x in range(days_without_update)
    ]
    stats = getattr(repo, f"get_{stats_type}_traffic")(per="day")[stats_type]
    for s in stats:
        if s.timestamp.date() in dates_not_included:
            stats_dict["timestamp"].append(s.raw_data["timestamp"])
            stats_dict["count"].append(s.count)
            stats_dict["uniques"].append(s.uniques)

    for i, item in enumerate(stats_dict["timestamp"]):
        stats_dict["timestamp"][i] = datetime.strptime(item, "%Y-%m-%dT%H:%M:%SZ").date()

    # fill with 0's dates not in the data
    delta = (datetime.today().date() - stats_dict["timestamp"][0]).days
    for i in reversed(range(delta)):
        d = datetime.today().date() - timedelta(days=i)
        if d not in stats_dict["timestamp"]:
            stats_dict["timestamp"].append(d)
            stats_dict["count"].append(0)
            stats_dict["uniques"].append(0)
    # sort after adding 0's
    timestamp, count, uniques = (list(i) for i in zip(*sorted(zip(*stats_dict.values()))))
    stats_dict["timestamp"] = timestamp
    stats_dict["count"] = count
    stats_dict["uniques"] = uniques
    
    with open(file_name, "w") as stats_file:
        dict_list = [dict(zip(stats_dict, t)) for t in zip(*stats_dict.values())]
        writer = csv.DictWriter(stats_file, ["timestamp", "count", "uniques"])
        writer.writeheader()
        for item in dict_list:
            writer.writerow(item)
    upload_to_s3(file_name)

    return stats_dict


def stats_plot(stats_type, repo):
    stats_dict = statistics(stats_type, repo)
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


def stars_statistics(repo):
    """Get stars statistics from GitHub."""
    file_name = "stars.csv"
    stars_dict = {"user": [], "starred_at": []}

    # check stargazers
    stargazers = repo.get_stargazers_with_dates()

    for star in stargazers:
        stars_dict["user"].append(star.user.login)
        stars_dict["starred_at"].append(star.raw_data["starred_at"])

    with open(file_name, "w") as stars_file:
        dict_list = [dict(zip(stars_dict, t)) for t in zip(*stars_dict.values())]
        writer = csv.DictWriter(stars_file, ["user", "starred_at"])
        writer.writeheader()
        for item in dict_list:
            writer.writerow(item)
    upload_to_s3(file_name)

    return stars_dict


def stars_plot(repo):
    stars_dict = stars_statistics(repo)
    stars_count_dict = {"timestamp": [], "count": []}
    for i, data in enumerate(stars_dict["starred_at"]):
        stars_count_dict["timestamp"].append(
            datetime.strptime(data, "%Y-%m-%dT%H:%M:%SZ")
        )
        stars_count_dict["count"].append(i + 1)

    source = ColumnDataSource(stars_count_dict)
    hover = HoverTool(
        renderers=[],
        tooltips=[("Count", "@count"), ("Time", "@timestamp{%Y-%m-%d}")],
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
