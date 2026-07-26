from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from freeagent_cli.cli import main
from freeagent_cli.config import Config


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_config():
    c = Config()
    c.client_id = "test-id"
    c.client_secret = "test-secret"
    c.refresh_token = "test-refresh"
    c.access_token = "test-access"
    c.access_token_expires_at = 9999999999.0
    return c


@pytest.fixture
def mock_api():
    return MagicMock()


def _mock_api_and_config(api_mock, config):
    api_mock.me.return_value = {"url": "/v2/users/me"}
    api_mock.projects.return_value = [
        {"name": "Acme", "url": "/v2/projects/1"},
        {"name": "Big Co", "url": "/v2/projects/2"},
    ]
    api_mock.tasks.return_value = [
        {"name": "Coding", "url": "/v2/tasks/1"},
        {"name": "Design", "url": "/v2/tasks/2"},
    ]


class TestDelete:
    def test_delete_confirmed(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = {
            "url": "/v2/timeslips/42",
            "hours": "2.5",
            "dated_on": "2026-05-15",
            "comment": "test work",
            "project": {"name": "Acme", "url": "/v2/projects/1"},
            "task": {"name": "Coding", "url": "/v2/tasks/1"},
        }
        mock_api.delete_timeslip.return_value = {"deleted": True, "id": "42", "already_deleted": False}

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["delete", "42"], input="y\n")
            assert result.exit_code == 0
            assert "Acme / Coding" in result.output
            assert "2026-05-15" in result.output
            assert "Deleted" in result.output

    def test_delete_aborted(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = {
            "url": "/v2/timeslips/42",
            "hours": "2.5",
            "dated_on": "2026-05-15",
            "comment": "test work",
            "project": {"name": "Acme", "url": "/v2/projects/1"},
            "task": {"name": "Coding", "url": "/v2/tasks/1"},
        }

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["delete", "42"], input="n\n")
            assert result.exit_code == 1

    def test_delete_yes_flag_skips_confirm(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = {
            "url": "/v2/timeslips/42",
            "hours": "2.5",
            "dated_on": "2026-05-15",
            "comment": "test work",
            "project": {"name": "Acme", "url": "/v2/projects/1"},
            "task": {"name": "Coding", "url": "/v2/tasks/1"},
        }
        mock_api.delete_timeslip.return_value = {"deleted": True, "id": "42", "already_deleted": False}

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["delete", "42", "--yes"])
            assert result.exit_code == 0
            assert "Deleted" in result.output

    def test_delete_by_url(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = {
            "url": "/v2/timeslips/42",
            "hours": "1.0",
            "dated_on": "2026-05-14",
            "comment": "",
            "project": {"name": "Big Co", "url": "/v2/projects/2"},
            "task": {"name": "Design", "url": "/v2/tasks/2"},
        }
        mock_api.delete_timeslip.return_value = {"deleted": True, "id": "42", "already_deleted": False}

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["delete", "https://api.freeagent.com/v2/timeslips/42", "--yes"])
            assert result.exit_code == 0
            mock_api.get_timeslip.assert_called_once_with("42")
            mock_api.delete_timeslip.assert_called_once_with("42")

    def test_delete_already_deleted(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.side_effect = Exception("not found")

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["delete", "999", "--yes"])
            assert result.exit_code == 2
            assert "not found" in result.output


