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
