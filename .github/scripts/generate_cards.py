#!/usr/bin/env python3
"""Generate GitHub profile stats, languages, streak, trophies, and activity SVGs."""

from __future__ import annotations

import datetime
import html
import json
import math
import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

GITHUB_USER = os.environ.get("GITHUB_USER", "Josufaria")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
DISPLAY_NAME = os.environ.get("DISPLAY_NAME", "Josué Faria")
OUT_DIR = os.environ.get("OUT_DIR", "dist")

BG_COLOR = "#0d1117"
CARD_BG = "#161b22"
BORDER_COLOR = "#30363d"
GRID_COLOR = "#21262d"
ACCENT_COLOR = "#58a6ff"
AREA_COLOR = "#1f6feb"
TEXT_PRIMARY = "#c9d1d9"
TEXT_SECONDARY = "#8b949e"
FONT_FAMILY = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

DEFAULT_LANG_COLORS = {
    "JavaScript": "#f1e05a",
    "TypeScript": "#3178c6",
    "Python": "#3572A5",
    "Java": "#b07219",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Swift": "#F05138",
    "SQL": "#e38c00",
    "Shell": "#89e051",
    "C#": "#178600",
    "C++": "#f34b7d",
    "C": "#555555",
    "Go": "#00ADD8",
    "Kotlin": "#A97BFF",
    "Dockerfile": "#384d54",
    "Jupyter Notebook": "#DA5B0B",
    "Other": "#8b949e",
}


