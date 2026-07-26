from __future__ import annotations

import httpx

from . import __version__
from . import auth
from . import config as cfg

#: FreeAgent caps per_page at 100; asking for the maximum keeps round trips down.
PER_PAGE = 100

#: Safety valve so a runaway Link chain can't loop forever. 100 pages = 10,000 records.
MAX_PAGES = 100


class FreeAgent:
    def __init__(self, c: cfg.Config):
        self.cfg = c

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.cfg.api_base,
            headers={
                "Authorization": f"Bearer {auth.access_token(self.cfg)}",
                "Accept": "application/json",
                "User-Agent": f"freeagent-cli/{__version__}",
            },
            timeout=30,
        )

    def get(self, path: str, **params) -> dict:
        with self._client() as c:
            r = c.get(path, params=params)
            r.raise_for_status()
            return r.json()

    def get_all(self, path: str, key: str, **params) -> list[dict]:
        """GET a list endpoint, following `Link: rel="next"` until exhausted.

        FreeAgent returns 25 records per page by default, so anything that reads a
        single response silently truncates. Params with a value of None are dropped.
        """
        query = {k: v for k, v in params.items() if v is not None}
        query.setdefault("per_page", PER_PAGE)
        items: list[dict] = []
        with self._client() as c:
            url = path
            # Only the first request needs params; each `next` URL carries its own.
            request_params: dict | None = query
            for _ in range(MAX_PAGES):
                r = c.get(url, params=request_params)
                r.raise_for_status()
                items.extend(r.json().get(key, []))
                next_link = r.links.get("next")
                if not next_link:
                    return items
                url = next_link["url"]
                request_params = None
        raise RuntimeError(
            f"Stopped after {MAX_PAGES} pages of {path}; narrow the date range."
        )

    def post(self, path: str, json_body: dict) -> dict:
        with self._client() as c:
            r = c.post(path, json=json_body)
            if r.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"{r.status_code} {r.reason_phrase}: {r.text}",
                    request=r.request, response=r,
                )
            return r.json()

    def me(self) -> dict:
        return self.get("/v2/users/me")["user"]

    def projects(self, view: str = "active") -> list[dict]:
        return self.get_all("/v2/projects", "projects", view=view)

    def tasks(self, project_url: str) -> list[dict]:
        return self.get_all("/v2/tasks", "tasks", project=project_url)

    def list_timeslips(self, *, from_date: str, to_date: str | None = None,
                       user: str | None = None, nested: bool = False) -> list[dict]:
        return self.get_all(
            "/v2/timeslips", "timeslips",
            from_date=from_date, to_date=to_date, user=user,
            nested="true" if nested else None,
        )

    def create_timeslip(self, *, user: str, project: str, task: str,
                        dated_on: str, hours: float, comment: str | None = None) -> dict:
        body: dict = {
            "timeslip": {
                "user": user,
                "project": project,
                "task": task,
                "dated_on": dated_on,
                "hours": str(hours),
            }
        }
        if comment:
            body["timeslip"]["comment"] = comment
        return self.post("/v2/timeslips", body)

    # -- banking ---------------------------------------------------------

    def bank_accounts(self, view: str | None = None) -> list[dict]:
        return self.get_all("/v2/bank_accounts", "bank_accounts", view=view)

    def bank_transactions(self, *, bank_account: str, view: str = "all",
                          from_date: str | None = None,
                          to_date: str | None = None) -> list[dict]:
        """List transactions for one account. `bank_account` is required by the API."""
        return self.get_all(
            "/v2/bank_transactions", "bank_transactions",
            bank_account=bank_account, view=view,
            from_date=from_date, to_date=to_date,
        )

    def bank_transaction(self, txn_id: str) -> dict:
        return self.get(f"/v2/bank_transactions/{txn_id}")["bank_transaction"]

    def categories(self) -> list[dict]:
        """Flatten the four parallel category arrays into one list.

        The API groups categories into `admin_expenses_categories`,
        `cost_of_sales_categories`, `income_categories` and `general_categories`.
        Each entry is tagged with the group it came from. Note that categories
        name themselves with `description`, not `name`, and are keyed by nominal
        code — which can carry a leading zero, e.g. "001".
        """
        data = self.get("/v2/categories", per_page=PER_PAGE)
        out: list[dict] = []
        for group, items in data.items():
            if not group.endswith("_categories") or not isinstance(items, list):
                continue
            label = group[: -len("_categories")]
            out.extend({**c, "group": label} for c in items)
        return out

    def create_explanation(self, *, bank_transaction: str, dated_on: str,
                           gross_value: str, category: str,
                           description: str | None = None) -> dict:
        """Explain (part of) a bank transaction against a category.

        Sales-tax fields are deliberately omitted so FreeAgent applies the
        category's automatic rate rather than this CLI guessing at VAT.
        """
        body: dict = {
            "bank_transaction_explanation": {
                "bank_transaction": bank_transaction,
                "dated_on": dated_on,
                "gross_value": gross_value,
                "category": category,
            }
        }
        if description:
            body["bank_transaction_explanation"]["description"] = description
        return self.post("/v2/bank_transaction_explanations", body)

    def delete(self, path: str) -> dict:
        with self._client() as c:
            r = c.delete(path)
            r.raise_for_status()
            return r.json()

    def delete_timeslip(self, timeslip_id: str) -> dict:
        try:
            return self.delete(f"/v2/timeslips/{timeslip_id}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"deleted": True, "id": timeslip_id, "already_deleted": True}
            raise

    def get_timeslip(self, timeslip_id: str) -> dict:
        return self.get(f"/v2/timeslips/{timeslip_id}", nested="true")["timeslip"]
