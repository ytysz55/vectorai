from __future__ import annotations

from pathlib import Path

from vectorai_cli.errors import EngineError, ErrorCode, RunStatus, Stage

ROOT = Path(__file__).resolve().parents[2]
CPP_ERROR_SOURCE = ROOT / "cpp" / "src" / "core" / "error.cpp"


def test_python_error_contract_matches_cpp_wire_values() -> None:
    cpp_source = CPP_ERROR_SOURCE.read_text(encoding="utf-8")
    wire_values = [
        *(item.value for item in ErrorCode),
        *(item.value for item in Stage),
        *(item.value for item in RunStatus),
    ]
    for value in wire_values:
        assert f'"{value}"' in cpp_source


def test_engine_error_is_immutable_and_serializable_by_field() -> None:
    error = EngineError(
        code=ErrorCode.DECODE_ERROR,
        stage=Stage.DECODE,
        message="invalid image payload",
        context={"media_type": "image/png"},
    )
    assert error.code.value == "DECODE_ERROR"
    assert error.stage.value == "decode"
    assert not error.retryable
    assert error.context == {"media_type": "image/png"}
