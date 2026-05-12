from __future__ import annotations

import datetime as _dt
import re

import click

from . import auth
from . import config as cfg
from .api import FreeAgent


def _api() -> FreeAgent:
    c = cfg.load()
    if not c.client_id:
        raise click.UsageError("Not configured. Run `freeagent-cli auth init`.")
    if not c.refresh_token:
        raise click.UsageError("Not authenticated. Run `freeagent-cli auth login`.")
    return FreeAgent(c)


def parse_hours(s: str) -> float:
    """Parse a duration: 1.5, 90m, 1h, 1h30m, 1:30."""
    s = s.strip().lower()
    try:
        return float(s)
    except ValueError:
        pass
    if ":" in s:
        h, m = s.split(":", 1)
        return int(h) + int(m) / 60
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+)m)?", s)
    if m and (m.group(1) or m.group(2)):
        total = float(m.group(1) or 0)
        total += int(m.group(2) or 0) / 60
        return total
    raise ValueError(f"Cannot parse duration {s!r}; try 1.5, 90m, 1h30m, or 1:30")


def format_hours(value) -> str:
    """Format a decimal-hours value as 40m / 1h / 1h30m, rounding to the nearest minute."""
    try:
        total_min = round(float(value) * 60)
    except (TypeError, ValueError):
        return str(value)
    if total_min == 0:
        return "0m"
    h, m = divmod(total_min, 60)
    if h == 0:
        return f"{m}m"
    if m == 0:
        return f"{h}h"
    return f"{h}h{m}m"


def _resolve(items: list[dict], query: str, label: str) -> dict:
    if query.startswith("http"):
        match = [i for i in items if i["url"] == query]
        if match:
            return match[0]
    if query.isdigit():
        match = [i for i in items if i["url"].rsplit("/", 1)[-1] == query]
        if match:
            return match[0]
    q = query.lower()
    matches = [i for i in items if q in i["name"].lower()]
    if not matches:
        names = ", ".join(i["name"] for i in items) or "(none)"
        raise click.UsageError(f"No {label} matches {query!r}. Available: {names}")
    if len(matches) > 1:
        names = ", ".join(m["name"] for m in matches)
        raise click.UsageError(f"Multiple {label}s match {query!r}: {names}")
    return matches[0]


def _pick_task(tasks: list[dict], task_q: str | None, project_name: str) -> dict:
    if task_q:
        return _resolve(tasks, task_q, "task")
    if not tasks:
        raise click.UsageError(f"Project {project_name!r} has no tasks.")
    if len(tasks) == 1:
        return tasks[0]
    names = ", ".join(t["name"] for t in tasks)
    raise click.UsageError(
        f"--task required for {project_name!r}. Available: {names}"
    )


@click.group(epilog="""
\b
Typical flow:
  freeagent-cli recent                            # check what you've already logged (avoids duplicates)
  freeagent-cli log <project> <duration> [comment]  [--task <name>] [--dry-run]
  freeagent-cli projects                          # first-time / discovery: projects + tasks

\b
Examples:
  freeagent-cli log Acme 1h30m "fixed the thing"
  freeagent-cli log "Big Co" 90m --task Coding
  freeagent-cli log Acme 1.5 --dry-run

\b
Time formats: 1.5  90m  1h30m  1:30
Project/task: numeric id, full URL, or case-insensitive name substring.
--task is optional only when the project has a single task; otherwise the error lists the choices.
""")
def main():
    """FreeAgent CLI."""


# -- auth ----------------------------------------------------------------

@main.group()
def auth_grp():
    """Authentication commands."""


main.add_command(auth_grp, name="auth")


@auth_grp.command("init")
@click.option("--client-id", required=True)
@click.option("--client-secret", required=True)
@click.option("--sandbox/--production", default=False, help="Use sandbox API (default: production).")
@click.option("--redirect-uri", default=cfg.DEFAULT_REDIRECT, show_default=True)
def auth_init(client_id, client_secret, sandbox, redirect_uri):
    """Store OAuth client credentials."""
    c = cfg.load()
    c.client_id = client_id
    c.client_secret = client_secret
    c.redirect_uri = redirect_uri
    c.api_base = cfg.SANDBOX_BASE if sandbox else cfg.PROD_BASE
    cfg.save(c)
    click.echo(f"Saved → {cfg.config_path()}")
    click.echo("Next: `freeagent-cli auth login`")


@auth_grp.command("login")
def auth_login():
    """Run the browser OAuth flow and store a refresh token."""
    c = cfg.load()
    if not c.client_id:
        raise click.UsageError("Run `freeagent-cli auth init` first.")
    auth.login(c)
    click.echo("Authenticated.")


@auth_grp.command("status")
def auth_status():
    """Show authentication status."""
    c = cfg.load()
    click.echo(f"Config:  {cfg.config_path()}")
    click.echo(f"API:     {c.api_base}")
    click.echo(f"Client:  {'set' if c.client_id else 'missing'}")
    click.echo(f"Refresh: {'present' if c.refresh_token else 'missing'}")


# -- me ------------------------------------------------------------------

@main.command()
def me():
    """Show the authenticated user."""
    u = _api().me()
    click.echo(f"{u.get('first_name','')} {u.get('last_name','')} <{u.get('email','')}>")
    click.echo(u["url"])