class TestEdit:
    def _old_timeslip(self):
        return {
            "url": "/v2/timeslips/42",
            "hours": "2.5",
            "dated_on": "2026-05-15",
            "comment": "test work",
            "project": {"name": "Acme", "url": "/v2/projects/1"},
            "task": {"name": "Coding", "url": "/v2/tasks/1"},
        }

    def test_edit_duration(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = self._old_timeslip()
        mock_api.create_timeslip.return_value = {
            "timeslip": {"url": "/v2/timeslips/43", "hours": "1.0", "dated_on": "2026-05-15"}
        }
        mock_api.delete_timeslip.return_value = {"deleted": True, "id": "42", "already_deleted": False}

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["edit", "42", "--duration", "1h", "--yes"])
            assert result.exit_code == 0
            assert "2h30m → 1h" in result.output
            mock_api.create_timeslip.assert_called_once()
            mock_api.delete_timeslip.assert_called_once_with("42")

    def test_edit_dry_run(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = self._old_timeslip()

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["edit", "42", "--duration", "1h", "--dry-run"])
            assert result.exit_code == 0
            assert "2h30m → 1h" in result.output
            mock_api.create_timeslip.assert_not_called()
            mock_api.delete_timeslip.assert_not_called()

    def test_edit_no_changes(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = self._old_timeslip()

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["edit", "42"])
            assert result.exit_code == 2
            assert "Nothing to change" in result.output

    def test_edit_project_with_matching_task(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = self._old_timeslip()

        def _tasks(project_url):
            if "/projects/2" in project_url:
                return [
                    {"name": "Coding", "url": "/v2/tasks/3"},
                    {"name": "Testing", "url": "/v2/tasks/4"},
                ]
            return [
                {"name": "Coding", "url": "/v2/tasks/1"},
                {"name": "Design", "url": "/v2/tasks/2"},
            ]

        mock_api.tasks.side_effect = _tasks
        mock_api.create_timeslip.return_value = {
            "timeslip": {"url": "/v2/timeslips/43", "hours": "2.5", "dated_on": "2026-05-15"}
        }
        mock_api.delete_timeslip.return_value = {"deleted": True, "id": "42", "already_deleted": False}

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["edit", "42", "--project", "Big Co", "--yes"])
            assert result.exit_code == 0
            assert "Acme → Big Co" in result.output

    def test_edit_project_task_not_found_requires_flag(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = self._old_timeslip()

        def _tasks(project_url):
            if "/projects/2" in project_url:
                return [
                    {"name": "Testing", "url": "/v2/tasks/4"},
                ]
            return [
                {"name": "Coding", "url": "/v2/tasks/1"},
            ]

        mock_api.tasks.side_effect = _tasks

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["edit", "42", "--project", "Big Co", "--yes"])
            assert result.exit_code == 2
            assert "--task required" in result.output

    def test_edit_aborted(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = self._old_timeslip()

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["edit", "42", "--duration", "3h"], input="n\n")
            assert result.exit_code == 1
            mock_api.create_timeslip.assert_not_called()

    def test_edit_timeslip_not_found(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.side_effect = Exception("not found")

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["edit", "999", "--duration", "2h"])
            assert result.exit_code == 2
            assert "not found" in result.output

    def test_edit_comment_blank(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.get_timeslip.return_value = self._old_timeslip()
        mock_api.create_timeslip.return_value = {
            "timeslip": {"url": "/v2/timeslips/43"}
        }
        mock_api.delete_timeslip.return_value = {"deleted": True, "id": "42", "already_deleted": False}

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["edit", "42", "--comment", "", "--yes"])
            assert result.exit_code == 0
            assert "'test work' → ''" in result.output


class TestRecent:
    def test_recent_includes_url(self, runner, mock_config, mock_api):
        _mock_api_and_config(mock_api, mock_config)
        mock_api.list_timeslips.return_value = [
            {
                "url": "/v2/timeslips/42",
                "hours": "2.5",
                "dated_on": "2026-05-15",
                "created_at": "2026-05-15T10:00:00Z",
                "comment": "test work",
                "project": {"name": "Acme"},
                "task": {"name": "Coding"},
            }
        ]

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["recent"])
            assert result.exit_code == 0
            assert "/v2/timeslips/42" in result.output


ACCOUNTS = [
    {"url": "/v2/bank_accounts/1", "name": "Current", "currency": "GBP",
     "current_balance": "1234.5", "status": "Active"},
    {"url": "/v2/bank_accounts/2", "name": "Savings", "currency": "GBP",
     "current_balance": "10.0", "status": "Active"},
    {"url": "/v2/bank_accounts/3", "name": "Old Card", "currency": "GBP",
     "current_balance": "0.0", "status": "Hidden"},
]


