from __future__ import annotations

import pytest

from freeagent_cli.cli import _extract_id, format_hours, parse_hours


class TestParseHours:
    def test_decimal(self):
        assert parse_hours("1.5") == 1.5
        assert parse_hours("0.25") == 0.25

    def test_minutes_only(self):
        assert parse_hours("90m") == 1.5
        assert parse_hours("30m") == 0.5
        assert parse_hours("0m") == 0.0

    def test_hours_only(self):
        assert parse_hours("1h") == 1.0
        assert parse_hours("2h") == 2.0

    def test_hours_and_minutes(self):
        assert parse_hours("1h30m") == 1.5
        assert parse_hours("2h15m") == 2.25
        assert parse_hours("0h45m") == 0.75

    def test_colon_format(self):
        assert parse_hours("1:30") == 1.5
        assert parse_hours("0:45") == 0.75
        assert parse_hours("2:00") == 2.0

    def test_case_insensitive(self):
        assert parse_hours("1H30M") == 1.5
        assert parse_hours("90M") == 1.5

    def test_whitespace(self):
        assert parse_hours("  1.5  ") == 1.5

    def test_invalid(self):
        with pytest.raises(ValueError, match="Cannot parse duration"):
            parse_hours("abc")
        with pytest.raises(ValueError, match="Cannot parse duration"):
            parse_hours("")

    def test_fractional_hours_with_minutes(self):
        assert parse_hours("1.5h30m") == 2.0


class TestFormatHours:
    def test_minutes_only(self):
        assert format_hours(0.5) == "30m"
        assert format_hours(0.25) == "15m"
        assert format_hours(0) == "0m"

    def test_hours_only(self):
        assert format_hours(1.0) == "1h"
        assert format_hours(2.0) == "2h"

    def test_hours_and_minutes(self):
        assert format_hours(1.5) == "1h30m"
        assert format_hours(2.25) == "2h15m"
        assert format_hours(0.75) == "45m"

    def test_rounding(self):
        assert format_hours(0.505) == "30m"
        assert format_hours(0.495) == "30m"

    def test_bad_input(self):
        assert format_hours(None) == "None"


class TestExtractId:
    def test_numeric_id(self):
        assert _extract_id("123456") == "123456"

    def test_full_url(self):
        assert _extract_id("https://api.freeagent.com/v2/timeslips/123456") == "123456"

    def test_sandbox_url(self):
        assert _extract_id("https://api.sandbox.freeagent.com/v2/timeslips/789") == "789"

    def test_url_with_query(self):
        assert _extract_id("https://api.freeagent.com/v2/timeslips/42?nested=true") == "42?nested=true"
