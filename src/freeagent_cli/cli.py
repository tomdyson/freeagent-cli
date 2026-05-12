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


class _HoursType(click.ParamType):
    name = "duration"

    def convert(self, value, param, ctx):
        try:
            return parse_hours(value)
        except ValueError as e:
            self.fail(str(e), param, ctx)


HOURS = _HoursType()


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
Typical flow (for agents/scripts):
  freeagent-cli projects list                 # projects + tasks in one call
  freeagent-cli time submit --project <name> --hours 1h30m [--task <name>] [--comment "..."] [--dry-run]

\b
Time formats accepted: 1.5  90m  1h30m  1:30
Project/task selection: numeric id, full URL, or case-insensitive name substring.
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


# -- me / projects / tasks -----------------------------------------------

@main.command()
def me():
    """Show the authenticated user."""
    u = _api().me()
    click.echo(f"{u.get('first_name','')} {u.get('last_name','')} <{u.get('email','')}>")
    click.echo(u["url"])


@main.group()
def projects():
    """Project commands."""


@projects.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include inactive projects.")
@click.option("--tasks/--no-tasks", "with_tasks", default=True,
              help="Include tasks for each project (default: yes).")
def projects_list(show_all, with_tasks):
    """List projects (and their tasks, by default)."""
    api = _api()
    view = "all" if show_all else "active"
    for p in api.projects(view=view):
        pid = p["url"].rsplit("/", 1)[-1]
        click.echo(f"{pid}\t{p['name']}")
        if with_tasks:
            for t in api.tasks(p["url"]):
                tid = t["url"].rsplit("/", 1)[-1]
                click.echo(f"\t{tid}\t{t['name']}")


@main.group()
def tasks():
    """Task commands."""


@tasks.command("list")
@click.option("--project", "project_q", required=True, help="Project name substring, id, or URL.")
def tasks_list(project_q):
    api = _api()
    project = _resolve(api.projects(view="active"), project_q, "project")
    for t in api.tasks(project["url"]):
        tid = t["url"].rsplit("/", 1)[-1]
        click.echo(f"{tid}\t{t['name']}")


# -- time submit ---------------------------------------------------------

@main.group()
def time():
    """Timeslip commands."""


@time.command("submit")
@click.option("--project", "project_q", required=True, help="Project name substring, id, or URL.")
@click.option("--task", "task_q", default=None,
              help="Task name substring, id, or URL. Optional only if the project has a single task.")
@click.option("--hours", required=True, type=HOURS,
              help="Duration: 1.5, 90m, 1h30m, 1:30, etc.")
@click.option("--date", "date_", default=None, help="YYYY-MM-DD (default: today).")
@click.option("--comment", default=None)
@click.option("--dry-run", is_flag=True, help="Resolve and preview, but don't submit.")
def time_submit(project_q, task_q, hours, date_, comment, dry_run):
    """Submit a timeslip."""
    api = _api()
    project = _resolve(api.projects(view="active"), project_q, "project")
    task = _pick_task(api.tasks(project["url"]), task_q, project["name"])
    dated_on = date_ or _dt.date.today().isoformat()

    if dry_run:
        click.echo(f"DRY RUN — would submit {hours}h on {dated_on} → {project['name']} / {task['name']}")
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
    click.echo(f"Submitted {hours}h on {dated_on} → {project['name']} / {task['name']}")
    if isinstance(ts, dict) and "url" in ts:
        click.echo(ts["url"])


if __name__ == "__main__":
    main()
