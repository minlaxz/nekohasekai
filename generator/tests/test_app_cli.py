from typing import Any

import pytest
from typer.testing import CliRunner
from generator import app

runner = CliRunner()


def test_generate_cli_calls_main(monkeypatch: pytest.MonkeyPatch):
    called: Any = {}

    def fake_main(**kwargs: Any):
        called.update(kwargs)

    monkeypatch.setattr(app, "main", fake_main)

    result = runner.invoke(app.app, ["--local", "--debug"])

    assert result.exit_code == 0
    assert called["local_mode"] is True
