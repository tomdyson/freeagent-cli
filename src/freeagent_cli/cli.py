from __future__ import annotations

import datetime as _dt
import math as _math
import re

import click
import httpx

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


def _extract_id(query: str) -> str:
    return query.rsplit("/", 1)[-1] if "/" in query else query


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


def format_amount(value) -> str:
    """Format a money value as a plain signed decimal (no thousands separator, for awk)."""
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


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


def _fetch_txn(api, txn_id: str) -> dict:
    """Fetch a bank transaction, distinguishing "missing" from "went wrong".

    A bare `except Exception` here would report an expired token or a 500 as
    "not found", sending you after the wrong problem.
    """
    try:
        return api.bank_transaction(txn_id)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 404:
            raise click.UsageError(f"Bank transaction {txn_id!r} not found.")
        if status in (401, 403):
            raise click.UsageError(
                f"FreeAgent refused the request ({status}). "
                "Check `freeagent-cli auth status`, and that your app has Banking access."
            )
        raise click.UsageError(f"FreeAgent returned {status} for transaction {txn_id}.")
    except httpx.RequestError as e:
        raise click.UsageError(f"Could not reach FreeAgent: {e}")


def _category_label(cat: dict) -> str:
    return f"{cat.get('nominal_code','?')} {cat.get('description','?')}"


def _pick_category(cats: list[dict], query: str) -> dict:
    """Resolve a category by nominal code, URL, or description substring.

    Kept separate from `_resolve` because categories key off `description`, and
    because a company has ~100 of them — listing them all on a miss is useless,
    so misses point at `categories --search` instead.
    """
    # Match on the trailing segment so absolute and relative URLs behave alike.
    key = _extract_id(query) if "/" in query else query
    if key:
        match = [c for c in cats if c["url"] == query or c["url"].rsplit("/", 1)[-1] == key]
        if match:
            return match[0]
    q = query.lower()
    matches = [c for c in cats if q in (c.get("description") or "").lower()]
    if not matches:
        raise click.UsageError(
            f"No category matches {query!r}. "
            f"Browse with `freeagent-cli categories --search {query}`."
        )
    if len(matches) > 1:
        shown = "; ".join(_category_label(c) for c in matches[:10])
        more = f"; … and {len(matches) - 10} more" if len(matches) > 10 else ""
        raise click.UsageError(
            f"Multiple categories match {query!r}: {shown}{more}. "
            "Use the nominal code to pick one."
        )
    return matches[0]


def _categories_used_by(api, txn: dict) -> list[str]:
    """Distinct category URLs across a transaction's existing explanations.

    Nested explanations can arrive abridged — carrying `entry_type` but no
    `category` URL — so fall back to fetching the full explanation object.
    Order is preserved so error messages read predictably.
    """
    urls: list[str] = []
    for exp in txn.get("bank_transaction_explanations") or []:
        if not isinstance(exp, dict):
            continue
        cat = exp.get("category")
        if not cat and exp.get("url"):
            cat = api.explanation(_extract_id(exp["url"])).get("category")
        if cat and cat not in urls:
            urls.append(cat)
    return urls


def _category_like(api, like_q: str, cats: list[dict]) -> tuple[dict, dict]:
    """Resolve the category used by another transaction. Returns (category, source txn)."""
    source_id = _extract_id(like_q)
    source = _fetch_txn(api, source_id)
    used = _categories_used_by(api, source)
    by_url = {c["url"]: c for c in cats}

    if not used:
        raise click.UsageError(
            f"Transaction {source_id} has no category to copy. "
            "Invoice payments, bill payments and transfers aren't categorised, "
            "so --like can't read one from them."
        )
    if len(used) > 1:
        shown = "; ".join(_category_label(by_url.get(u, {"description": u})) for u in used)
        raise click.UsageError(
            f"Transaction {source_id} is split across several categories: {shown}. "
            "Pass a CATEGORY explicitly."
        )

    url = used[0]
    # A category can be missing from the list if it's been archived since.
    return by_url.get(url, {"url": url, "nominal_code": _extract_id(url),
                            "description": "(unlisted category)"}), source


