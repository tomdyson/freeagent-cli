from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from freeagent_cli.api import FreeAgent
from freeagent_cli.config import Config


@pytest.fixture
def config():
    c = Config()
    c.client_id = "test-id"
    c.client_secret = "test-secret"
    c.refresh_token = "test-refresh"
    c.access_token = "test-access"
    c.access_token_expires_at = 9999999999.0
    return c


@pytest.fixture
def api(config):
    return FreeAgent(config)


def _page(items_key, items, next_url=None):
    """A mock response for one page of a list endpoint."""
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = {items_key: items}
    r.links = {"next": {"url": next_url}} if next_url else {}
    return r


class TestGetAll:
    def test_single_page(self, api):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = _page("projects", [{"name": "Acme"}])

        with patch.object(api, "_client", return_value=mock_client):
            assert api.get_all("/v2/projects", "projects") == [{"name": "Acme"}]

        mock_client.get.assert_called_once_with("/v2/projects", params={"per_page": 100})

    def test_follows_next_link(self, api):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.side_effect = [
            _page("projects", [{"name": "A"}], next_url="https://api.freeagent.com/v2/projects?page=2"),
            _page("projects", [{"name": "B"}], next_url="https://api.freeagent.com/v2/projects?page=3"),
            _page("projects", [{"name": "C"}]),
        ]

        with patch.object(api, "_client", return_value=mock_client):
            result = api.get_all("/v2/projects", "projects", view="active")

        assert [p["name"] for p in result] == ["A", "B", "C"]
        assert mock_client.get.call_count == 3
        # First call carries params; subsequent calls use the next URL verbatim.
        first, second, third = mock_client.get.call_args_list
        assert first.args[0] == "/v2/projects"
        assert first.kwargs["params"] == {"view": "active", "per_page": 100}
        assert second.args[0] == "https://api.freeagent.com/v2/projects?page=2"
        assert second.kwargs["params"] is None
        assert third.args[0] == "https://api.freeagent.com/v2/projects?page=3"

    def test_drops_none_params(self, api):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = _page("timeslips", [])

        with patch.object(api, "_client", return_value=mock_client):
            api.get_all("/v2/timeslips", "timeslips", from_date="2026-01-01", user=None)

        assert mock_client.get.call_args.kwargs["params"] == {
            "from_date": "2026-01-01", "per_page": 100,
        }

    def test_missing_key_yields_empty(self, api):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = _page("something_else", [{"a": 1}])

        with patch.object(api, "_client", return_value=mock_client):
            assert api.get_all("/v2/projects", "projects") == []

    def test_runaway_link_chain_raises(self, api):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        # Every page claims there's another one.
        mock_client.get.return_value = _page("projects", [{"name": "A"}], next_url="/v2/projects?page=2")

        with patch.object(api, "_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Stopped after 100 pages"):
                api.get_all("/v2/projects", "projects")


class TestBanking:
    def test_bank_accounts(self, api):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = _page(
            "bank_accounts", [{"name": "Current", "url": "/v2/bank_accounts/1"}]
        )

        with patch.object(api, "_client", return_value=mock_client):
            assert api.bank_accounts()[0]["name"] == "Current"

        mock_client.get.assert_called_once_with("/v2/bank_accounts", params={"per_page": 100})

    def test_bank_transactions_passes_required_account(self, api):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = _page("bank_transactions", [])

        with patch.object(api, "_client", return_value=mock_client):
            api.bank_transactions(
                bank_account="/v2/bank_accounts/1", view="unexplained", from_date="2026-01-01",
            )

        assert mock_client.get.call_args.kwargs["params"] == {
            "bank_account": "/v2/bank_accounts/1",
            "view": "unexplained",
            "from_date": "2026-01-01",
            "per_page": 100,
        }


class TestDeleteTimeslip:
    def test_delete_success(self, api):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"timeslip": {"url": "/v2/timeslips/42"}}
        mock_client.__enter__.return_value = mock_client
        mock_client.delete.return_value = mock_response

        with patch.object(api, "_client", return_value=mock_client):
            result = api.delete_timeslip("42")
            assert result == {"timeslip": {"url": "/v2/timeslips/42"}}
            mock_client.delete.assert_called_once_with("/v2/timeslips/42")

    def test_delete_404_returns_already_deleted(self, api):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_client.__enter__.return_value = mock_client

        error_response = MagicMock()
        error_response.status_code = 404
        error_response.text = "Not found"
        error = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=error_response)
        mock_client.delete.side_effect = error

        with patch.object(api, "_client", return_value=mock_client):
            result = api.delete_timeslip("42")
            assert result == {"deleted": True, "id": "42", "already_deleted": True}

    def test_delete_500_reraises(self, api):
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client

        error_response = MagicMock()
        error_response.status_code = 500
        error = httpx.HTTPStatusError("500 Server Error", request=MagicMock(), response=error_response)
        mock_client.delete.side_effect = error

        with patch.object(api, "_client", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                api.delete_timeslip("42")


class TestGetTimeslip:
    def test_get_timeslip(self, api):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "timeslip": {
                "url": "/v2/timeslips/42",
                "hours": "2.5",
                "dated_on": "2026-05-15",
                "comment": "test work",
                "project": {"name": "Acme", "url": "/v2/projects/1"},
                "task": {"name": "Coding", "url": "/v2/tasks/1"},
            }
        }
        mock_client.__enter__.return_value = mock_client
        mock_client.get.return_value = mock_response

        with patch.object(api, "_client", return_value=mock_client):
            result = api.get_timeslip("42")
            assert result["url"] == "/v2/timeslips/42"
            assert result["hours"] == "2.5"
            mock_client.get.assert_called_once_with("/v2/timeslips/42", params={"nested": "true"})


class TestDelete:
    def test_delete_generic(self, api):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"status": "ok"}
        mock_client.__enter__.return_value = mock_client
        mock_client.delete.return_value = mock_response

        with patch.object(api, "_client", return_value=mock_client):
            result = api.delete("/v2/some/resource")
            assert result == {"status": "ok"}
            mock_client.delete.assert_called_once_with("/v2/some/resource")