def http_json(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    req_headers = {
        "User-Agent": "Josufaria-Profile-Card-Generator",
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def graphql_query(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    if not GITHUB_TOKEN:
        raise RuntimeError("No GITHUB_TOKEN available for GraphQL")
    headers = {
        "Authorization": f"bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }
    res = http_json(
        "https://api.github.com/graphql",
        method="POST",
        payload={"query": query, "variables": variables},
        headers=headers,
    )
    if "errors" in res and not res.get("data"):
        raise RuntimeError(f"GraphQL error: {res['errors']}")
    return res["data"]


def fetch_github_data(username: str) -> dict[str, Any]:
    """Fetch user profile, repositories, languages, and daily contributions."""
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.date()

    profile: dict[str, Any] = {
        "name": DISPLAY_NAME,
        "followers": 0,
        "public_repos": 0,
        "stars": 0,
        "total_commits": 0,
        "total_prs": 0,
        "total_issues": 0,
        "languages": {},  # name -> {"size": int, "color": str}
        "contributions": {},  # "YYYY-MM-DD" -> int
        "created_date": (today - datetime.timedelta(days=365)).isoformat(),
    }

    if GITHUB_TOKEN:
        try:
            base_query = """
            query($login: String!) {
              user(login: $login) {
                name
                createdAt
                followers { totalCount }
                pullRequests { totalCount }
                issues { totalCount }
                repositories(
                  first: 100
                  ownerAffiliations: OWNER
                  isFork: false
                  privacy: PUBLIC
                  orderBy: {field: UPDATED_AT, direction: DESC}
                ) {
                  totalCount
                  nodes {
                    name
                    stargazerCount
                    languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
                      edges {
                        size
                        node {
                          name
                          color
                        }
                      }
                    }
                  }
                }
                contributionsCollection {
                  totalCommitContributions
                  restrictedContributionsCount
                  contributionCalendar {
                    totalContributions
                    weeks {
                      contributionDays {
                        contributionCount
                        date
                      }
                    }
                  }
                }
              }
            }
            """
            data = graphql_query(base_query, {"login": username})
            user = data.get("user") or {}
            if user.get("name"):
                profile["name"] = user["name"].split()[0] + (
                    " " + user["name"].split()[1] if len(user["name"].split()) > 1 else ""
                )
            profile["followers"] = (user.get("followers") or {}).get("totalCount", 0)
            profile["total_prs"] = (user.get("pullRequests") or {}).get("totalCount", 0)
            profile["total_issues"] = (user.get("issues") or {}).get("totalCount", 0)

            created_at = user.get("createdAt")
            created_year = today.year
            if created_at:
                profile["created_date"] = created_at[:10]
                created_year = int(created_at[:4])

            repos = user.get("repositories") or {}
            profile["public_repos"] = repos.get("totalCount", 0)
            for repo in repos.get("nodes") or []:
                profile["stars"] += repo.get("stargazerCount", 0)
                for edge in (repo.get("languages") or {}).get("edges") or []:
                    size = edge.get("size", 0)
                    node = edge.get("node") or {}
                    lang_name = node.get("name")
                    if not lang_name or size <= 0:
                        continue
                    color = node.get("color") or DEFAULT_LANG_COLORS.get(lang_name, "#8b949e")
                    entry = profile["languages"].setdefault(lang_name, {"size": 0, "color": color})
                    entry["size"] += size

            # Collect full contribution history year by year from account creation
            year_query = """
            query($login: String!, $from: DateTime!, $to: DateTime!) {
              user(login: $login) {
                contributionsCollection(from: $from, to: $to) {
                  totalCommitContributions
                  restrictedContributionsCount
                  contributionCalendar {
                    weeks {
                      contributionDays {
                        contributionCount
                        date
                      }
                    }
                  }
                }
              }
            }
            """
            total_commits_all = 0
            start_year = max(created_year, today.year - 6)
            for yr in range(start_year, today.year + 1):
                from_dt = f"{yr}-01-01T00:00:00Z"
                to_dt = f"{yr}-12-31T23:59:59Z"
                ydata = graphql_query(year_query, {"login": username, "from": from_dt, "to": to_dt})
                cc = ((ydata.get("user") or {}).get("contributionsCollection")) or {}
                total_commits_all += cc.get("totalCommitContributions", 0) + cc.get(
                    "restrictedContributionsCount", 0
                )
                for week in (cc.get("contributionCalendar") or {}).get("weeks") or []:
                    for day in week.get("contributionDays") or []:
                        d = day.get("date")
                        c = day.get("contributionCount", 0)
                        if d and d <= today.isoformat():
                            profile["contributions"][d] = max(profile["contributions"].get(d, 0), c)

            profile["total_commits"] = total_commits_all
            return profile
        except Exception as exc:
            print(f"GraphQL fetch warning, falling back to REST: {exc}")

    # REST fallback (works even without token)
    rest_headers = {}
    if GITHUB_TOKEN:
        rest_headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    try:
        user_json = http_json(f"https://api.github.com/users/{username}", headers=rest_headers)
        profile["followers"] = user_json.get("followers", 0)
        profile["public_repos"] = user_json.get("public_repos", 0)
        if user_json.get("created_at"):
            profile["created_date"] = user_json["created_at"][:10]
        if user_json.get("name"):
            parts = user_json["name"].split()
            profile["name"] = " ".join(parts[:2])

        repos_json = http_json(
            f"https://api.github.com/users/{username}/repos?per_page=100&type=owner",
            headers=rest_headers,
        )
        for repo in repos_json:
            if repo.get("fork"):
                continue
            profile["stars"] += repo.get("stargazers_count", 0)
            lang = repo.get("language")
            if lang:
                color = DEFAULT_LANG_COLORS.get(lang, "#8b949e")
                entry = profile["languages"].setdefault(lang, {"size": 0, "color": color})
                entry["size"] += max(repo.get("size", 1), 1)
    except Exception as exc:
        print(f"REST user/repos fetch warning: {exc}")

    try:
        contrib_json = http_json(f"https://github-contributions-api.jogruber.de/v4/{username}?y=all")
        for item in contrib_json.get("contributions") or []:
            d = item.get("date")
            c = item.get("count", 0)
            if d and d <= today.isoformat():
                profile["contributions"][d] = c
        profile["total_commits"] = sum(profile["contributions"].values())
    except Exception as exc:
        print(f"Contributions fallback warning: {exc}")

    return profile


def compute_streaks(contributions: dict[str, int]) -> dict[str, Any]:
    today = datetime.date.today()
    if not contributions:
        return {
            "total": 0,
            "first_date": today.isoformat(),
            "current": 0,
            "current_start": today.isoformat(),
            "current_end": today.isoformat(),
            "longest": 0,
            "longest_start": today.isoformat(),
            "longest_end": today.isoformat(),
        }

    sorted_dates = sorted(d for d in contributions if d <= today.isoformat())
    total = sum(contributions[d] for d in sorted_dates)
    first_date = sorted_dates[0] if sorted_dates else today.isoformat()

    # Build contiguous daily series from first_date to today
    start_d = datetime.date.fromisoformat(first_date)
    longest = 0
    longest_start = first_date
    longest_end = first_date

    run = 0
    run_start = start_d
    d = start_d
    while d <= today:
        ds = d.isoformat()
        cnt = contributions.get(ds, 0)
        if cnt > 0:
            if run == 0:
                run_start = d
            run += 1
            if run > longest:
                longest = run
                longest_start = run_start.isoformat()
                longest_end = ds
        else:
            run = 0
        d += datetime.timedelta(days=1)

    # Current streak: if today has 0, allow continuing from yesterday (standard GitHub streak behavior)
    current = 0
    current_start = today
    current_end = today
    check = today
    if contributions.get(today.isoformat(), 0) == 0:
        check = today - datetime.timedelta(days=1)

    if contributions.get(check.isoformat(), 0) > 0:
        current_end = check
        while check >= start_d and contributions.get(check.isoformat(), 0) > 0:
            current += 1
            current_start = check
            check -= datetime.timedelta(days=1)

    return {
        "total": total,
        "first_date": first_date,
        "current": current,
        "current_start": current_start.isoformat(),
        "current_end": current_end.isoformat(),
        "longest": longest,
        "longest_start": longest_start,
        "longest_end": longest_end,
    }


def fmt_date(iso_date: str) -> str:
    try:
        dt = datetime.date.fromisoformat(iso_date)
        return dt.strftime("%b %d, %Y")
    except ValueError:
        return iso_date


def fmt_num(n: int) -> str:
    if n >= 1000:
        return f"{n / 1000:.1f}k" if n % 1000 >= 100 else f"{n // 1000}k"
    return str(n)


def compute_overall_rank(profile: dict[str, Any]) -> tuple[str, float]:
    score = (
        profile["total_commits"] * 1.0
        + profile["stars"] * 4.0
        + profile["total_prs"] * 3.0
        + profile["total_issues"] * 1.5
        + profile["public_repos"] * 2.5
        + profile["followers"] * 3.0
    )
    if score >= 800:
        return "S", 0.92
    if score >= 450:
        return "A+", 0.85
    if score >= 250:
        return "A", 0.78
    if score >= 120:
        return "B+", 0.68
    if score >= 50:
        return "B", 0.56
    return "C+", 0.42


def render_github_stats(profile: dict[str, Any]) -> str:
    title = html.escape(f"{profile['name']}'s GitHub Stats")
    rank, progress = compute_overall_rank(profile)
    radius = 40
    circumference = 2 * math.pi * radius
    dash_offset = circumference * (1.0 - progress)

    rows = [
        (
            "Total Stars Earned:",
            fmt_num(profile["stars"]),
            "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.75.75 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z",
        ),
        (
            "Total Commits:",
            fmt_num(profile["total_commits"]),
            "M11.93 8.5a4.002 4.002 0 0 1-7.86 0H.75a.75.75 0 0 1 0-1.5h3.32a4.002 4.002 0 0 1 7.86 0h3.32a.75.75 0 0 1 0 1.5Zm-1.43-.75a2.5 2.5 0 1 0-5 0 2.5 2.5 0 0 0 5 0Z",
        ),
        (
            "Total PRs:",
            fmt_num(profile["total_prs"]),
            "M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354Z",
        ),
        (
            "Total Issues:",
            fmt_num(profile["total_issues"]),
            "M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z",
        ),
        (
            "Public Repositories:",
            fmt_num(profile["public_repos"]),
            "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8Z",
        ),
    ]

    row_svgs = []
    for idx, (label, val, path_d) in enumerate(rows):
        y = 66 + idx * 25
        row_svgs.append(
            f'<g transform="translate(25, {y})">'
            f'<svg x="0" y="-12" width="16" height="16" viewBox="0 0 16 16" fill="{ACCENT_COLOR}">'
            f'<path fill-rule="evenodd" d="{path_d}"/></svg>'
            f'<text x="25" y="0" fill="{TEXT_PRIMARY}" font-size="13.5" font-weight="600" font-family="{FONT_FAMILY}">{html.escape(label)}</text>'
            f'<text x="275" y="0" fill="{TEXT_PRIMARY}" font-size="13.5" font-weight="700" text-anchor="end" font-family="{FONT_FAMILY}">{html.escape(val)}</text>'
            f"</g>"
        )

    return f"""<svg width="495" height="195" viewBox="0 0 495 195" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0.5" y="0.5" width="494" height="194" rx="6" fill="{BG_COLOR}" stroke="{BORDER_COLOR}"/>
  <text x="25" y="34" fill="{ACCENT_COLOR}" font-size="18" font-weight="700" font-family="{FONT_FAMILY}">{title}</text>
  {"".join(row_svgs)}
  <g transform="translate(405, 106)">
    <circle cx="0" cy="0" r="{radius}" stroke="{GRID_COLOR}" stroke-width="6" fill="none"/>
    <circle cx="0" cy="0" r="{radius}" stroke="{ACCENT_COLOR}" stroke-width="6" fill="none"
      stroke-linecap="round" stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{dash_offset:.2f}"
      transform="rotate(-90)"/>
    <text x="0" y="7" fill="{TEXT_PRIMARY}" font-size="22" font-weight="800" text-anchor="middle" font-family="{FONT_FAMILY}">{html.escape(rank)}</text>
  </g>
</svg>
"""


def render_top_langs(profile: dict[str, Any]) -> str:
    langs_dict = profile["languages"]
    sorted_langs = sorted(langs_dict.items(), key=lambda item: item[1]["size"], reverse=True)
    if not sorted_langs:
        sorted_langs = [
            ("JavaScript", {"size": 35, "color": DEFAULT_LANG_COLORS["JavaScript"]}),
            ("TypeScript", {"size": 25, "color": DEFAULT_LANG_COLORS["TypeScript"]}),
            ("Java", {"size": 20, "color": DEFAULT_LANG_COLORS["Java"]}),
            ("Python", {"size": 20, "color": DEFAULT_LANG_COLORS["Python"]}),
        ]

    top = sorted_langs[:7]
    if len(sorted_langs) > 7:
        other_size = sum(v["size"] for _, v in sorted_langs[7:])
        if other_size > 0:
            top.append(("Other", {"size": other_size, "color": DEFAULT_LANG_COLORS["Other"]}))

    total_size = sum(v["size"] for _, v in top) or 1
    bar_width = 445
    bar_x = 25
    bar_y = 54

    segments = []
    cur_x = float(bar_x)
    for name, info in top:
        seg_w = (info["size"] / total_size) * bar_width
        segments.append(
            f'<rect x="{cur_x:.2f}" y="{bar_y}" width="{max(seg_w, 1.5):.2f}" height="10" fill="{html.escape(info["color"])}"/>'
        )
        cur_x += seg_w

    legend_items = []
    for idx, (name, info) in enumerate(top):
        pct = (info["size"] / total_size) * 100
        col = idx % 2
        row = idx // 2
        lx = 25 + col * 225
        ly = 94 + row * 25
        legend_items.append(
            f'<g transform="translate({lx}, {ly})">'
            f'<circle cx="5" cy="-4" r="5" fill="{html.escape(info["color"])}"/>'
            f'<text x="16" y="0" fill="{TEXT_PRIMARY}" font-size="12.5" font-weight="500" font-family="{FONT_FAMILY}">'
            f'{html.escape(name)} <tspan fill="{TEXT_SECONDARY}">{pct:.1f}%</tspan></text>'
            f"</g>"
        )

    return f"""<svg width="495" height="195" viewBox="0 0 495 195" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <clipPath id="lang-bar-clip">
      <rect x="{bar_x}" y="{bar_y}" width="{bar_width}" height="10" rx="5"/>
    </clipPath>
  </defs>
  <rect x="0.5" y="0.5" width="494" height="194" rx="6" fill="{BG_COLOR}" stroke="{BORDER_COLOR}"/>
  <text x="25" y="34" fill="{ACCENT_COLOR}" font-size="18" font-weight="700" font-family="{FONT_FAMILY}">Most Used Languages</text>
  <g clip-path="url(#lang-bar-clip)">
    {"".join(segments)}
  </g>
  {"".join(legend_items)}
</svg>
"""


def render_streak_stats(streak: dict[str, Any]) -> str:
    total_range = f"{fmt_date(streak['first_date'])} - Present"
    curr_range = (
        f"{fmt_date(streak['current_start'])} - {fmt_date(streak['current_end'])}"
        if streak["current"] > 0
        else "No active streak today"
    )
    long_range = (
        f"{fmt_date(streak['longest_start'])} - {fmt_date(streak['longest_end'])}"
        if streak["longest"] > 0
        else "No streak recorded"
    )

    return f"""<svg width="700" height="180" viewBox="0 0 700 180" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0.5" y="0.5" width="699" height="179" rx="6" fill="{BG_COLOR}" stroke="{BORDER_COLOR}"/>
  <line x1="233" y1="24" x2="233" y2="156" stroke="{GRID_COLOR}" stroke-width="1.5"/>
  <line x1="467" y1="24" x2="467" y2="156" stroke="{GRID_COLOR}" stroke-width="1.5"/>

  <!-- Total Contributions -->
  <text x="116.5" y="76" fill="{TEXT_PRIMARY}" font-size="30" font-weight="800" text-anchor="middle" font-family="{FONT_FAMILY}">{streak['total']}</text>
  <text x="116.5" y="106" fill="{TEXT_PRIMARY}" font-size="14" font-weight="600" text-anchor="middle" font-family="{FONT_FAMILY}">Total Contributions</text>
  <text x="116.5" y="130" fill="{TEXT_SECONDARY}" font-size="11.5" text-anchor="middle" font-family="{FONT_FAMILY}">{html.escape(total_range)}</text>

  <!-- Current Streak Ring -->
  <circle cx="350" cy="68" r="36" stroke="{ACCENT_COLOR}" stroke-width="4" fill="none"/>
  <circle cx="350" cy="32" r="10" fill="{BG_COLOR}"/>
  <path d="M350 22 C352.5 25.5 354.5 28 354.5 31.2 C354.5 33.8 352.5 35.8 350 35.8 C347.5 35.8 345.5 33.8 345.5 31.2 C345.5 29.4 346.4 27.9 347.4 26.8 C347.3 28.1 348.2 29 348.9 29 C348.7 26.6 349.1 24.3 350 22 Z" fill="{ACCENT_COLOR}"/>
  <text x="350" y="77" fill="{TEXT_PRIMARY}" font-size="28" font-weight="800" text-anchor="middle" font-family="{FONT_FAMILY}">{streak['current']}</text>
  <text x="350" y="126" fill="{ACCENT_COLOR}" font-size="14" font-weight="700" text-anchor="middle" font-family="{FONT_FAMILY}">Current Streak</text>
  <text x="350" y="148" fill="{TEXT_SECONDARY}" font-size="11.5" text-anchor="middle" font-family="{FONT_FAMILY}">{html.escape(curr_range)}</text>

  <!-- Longest Streak -->
  <text x="583.5" y="76" fill="{TEXT_PRIMARY}" font-size="30" font-weight="800" text-anchor="middle" font-family="{FONT_FAMILY}">{streak['longest']}</text>
  <text x="583.5" y="106" fill="{TEXT_PRIMARY}" font-size="14" font-weight="600" text-anchor="middle" font-family="{FONT_FAMILY}">Longest Streak</text>
  <text x="583.5" y="130" fill="{TEXT_SECONDARY}" font-size="11.5" text-anchor="middle" font-family="{FONT_FAMILY}">{html.escape(long_range)}</text>
</svg>
"""


def trophy_tier(value: int, thresholds: list[tuple[int, str, str]]) -> tuple[str, str]:
    for threshold, rank, color in thresholds:
        if value >= threshold:
            return rank, color
    return "C", "#8b949e"


def render_trophies(profile: dict[str, Any]) -> str:
    gold = "#e3b341"
    silver = "#58a6ff"
    bronze = "#8b949e"

    items = [
        ("Repositories", profile["public_repos"], f"{profile['public_repos']} repos", [(50, "SSS", gold), (30, "SS", gold), (20, "S", gold), (10, "AAA", silver), (5, "AA", silver), (1, "A", bronze)]),
        ("Commits", profile["total_commits"], f"{fmt_num(profile['total_commits'])} pt", [(1000, "SSS", gold), (500, "SS", gold), (250, "S", gold), (100, "AAA", silver), (50, "AA", silver), (10, "A", bronze)]),
        ("Languages", len(profile["languages"]), f"{len(profile['languages'])} langs", [(12, "SSS", gold), (9, "SS", gold), (7, "S", gold), (5, "AAA", silver), (3, "AA", silver), (1, "A", bronze)]),
        ("Stars", profile["stars"], f"{profile['stars']} pt", [(100, "SSS", gold), (50, "SS", gold), (20, "S", gold), (10, "AAA", silver), (3, "AA", silver), (1, "A", bronze)]),
        ("PullRequest", profile["total_prs"], f"{profile['total_prs']} PRs", [(50, "SSS", gold), (25, "SS", gold), (10, "S", gold), (5, "AAA", silver), (2, "AA", silver), (1, "A", bronze)]),
        ("Issues", profile["total_issues"], f"{profile['total_issues']} pt", [(50, "SSS", gold), (25, "SS", gold), (10, "S", gold), (5, "AAA", silver), (2, "AA", silver), (1, "A", bronze)]),
        ("Followers", profile["followers"], f"{profile['followers']} pt", [(100, "SSS", gold), (50, "SS", gold), (20, "S", gold), (10, "AAA", silver), (3, "AA", silver), (1, "A", bronze)]),
    ]

    cards = []
    card_w = 110
    gap = 10
    start_x = 10
    for idx, (label, val, sub, thresholds) in enumerate(items):
        rank, color = trophy_tier(val, thresholds)
        x = start_x + idx * (card_w + gap)
        cx = x + card_w / 2
        cards.append(
            f'<g>'
            f'<rect x="{x}" y="8" width="{card_w}" height="124" rx="8" fill="{CARD_BG}" stroke="{BORDER_COLOR}"/>'
            f'<text x="{cx}" y="28" fill="{TEXT_PRIMARY}" font-size="11.5" font-weight="700" text-anchor="middle" font-family="{FONT_FAMILY}">{html.escape(label)}</text>'
            f'<g transform="translate({cx - 16}, 36)">'
            f'<path d="M8 4h16v10c0 4.4-3.6 8-8 8s-8-3.6-8-8V4z" fill="none" stroke="{color}" stroke-width="2"/>'
            f'<path d="M8 7H4c0 4 1.8 6 4 6M24 7h4c0 4-1.8 6-4 6" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
            f'<path d="M16 22v5M11 27h10" stroke="{color}" stroke-width="2" stroke-linecap="round"/>'
            f'<text x="16" y="15" fill="{color}" font-size="8.5" font-weight="800" text-anchor="middle" font-family="{FONT_FAMILY}">{html.escape(rank)}</text>'
            f'</g>'
            f'<rect x="{cx - 18}" y="76" width="36" height="18" rx="4" fill="{BG_COLOR}" stroke="{color}" stroke-width="1"/>'
            f'<text x="{cx}" y="89" fill="{color}" font-size="10.5" font-weight="800" text-anchor="middle" font-family="{FONT_FAMILY}">{html.escape(rank)}</text>'
            f'<text x="{cx}" y="116" fill="{TEXT_SECONDARY}" font-size="11" font-weight="600" text-anchor="middle" font-family="{FONT_FAMILY}">{html.escape(sub)}</text>'
            f'</g>'
        )

    return f"""<svg width="850" height="140" viewBox="0 0 850 140" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect x="0.5" y="0.5" width="849" height="139" rx="6" fill="{BG_COLOR}" stroke="{BORDER_COLOR}"/>
  {"".join(cards)}
</svg>
"""


def render_activity_graph(profile: dict[str, Any]) -> str:
    today = datetime.date.today()
    days = [today - datetime.timedelta(days=offset) for offset in range(30, -1, -1)]
    values = [profile["contributions"].get(d.isoformat(), 0) for d in days]
    max_val = max(max(values), 4)
    # Round max_val up to a clean multiple of 4 for 4 grid bands
    y_top = int(math.ceil(max_val / 4.0) * 4)

    left = 55.0
    right = 825.0
    top = 60.0
    bottom = 250.0
    plot_w = right - left
    plot_h = bottom - top

    # Horizontal grid + Y labels
    grid_lines = []
    for step in range(5):
        val = int((y_top / 4) * step)
        y = bottom - (step / 4.0) * plot_h
        grid_lines.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{GRID_COLOR}" stroke-dasharray="4 4"/>'
            f'<text x="{left - 10}" y="{y + 4:.1f}" fill="{TEXT_SECONDARY}" font-size="11" text-anchor="end" font-family="{FONT_FAMILY}">{val}</text>'
        )

    points = []
    for idx, val in enumerate(values):
        x = left + (idx / (len(days) - 1)) * plot_w
        y = bottom - (val / float(y_top)) * plot_h
        points.append((x, y, val, days[idx]))

    # Smooth quadratic/cubic bezier path clamped inside plot bounds
    line_parts = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    for i in range(1, len(points)):
        x0, y0 = points[i - 1][0], points[i - 1][1]
        x1, y1 = points[i][0], points[i][1]
        cx = (x0 + x1) / 2.0
        line_parts.append(f"C {cx:.2f} {y0:.2f}, {cx:.2f} {y1:.2f}, {x1:.2f} {y1:.2f}")
    line_d = " ".join(line_parts)
    area_d = f"{line_d} L {points[-1][0]:.2f} {bottom:.2f} L {points[0][0]:.2f} {bottom:.2f} Z"

    circles = [
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.5" fill="{TEXT_PRIMARY}" stroke="{ACCENT_COLOR}" stroke-width="1.5"/>'
        for x, y, _, _ in points
    ]

    x_labels = []
    for idx, (x, _, _, d) in enumerate(points):
        if idx % 5 == 0 or idx == len(points) - 1:
            x_labels.append(
                f'<text x="{x:.2f}" y="{bottom + 22:.1f}" fill="{TEXT_SECONDARY}" font-size="11" text-anchor="middle" font-family="{FONT_FAMILY}">{d.strftime("%d/%m")}</text>'
            )

    title = html.escape(f"{profile['name']}'s Contribution Graph (Last 31 Days)")

    return f"""<svg width="850" height="300" viewBox="0 0 850 300" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{AREA_COLOR}" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="{AREA_COLOR}" stop-opacity="0.02"/>
    </linearGradient>
  </defs>
  <rect x="0.5" y="0.5" width="849" height="299" rx="6" fill="{BG_COLOR}" stroke="{BORDER_COLOR}"/>
  <text x="425" y="34" fill="{ACCENT_COLOR}" font-size="17" font-weight="700" text-anchor="middle" font-family="{FONT_FAMILY}">{title}</text>
  {"".join(grid_lines)}
  <path d="{area_d}" fill="url(#areaGrad)"/>
  <path d="{line_d}" stroke="{ACCENT_COLOR}" stroke-width="2.5" fill="none" stroke-linecap="round"/>
  {"".join(circles)}
  {"".join(x_labels)}
</svg>
"""


def write_and_validate_svg(path: str, content: str) -> None:
    ET.fromstring(content)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    profile = fetch_github_data(GITHUB_USER)
    streak = compute_streaks(profile["contributions"])

    files = {
        "github-stats.svg": render_github_stats(profile),
        "top-langs.svg": render_top_langs(profile),
        "streak-stats.svg": render_streak_stats(streak),
        "trophies.svg": render_trophies(profile),
        "activity-graph.svg": render_activity_graph(profile),
    }

    for filename, svg in files.items():
        out_path = os.path.join(OUT_DIR, filename)
        write_and_validate_svg(out_path, svg)
        print(f"Generated {out_path}")


if __name__ == "__main__":
    main()