def parse_amount(s: str) -> float:
    """Parse a money amount, ignoring currency symbols, commas and sign.

    The sign is discarded on purpose: `explain` always takes it from the
    transaction, so a partial explanation can't flip money out into money in.
    """
    cleaned = re.sub(r"[^0-9.]", "", s)
    try:
        return abs(float(cleaned))
    except ValueError:
        raise ValueError(f"Cannot parse amount {s!r}; try 42.50")


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


def _active_accounts(accounts: list[dict]) -> list[dict]:
    """Drop hidden accounts. Treat a missing status as active."""
    return [a for a in accounts if (a.get("status") or "active").lower() != "hidden"]


def _pick_account(accounts: list[dict], account_q: str | None) -> dict:
    """Resolve --account, or fall back to the only active account.

    An explicitly named account resolves against every account, so you can still
    reach a hidden one; the implicit default only ever considers active accounts.
    """
    if account_q:
        return _resolve(accounts, account_q, "bank account")
    active = _active_accounts(accounts)
    if not active:
        raise click.UsageError("No active bank accounts found.")
    if len(active) == 1:
        return active[0]
    names = ", ".join(a["name"] for a in active)
    raise click.UsageError(f"--account required. Available: {names}")


@click.group(epilog="""
\b
Typical flow:
  freeagent-cli recent                            # check what you've already logged (avoids duplicates)
  freeagent-cli log <project> <duration> [comment]  [--task <name>] [--dry-run]
  freeagent-cli projects                          # first-time / discovery: projects + tasks

\b
Banking:
  freeagent-cli accounts                          # bank accounts + balances
  freeagent-cli unexplained [--account <name>]    # transactions still needing an explanation
  freeagent-cli categories --search travel        # find a category to explain against
  freeagent-cli explain <txn> <category> [--dry-run]
  freeagent-cli explain <txn> --like <other txn>  # reuse a category for a recurring payee

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
        click.echo(f"{s.get('dated_on','?')}\t{format_hours(s.get('hours'))}\t{pname}\t{tname}\t{comment}\t{s.get('url','')}")


# -- banking -------------------------------------------------------------

@main.command()
@click.option("--all", "show_all", is_flag=True, help="Include hidden accounts.")
def accounts(show_all):
    """List bank accounts (id, name, currency, balance)."""
    api = _api()
    accs = api.bank_accounts()
    if not show_all:
        accs = _active_accounts(accs)
    if not accs:
        click.echo("(no bank accounts)")
        return
    for a in accs:
        aid = a["url"].rsplit("/", 1)[-1]
        click.echo(
            f"{aid}\t{a.get('name','?')}\t{a.get('currency','')}\t"
            f"{format_amount(a.get('current_balance'))}"
        )


@main.command()
@click.option("--account", "account_q", default=None,
              help="Bank account name substring, id, or URL. Optional if you have one account.")
@click.option("--days", default=90, show_default=True,
              help="Look back this many days (0 for no date limit).")
@click.option("-n", "limit", default=25, show_default=True,
              help="How many to show (0 for all).")
def unexplained(account_q, days, limit):
    """Show unexplained bank transactions (most recent first).

    \b
    Output is tab-separated: date, unexplained amount, description, count of
    similar transactions, marker, URL. The marker reads `partial` when only
    part of the transaction has been explained. A summary goes to stderr, so
    piping stdout stays clean.

    \b
    Examples:
      freeagent-cli unexplained
      freeagent-cli unexplained --account Current --days 365
      freeagent-cli unexplained -n 0 | grep -i stripe
    """
    api = _api()
    account = _pick_account(api.bank_accounts(), account_q)
    from_date = (
        (_dt.date.today() - _dt.timedelta(days=days)).isoformat() if days else None
    )
    txns = api.bank_transactions(
        bank_account=account["url"], view="unexplained", from_date=from_date,
    )
    txns.sort(key=lambda t: (t.get("dated_on", ""), t.get("created_at", "")), reverse=True)

    if not txns:
        window = f" in the last {days} days" if days else ""
        click.echo(f"(nothing unexplained on {account['name']}{window})")
        return

    shown = txns if limit == 0 else txns[:limit]
    for t in shown:
        unex = t.get("unexplained_amount", t.get("amount"))
        desc = (t.get("description") or "").replace("\n", " ").replace("\t", " ")
        similar = t.get("matching_transactions_count") or 0
        marker = "partial" if _is_partial(t) else ""
        click.echo(
            f"{t.get('dated_on','?')}\t{format_amount(unex)}\t{desc}\t"
            f"{similar}\t{marker}\t{t.get('url','')}"
        )

    total = sum(_unexplained_value(t) for t in txns)
    summary = (
        f"{len(txns)} unexplained on {account['name']}, "
        f"total {format_amount(total)} {account.get('currency','')}".rstrip()
    )
    if len(shown) < len(txns):
        summary += f" (showing {len(shown)} — use -n 0 for all)"
    click.echo(summary, err=True)


@main.command()
@click.option("--search", "search", default=None, help="Filter by description substring.")
@click.option("--group", "group", default=None,
              help="Filter by group: admin_expenses, cost_of_sales, income, general.")
def categories(search, group):
    """List spending/income categories (nominal code, group, description)."""
    api = _api()
    cats = api.categories()
    if group:
        g = group.lower()
        cats = [c for c in cats if g in c.get("group", "").lower()]
    if search:
        q = search.lower()
        cats = [c for c in cats if q in (c.get("description") or "").lower()]
    if not cats:
        click.echo("(no matching categories)")
        return
    for c in cats:
        click.echo(
            f"{c.get('nominal_code','?')}\t{c.get('group','')}\t{c.get('description','?')}"
        )


@main.command()
@click.argument("txn_q", metavar="TRANSACTION_ID_OR_URL")
@click.argument("category_q", metavar="[CATEGORY]", required=False)
@click.option("--like", "like_q", default=None, metavar="TRANSACTION",
              help="Reuse the category from another transaction, instead of CATEGORY.")
@click.option("--amount", "amount_str", default=None,
              help="Explain only part of it (default: the whole unexplained amount).")
@click.option("--description", "description", default=None, help="Note on the explanation.")
@click.option("--date", "date_", default=None,
              help="YYYY-MM-DD (default: the transaction's own date).")
@click.option("--dry-run", is_flag=True, help="Resolve and preview, but don't submit.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def explain(txn_q, category_q, like_q, amount_str, description, date_, dry_run, yes):
    """Explain a bank transaction: TRANSACTION CATEGORY.

    \b
    CATEGORY matches by nominal code, URL, or description substring.
    Run `freeagent-cli categories --search travel` to find one.

    \b
    Instead of CATEGORY, --like reuses the category from a transaction you've
    already explained — handy for a payee that recurs every month. The
    `similar` column in `unexplained` tells you when that's likely to help.

    \b
    Examples:
      freeagent-cli explain 12345 285
      freeagent-cli explain 12345 "Accommodation and Meals" --description "client dinner"
      freeagent-cli explain 12345 285 --amount 20 --dry-run
      freeagent-cli explain 12345 --like 9999

    \b
    VAT is left to FreeAgent's automatic rate for the category; this command
    doesn't set sales-tax fields. Override in the web UI if you need to.
    """
    if category_q and like_q:
        raise click.UsageError("Use CATEGORY or --like, not both.")
    if not category_q and not like_q:
        raise click.UsageError(
            "Give a CATEGORY, or --like <transaction> to copy one. "
            "Browse with `freeagent-cli categories --search <text>`."
        )

    api = _api()
    tid = _extract_id(txn_q)
    txn = _fetch_txn(api, tid)

    unexplained_amt = _unexplained_value(txn)
    if unexplained_amt == 0:
        raise click.UsageError(
            f"Transaction {tid} has nothing left to explain."
        )

    if amount_str is None:
        gross = unexplained_amt
    else:
        try:
            magnitude = parse_amount(amount_str)
        except ValueError as e:
            raise click.UsageError(str(e))
        if magnitude == 0:
            raise click.UsageError("--amount must be non-zero.")
        # Sign always comes from the transaction, never from the user.
        gross = _math.copysign(magnitude, unexplained_amt)
        if magnitude > abs(unexplained_amt) + 0.005:
            raise click.UsageError(
                f"--amount {format_amount(magnitude)} exceeds the "
                f"{format_amount(abs(unexplained_amt))} still unexplained."
            )

    cats = api.categories()
    if like_q:
        cat, source = _category_like(api, like_q, cats)
        source_desc = (source.get("description") or "").replace("\n", " ")
        provenance = f"  (from {source.get('dated_on','?')} {source_desc})"
    else:
        cat = _pick_category(cats, category_q)
        provenance = ""
    dated_on = date_ or txn.get("dated_on", "")

    desc = (txn.get("description") or "").replace("\n", " ")
    click.echo(f"Explain {txn.get('dated_on','?')}  {desc}")
    click.echo(f"  Amount:   {format_amount(gross)} of "
               f"{format_amount(unexplained_amt)} unexplained")
    click.echo(f"  Category: {_category_label(cat)}{provenance}")
    click.echo(f"  Date:     {dated_on}")
    if description:
        click.echo(f"  Note:     {description}")
    click.echo("  VAT:      FreeAgent's automatic rate for this category")

    if dry_run:
        click.echo("DRY RUN — nothing submitted.")
        return

    if not yes:
        click.confirm("Submit this explanation?", abort=True)

    result = api.create_explanation(
        bank_transaction=txn["url"], dated_on=dated_on,
        gross_value=f"{gross:.2f}", category=cat["url"], description=description,
    )
    remaining = unexplained_amt - gross
    if abs(remaining) >= 0.005:
        click.echo(f"Explained. {format_amount(remaining)} still unexplained.")
    else:
        click.echo("Explained.")
    exp = result.get("bank_transaction_explanation", result)
    if isinstance(exp, dict) and "url" in exp:
        click.echo(exp["url"])


def _unexplained_value(txn: dict) -> float:
    """The still-unexplained amount as a float, falling back to the full amount.

    Junk counts as 0.0 rather than raising: `format_amount` already degrades to
    printing the raw value per line, so the summary shouldn't be the one thing
    that aborts the command after the table has been printed.
    """
    raw = txn.get("unexplained_amount")
    if raw is None or raw == "":
        raw = txn.get("amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _is_partial(txn: dict) -> bool:
    """True when some of the transaction is explained and some isn't."""
    try:
        return float(txn["unexplained_amount"]) != float(txn["amount"])
    except (KeyError, TypeError, ValueError):
        return False


# -- delete --------------------------------------------------------------

@main.command()
@click.argument("timeslip_q", metavar="TIMESLIP_ID_OR_URL")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def delete(timeslip_q, yes):
    """Delete a timeslip by numeric ID or full URL."""
    api = _api()
    tid = _extract_id(timeslip_q)
    try:
        ts = api.get_timeslip(tid)
    except Exception:
        raise click.UsageError(f"Timeslip {tid!r} not found.")
    proj = ts.get("project")
    task_ = ts.get("task")
    pname = proj["name"] if isinstance(proj, dict) else "?"
    tname = task_["name"] if isinstance(task_, dict) else "?"
    comment = (ts.get("comment") or "")[:80]
    click.echo(f"{ts.get('dated_on','?')}  {format_hours(ts.get('hours'))}  {pname} / {tname}")
    if comment:
        click.echo(f"  {comment}")
    if not yes:
        click.confirm("Delete this timeslip?", abort=True)
    result = api.delete_timeslip(tid)
    if result.get("already_deleted"):
        click.echo("Timeslip already deleted.")
    else:
        click.echo("Deleted.")
    click.echo(ts.get("url", ""))


# -- edit ----------------------------------------------------------------

@main.command()
@click.argument("timeslip_q", metavar="TIMESLIP_ID_OR_URL")
@click.option("--project", "project_q", default=None,
              help="New project (name substring, id, or URL).")
@click.option("--task", "task_q", default=None,
              help="New task (name substring, id, or URL).")
@click.option("--duration", "duration_str", default=None,
              help="New duration (1.5, 90m, 1h30m, 1:30).")
@click.option("--date", "date_", default=None, help="New date YYYY-MM-DD.")
@click.option("--comment", "comment", default=None, help="New comment.")
@click.option("--dry-run", is_flag=True, help="Resolve and preview, but don't submit.")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation.")
def edit(timeslip_q, project_q, task_q, duration_str, date_, comment, dry_run, yes):
    """Edit a timeslip: fetch, apply changes, delete old, create new.

    \b
    Only the options you pass are changed; everything else stays the same.
    If you change --project, --task defaults to a matching task name in the new
    project if one exists, otherwise you must pass --task explicitly.

    \b
    Examples:
      freeagent-cli edit 123456 --duration 2h
      freeagent-cli edit https://api.freeagent.com/v2/timeslips/123456 --comment "done"
      freeagent-cli edit 123456 --project "Big Co" --task Coding --dry-run
    """
    api = _api()
    tid = _extract_id(timeslip_q)
    try:
        old = api.get_timeslip(tid)
    except Exception:
        raise click.UsageError(f"Timeslip {tid!r} not found.")

    if not any([project_q, task_q, duration_str, date_, comment is not None]):
        raise click.UsageError("Nothing to change. Use --help to see options.")

    old_proj = old.get("project")
    old_task = old.get("task")

    new_project_url = old_proj["url"] if isinstance(old_proj, dict) else ""
    new_task_url = old_task["url"] if isinstance(old_task, dict) else ""
    new_hours = float(old.get("hours", 0))
    new_date = old.get("dated_on", "")
    new_comment = old.get("comment") or ""

    old_pname = old_proj["name"] if isinstance(old_proj, dict) else "?"
    old_tname = old_task["name"] if isinstance(old_task, dict) else "?"
    new_pname = old_pname
    new_tname = old_tname

    if project_q:
        new_proj = _resolve(api.projects(view="active"), project_q, "project")
        new_project_url = new_proj["url"]
        new_pname = new_proj["name"]
        if not task_q:
            new_tasks = api.tasks(new_project_url)
            matches = [t for t in new_tasks if t["name"].lower() == old_tname.lower()]
            if len(matches) == 1:
                new_task_url = matches[0]["url"]
                new_tname = matches[0]["name"]
            else:
                names = ", ".join(t["name"] for t in new_tasks) or "(none)"
                raise click.UsageError(
                    f"Project changed; --task required. Available in {new_proj['name']!r}: {names}"
                )

    if task_q:
        proj_tasks = api.tasks(new_project_url)
        new_task = _resolve(proj_tasks, task_q, "task")
        new_task_url = new_task["url"]
        new_tname = new_task["name"]

    if duration_str:
        try:
            new_hours = parse_hours(duration_str)
        except ValueError as e:
            raise click.UsageError(str(e))

    if date_:
        new_date = date_

    if comment is not None:
        new_comment = comment

    lines = []
    lines.append("Before → After")
    lines.append(f"  Project:  {old_pname} → {new_pname}")
    lines.append(f"  Task:     {old_tname} → {new_tname}")
    lines.append(f"  Date:     {old.get('dated_on','?')} → {new_date}")
    lines.append(f"  Duration: {format_hours(old.get('hours'))} → {format_hours(new_hours)}")
    lines.append(f"  Comment:  {repr(old.get('comment') or '')} → {repr(new_comment)}")
    click.echo("\n".join(lines))

    if dry_run:
        return

    if not yes:
        click.confirm("Proceed with edit?", abort=True)

    user_url = api.me()["url"]
    result = api.create_timeslip(
        user=user_url, project=new_project_url, task=new_task_url,
        dated_on=new_date, hours=new_hours, comment=new_comment or None,
    )
    ts = result["timeslips"][0] if "timeslips" in result else result.get("timeslip", result)
    api.delete_timeslip(tid)
    click.echo(f"Edited → {new_pname} / {new_tname}{' --dry-run' if dry_run else ''}")
    if isinstance(ts, dict) and "url" in ts:
        click.echo(ts["url"])


if __name__ == "__main__":
    main()