class TestAccounts:
    def test_lists_active_only(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = ACCOUNTS

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["accounts"])

        assert result.exit_code == 0
        assert "1\tCurrent\tGBP\t1234.50" in result.output
        assert "Old Card" not in result.output

    def test_all_includes_hidden(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = ACCOUNTS

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["accounts", "--all"])

        assert result.exit_code == 0
        assert "Old Card" in result.output

    def test_no_accounts(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = []

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["accounts"])

        assert result.exit_code == 0
        assert "(no bank accounts)" in result.output


class TestUnexplained:
    def test_requires_account_when_ambiguous(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = ACCOUNTS

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["unexplained"])

        assert result.exit_code != 0
        assert "--account required" in result.output
        assert "Current, Savings" in result.output

    def test_single_account_is_implicit(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = [ACCOUNTS[0]]
        mock_api.bank_transactions.return_value = []

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["unexplained"])

        assert result.exit_code == 0
        assert "nothing unexplained on Current" in result.output
        assert mock_api.bank_transactions.call_args.kwargs["view"] == "unexplained"

    def test_lists_most_recent_first_with_summary(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = ACCOUNTS
        mock_api.bank_transactions.return_value = [
            {"url": "/v2/bank_transactions/1", "dated_on": "2026-05-01",
             "amount": "-20.0", "unexplained_amount": "-20.0",
             "description": "Older", "matching_transactions_count": 0},
            {"url": "/v2/bank_transactions/2", "dated_on": "2026-06-01",
             "amount": "-42.5", "unexplained_amount": "-42.5",
             "description": "Newer", "matching_transactions_count": 3},
        ]

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["unexplained", "--account", "Current"])

        assert result.exit_code == 0
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        assert lines[0].startswith("2026-06-01\t-42.50\tNewer\t3\t")
        assert lines[1].startswith("2026-05-01\t-20.00\tOlder\t0\t")
        assert "2 unexplained on Current, total -62.50 GBP" in result.stderr

    def test_partial_marker(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = [ACCOUNTS[0]]
        mock_api.bank_transactions.return_value = [
            {"url": "/v2/bank_transactions/1", "dated_on": "2026-06-01",
             "amount": "-100.0", "unexplained_amount": "-40.0",
             "description": "Part done", "matching_transactions_count": 0},
        ]

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["unexplained"])

        assert result.exit_code == 0
        assert "-40.00\tPart done\t0\tpartial\t" in result.stdout

    def test_limit_truncates_and_says_so(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = [ACCOUNTS[0]]
        mock_api.bank_transactions.return_value = [
            {"url": f"/v2/bank_transactions/{i}", "dated_on": f"2026-06-{i:02d}",
             "amount": "-1.0", "unexplained_amount": "-1.0",
             "description": f"txn {i}", "matching_transactions_count": 0}
            for i in range(1, 11)
        ]

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["unexplained", "-n", "3"])

        assert result.exit_code == 0
        assert len([ln for ln in result.stdout.splitlines() if ln.strip()]) == 3
        assert "showing 3 — use -n 0 for all" in result.stderr

    def test_days_zero_means_no_date_filter(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = [ACCOUNTS[0]]
        mock_api.bank_transactions.return_value = []

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["unexplained", "--days", "0"])

        assert result.exit_code == 0
        assert mock_api.bank_transactions.call_args.kwargs["from_date"] is None

    def test_named_hidden_account_still_resolves(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = ACCOUNTS
        mock_api.bank_transactions.return_value = []

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["unexplained", "--account", "Old Card"])

        assert result.exit_code == 0
        assert mock_api.bank_transactions.call_args.kwargs["bank_account"] == "/v2/bank_accounts/3"

    def test_unknown_account_lists_choices(self, runner, mock_config, mock_api):
        mock_api.bank_accounts.return_value = ACCOUNTS

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["unexplained", "--account", "Nope"])

        assert result.exit_code != 0
        assert "No bank account matches 'Nope'" in result.output


