from __future__ import annotations

import httpx

from . import auth
from . import config as cfg


class FreeAgent:
    def __init__(self, c: cfg.Config):
        self.cfg = c

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.cfg.api_base,
            headers={
                "Authorization": f"Bearer {auth.access_token(self.cfg)}",
                "Accept": "application/json",
                "User-Agent": "freeagent-cli/0.2",
            },
            timeout=30,
        )

    def get(self, path: str, **params) -> dict:
        with self._client() as c:
            r = c.get(path, params=params)
            r.raise_for_status()
            return r.json()

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
        return self.get("/v2/projects", view=view).get("projects", [])

    def tasks(self, project_url: str) -> list[dict]:
        return self.get("/v2/tasks", project=project_url).get("tasks", [])

    def list_timeslips(self, *, from_date: str, to_date: str | None = None,
                       user: str | None = None, nested: bool = False) -> list[dict]:
        params: dict = {"from_date": from_date}
        if to_date:
            params["to_date"] = to_date
        if user:
            params["user"] = user
        if nested:
            params["nested"] = "true"
        return self.get("/v2/timeslips", **params).get("timeslips", [])

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
