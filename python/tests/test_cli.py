from __future__ import annotations

import json

from vectorai_cli.__main__ import main


def test_doctor_emits_machine_readable_environment(capsys: object) -> None:
    assert main(["doctor"]) == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert payload["vectorai_version"] == "0.1.0"
    assert payload["platform"] in {"windows", "linux", "darwin"}
    assert payload["python_version"]
    assert payload["machine"]