CATEGORIES = [
    {"url": "/v2/categories/285", "nominal_code": "285",
     "description": "Accommodation and Meals", "group": "admin_expenses"},
    {"url": "/v2/categories/286", "nominal_code": "286",
     "description": "Travel", "group": "admin_expenses"},
    {"url": "/v2/categories/001", "nominal_code": "001",
     "description": "Sales", "group": "income"},
]

TXN = {
    "url": "/v2/bank_transactions/5",
    "dated_on": "2026-06-01",
    "amount": "-42.5",
    "unexplained_amount": "-42.5",
    "description": "STRIPE PAYOUT",
}


def _mock_explain(api_mock, txn=None, categories=None):
    api_mock.bank_transaction.return_value = dict(txn or TXN)
    api_mock.categories.return_value = categories or CATEGORIES
    api_mock.create_explanation.return_value = {
        "bank_transaction_explanation": {"url": "/v2/bank_transaction_explanations/9"}
    }


class TestCategories:
    def test_lists_all(self, runner, mock_config, mock_api):
        mock_api.categories.return_value = CATEGORIES

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["categories"])

        assert result.exit_code == 0
        assert "285\tadmin_expenses\tAccommodation and Meals" in result.output

    def test_search_filters(self, runner, mock_config, mock_api):
        mock_api.categories.return_value = CATEGORIES

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["categories", "--search", "trav"])

        assert result.exit_code == 0
        assert "Travel" in result.output
        assert "Sales" not in result.output

    def test_group_filters(self, runner, mock_config, mock_api):
        mock_api.categories.return_value = CATEGORIES

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["categories", "--group", "income"])

        assert result.exit_code == 0
        assert "Sales" in result.output
        assert "Travel" not in result.output

    def test_no_match(self, runner, mock_config, mock_api):
        mock_api.categories.return_value = CATEGORIES

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["categories", "--search", "zzz"])

        assert result.exit_code == 0
        assert "(no matching categories)" in result.output