# -- projects / tasks ----------------------------------------------------

@main.command()
@click.option("--all", "show_all", is_flag=True, help="Include inactive projects.")
@click.option("--tasks/--no-tasks", "with_tasks", default=True,
              help="Include tasks for each project (default: yes).")
@click.option("--flat", is_flag=True,
              help="One project/task pair per line for grep (tab-separated).")
def projects(show_all, with_tasks, flat):
    """List projects (and their tasks, by default)."""
    api = _api()
    view = "all" if show_all else "active"
    for p in api.projects(view=view):
        pid = p["url"].rsplit("/", 1)[-1]
        if not with_tasks:
            click.echo(f"{pid}\t{p['name']}")
            continue
        ts = api.tasks(p["url"])
        if flat:
            if not ts:
                click.echo(f"{pid}\t{p['name']}\t\t")
            for t in ts:
                tid = t["url"].rsplit("/", 1)[-1]
                click.echo(f"{pid}\t{p['name']}\t{tid}\t{t['name']}")
        else:
            click.echo(f"{pid}\t{p['name']}")
            for t in ts:
                tid = t["url"].rsplit("/", 1)[-1]
                click.echo(f"\t{tid}\t{t['name']}")


@main.command()
@click.option("--project", "project_q", required=True, help="Project name substring, id, or URL.")
def tasks(project_q):
    """List tasks for a project."""
    api = _api()
    project = _resolve(api.projects(view="active"), project_q, "project")
    for t in api.tasks(project["url"]):
        tid = t["url"].rsplit("/", 1)[-1]
        click.echo(f"{tid}\t{t['name']}")


# -- log -----------------------------------------------------------------

@main.command()
@click.argument("project_q", metavar="PROJECT")
@click.argument("duration", metavar="HOURS")
@click.argument("comment_parts", nargs=-1, metavar="[COMMENT...]")
@click.option("--task", "task_q", default=None,
              help="Task name substring, id, or URL. Optional only if the project has a single task.")
@click.option("--date", "date_", default=None, help="YYYY-MM-DD (default: today).")
@click.option("--dry-run", is_flag=True, help="Resolve and preview, but don't submit.")
def log(project_q, duration, comment_parts, task_q, date_, dry_run):
    """Submit a timeslip: PROJECT HOURS [COMMENT...].

    \b
    Examples:
      freeagent-cli log Acme 1h30m "fixed the thing"
      freeagent-cli log Acme 90m fixed the thing       # comment without quotes
      freeagent-cli log "Big Co" 1.5 --task Coding --date 2026-05-01

    Tip: run `freeagent-cli recent` first to avoid duplicate entries.
    """
    try:
        hours = parse_hours(duration)
    except ValueError as e:
        raise click.UsageError(str(e))
    comment = " ".join(comment_parts) if comment_parts else None

    api = _api()
    project = _resolve(api.projects(view="active"), project_q, "project")
    task = _pick_task(api.tasks(project["url"]), task_q, project["name"])
    dated_on = date_ or _dt.date.today().isoformat()

    if dry_run:
        click.echo(f"DRY RUN — would submit {format_hours(hours)} on {dated_on} → {project['name']} / {task['name']}")
        click.echo(f"  project: {project['url']}")
        click.echo(f"  task:    {task['url']}")
        if comment:
            click.echo(f"  comment: {comment}")
        return

    user_url = api.me()["url"]
    result = api.create_timeslip(
        user=user_url, project=project["url"], task=task["url"],
        dated_on=dated_on, hours=hours, comment=comment,
    )
    ts = result["timeslips"][0] if "timeslips" in result else result.get("timeslip", result)
    click.echo(f"Submitted {format_hours(hours)} on {dated_on} → {project['name']} / {task['name']}")
    if isinstance(ts, dict) and "url" in ts:
        click.echo(ts["url"])


# -- recent --------------------------------------------------------------

@main.command()
@click.option("-n", "limit", default=5, show_default=True, help="How many entries to show.")
@click.option("--days", default=14, show_default=True, help="Look back this many days.")
@click.option("--all-users", is_flag=True, help="Include other users (default: just you).")
def recent(limit, days, all_users):
    """Show recent timeslips (most recent first)."""
    api = _api()
    from_date = (_dt.date.today() - _dt.timedelta(days=days)).isoformat()
    user_url = None if all_users else api.me()["url"]
    slips = api.list_timeslips(from_date=from_date, user=user_url, nested=True)
    slips.sort(
        key=lambda t: (t.get("dated_on", ""), t.get("created_at", "")),
        reverse=True,
    )
    if not slips:
        click.echo(f"(no timeslips in the last {days} days)")
        return
    for s in slips[:limit]:
        proj = s.get("project")
        task_ = s.get("task")
        pname = proj["name"] if isinstance(proj, dict) else "?"
        tname = task_["name"] if isinstance(task_, dict) else "?"
        comment = (s.get("comment") or "").replace("\n", " ")
        click.echo(f"{s.get('dated_on','?')}\t{format_hours(s.get('hours'))}\t{pname}\t{tname}\t{comment}")


if __name__ == "__main__":
    main()