class TestExplain:
    def test_full_amount_by_default(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "285"], input="y\n")

        assert result.exit_code == 0
        assert mock_api.create_explanation.call_args.kwargs == {
            "bank_transaction": "/v2/bank_transactions/5",
            "dated_on": "2026-06-01",
            "gross_value": "-42.50",
            "category": "/v2/categories/285",
            "description": None,
        }
        assert "Explained." in result.output

    def test_partial_amount_keeps_transaction_sign(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            # A positive --amount on a money-out transaction must stay negative.
            result = runner.invoke(main, ["explain", "5", "285", "--amount", "20"], input="y\n")

        assert result.exit_code == 0
        assert mock_api.create_explanation.call_args.kwargs["gross_value"] == "-20.00"
        assert "-22.50 still unexplained" in result.output

    def test_amount_strips_currency_symbols(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "285", "--amount", "£20.00"], input="y\n")

        assert result.exit_code == 0
        assert mock_api.create_explanation.call_args.kwargs["gross_value"] == "-20.00"

    def test_money_in_stays_positive(self, runner, mock_config, mock_api):
        _mock_explain(mock_api, txn={**TXN, "amount": "100.0", "unexplained_amount": "100.0"})

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "001", "--amount", "-40"], input="y\n")

        assert result.exit_code == 0
        assert mock_api.create_explanation.call_args.kwargs["gross_value"] == "40.00"

    def test_amount_over_unexplained_rejected(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "285", "--amount", "100"])

        assert result.exit_code != 0
        assert "exceeds the 42.50 still unexplained" in result.output
        mock_api.create_explanation.assert_not_called()

    def test_fully_explained_transaction_rejected(self, runner, mock_config, mock_api):
        _mock_explain(mock_api, txn={**TXN, "unexplained_amount": "0.0"})

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "285"])

        assert result.exit_code != 0
        assert "nothing left to explain" in result.output
        mock_api.create_explanation.assert_not_called()

    def test_dry_run_submits_nothing(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "285", "--dry-run"])

        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        mock_api.create_explanation.assert_not_called()

    def test_declining_confirmation_submits_nothing(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "285"], input="n\n")

        assert result.exit_code != 0
        mock_api.create_explanation.assert_not_called()

    def test_category_by_description(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "accommodation", "-y"])

        assert result.exit_code == 0
        assert mock_api.create_explanation.call_args.kwargs["category"] == "/v2/categories/285"

    def test_ambiguous_category_lists_codes(self, runner, mock_config, mock_api):
        _mock_explain(mock_api, categories=[
            {"url": "/v2/categories/285", "nominal_code": "285",
             "description": "Travel and Subsistence", "group": "admin_expenses"},
            {"url": "/v2/categories/286", "nominal_code": "286",
             "description": "Travel Insurance", "group": "admin_expenses"},
        ])

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "travel"])

        assert result.exit_code != 0
        assert "285 Travel and Subsistence" in result.output
        assert "286 Travel Insurance" in result.output
        mock_api.create_explanation.assert_not_called()

    def test_unknown_category_points_at_search(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "zzz"])

        assert result.exit_code != 0
        assert "categories --search zzz" in result.output

    def test_leading_zero_nominal_code(self, runner, mock_config, mock_api):
        _mock_explain(mock_api, txn={**TXN, "amount": "100.0", "unexplained_amount": "100.0"})

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "001", "-y"])

        assert result.exit_code == 0
        assert mock_api.create_explanation.call_args.kwargs["category"] == "/v2/categories/001"

    def test_accepts_full_url_and_date_override(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, [
                "explain", "https://api.freeagent.com/v2/bank_transactions/5",
                "285", "--date", "2026-06-30", "--description", "note", "-y",
            ])

        assert result.exit_code == 0
        mock_api.bank_transaction.assert_called_once_with("5")
        kwargs = mock_api.create_explanation.call_args.kwargs
        assert kwargs["dated_on"] == "2026-06-30"
        assert kwargs["description"] == "note"

    def test_missing_transaction(self, runner, mock_config, mock_api):
        mock_api.bank_transaction.side_effect = Exception("404")

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "99", "285"])

        assert result.exit_code != 0
        assert "Bank transaction '99' not found" in result.output

    def test_like_copies_category(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)
        source = {
            "url": "/v2/bank_transactions/9", "dated_on": "2026-05-01",
            "description": "STRIPE PAYOUT", "amount": "-42.5",
            "unexplained_amount": "0.0",
            "bank_transaction_explanations": [
                {"url": "/v2/bank_transaction_explanations/8",
                 "category": "/v2/categories/286", "gross_value": "-42.5"},
            ],
        }
        mock_api.bank_transaction.side_effect = lambda tid: dict(TXN) if tid == "5" else source

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "--like", "9", "-y"])

        assert result.exit_code == 0
        assert mock_api.create_explanation.call_args.kwargs["category"] == "/v2/categories/286"
        assert "286 Travel  (from 2026-05-01 STRIPE PAYOUT)" in result.output
        # Category came from the nested payload, so no extra fetch was needed.
        mock_api.explanation.assert_not_called()

    def test_like_fetches_abridged_explanation(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)
        source = {
            "url": "/v2/bank_transactions/9", "dated_on": "2026-05-01",
            "description": "STRIPE PAYOUT",
            # Abridged: entry_type but no category URL.
            "bank_transaction_explanations": [
                {"url": "/v2/bank_transaction_explanations/8",
                 "entry_type": "Travel", "gross_value": "-42.5"},
            ],
        }
        mock_api.bank_transaction.side_effect = lambda tid: dict(TXN) if tid == "5" else source
        mock_api.explanation.return_value = {"category": "/v2/categories/286"}

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "--like", "9", "-y"])

        assert result.exit_code == 0
        mock_api.explanation.assert_called_once_with("8")
        assert mock_api.create_explanation.call_args.kwargs["category"] == "/v2/categories/286"

    def test_like_with_no_explanations_errors(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)
        source = {"url": "/v2/bank_transactions/9", "dated_on": "2026-05-01",
                  "description": "TRANSFER", "bank_transaction_explanations": []}
        mock_api.bank_transaction.side_effect = lambda tid: dict(TXN) if tid == "5" else source

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "--like", "9"])

        assert result.exit_code != 0
        assert "has no category to copy" in result.output
        mock_api.create_explanation.assert_not_called()

    def test_like_with_split_categories_errors(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)
        source = {
            "url": "/v2/bank_transactions/9", "dated_on": "2026-05-01",
            "description": "MIXED",
            "bank_transaction_explanations": [
                {"url": "/v2/bank_transaction_explanations/8", "category": "/v2/categories/285"},
                {"url": "/v2/bank_transaction_explanations/9", "category": "/v2/categories/286"},
            ],
        }
        mock_api.bank_transaction.side_effect = lambda tid: dict(TXN) if tid == "5" else source

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "--like", "9"])

        assert result.exit_code != 0
        assert "split across several categories" in result.output
        assert "285 Accommodation and Meals" in result.output
        mock_api.create_explanation.assert_not_called()

    def test_like_dedupes_repeated_category(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)
        source = {
            "url": "/v2/bank_transactions/9", "dated_on": "2026-05-01",
            "description": "SPLIT SAME",
            "bank_transaction_explanations": [
                {"url": "/v2/bank_transaction_explanations/8", "category": "/v2/categories/286"},
                {"url": "/v2/bank_transaction_explanations/9", "category": "/v2/categories/286"},
            ],
        }
        mock_api.bank_transaction.side_effect = lambda tid: dict(TXN) if tid == "5" else source

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "--like", "9", "-y"])

        assert result.exit_code == 0
        assert mock_api.create_explanation.call_args.kwargs["category"] == "/v2/categories/286"

    def test_like_missing_source_transaction(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)
        mock_api.bank_transaction.side_effect = (
            lambda tid: dict(TXN) if tid == "5" else (_ for _ in ()).throw(Exception("404"))
        )

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "--like", "99"])

        assert result.exit_code != 0
        assert "Bank transaction '99' not found" in result.output

    def test_category_and_like_together_rejected(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "285", "--like", "9"])

        assert result.exit_code != 0
        assert "not both" in result.output
        mock_api.create_explanation.assert_not_called()

    def test_neither_category_nor_like_rejected(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5"])

        assert result.exit_code != 0
        assert "Give a CATEGORY, or --like" in result.output
        mock_api.create_explanation.assert_not_called()

    def test_like_respects_partial_amount(self, runner, mock_config, mock_api):
        _mock_explain(mock_api)
        source = {
            "url": "/v2/bank_transactions/9", "dated_on": "2026-05-01",
            "description": "STRIPE PAYOUT",
            "bank_transaction_explanations": [
                {"url": "/v2/bank_transaction_explanations/8", "category": "/v2/categories/286"},
            ],
        }
        mock_api.bank_transaction.side_effect = lambda tid: dict(TXN) if tid == "5" else source

        with patch("freeagent_cli.cli.cfg.load", return_value=mock_config), \
             patch("freeagent_cli.cli.FreeAgent", return_value=mock_api):
            result = runner.invoke(main, ["explain", "5", "--like", "9", "--amount", "10", "-y"])

        assert result.exit_code == 0
        kwargs = mock_api.create_explanation.call_args.kwargs
        assert kwargs["gross_value"] == "-10.00"
        assert kwargs["category"] == "/v2/categories/286"
