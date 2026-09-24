from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from PIL import Image

from vectorai_bench.release_gate import LOCKED_G2_CASE_IDS, build_e6_release_report


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    roots = tuple(
        tmp_path / f"{name}" for name in ("g2", "g3", "g4", "g2-repeat", "g3-repeat", "g4-repeat")
    )
    g2, g3, g4, g2_repeat, g3_repeat, g4_repeat = roots
    evidence = [
        {
            "case_id": case,
            "observations": [{"renderer": name} for name in ("chromium", "inkscape", "resvg")],
        }
        for case in sorted(LOCKED_G2_CASE_IDS)
    ]
    for root, name, digest in (
        (g2, "g2", "a" * 64),
        (g3, "g3", "b" * 64),
        (g4, "g4", "c" * 64),
        (g2_repeat, "g2", "a" * 64),
        (g3_repeat, "g3", "b" * 64),
        (g4_repeat, "g4", "c" * 64),
    ):
        payload: dict[str, object] = {"semantic_digest": digest, "evaluation": {"passed": True}}
        if name == "g2":
            payload["renderer_evidence"] = evidence
        _json(root / f"{name}-report.json", payload)
    for case in sorted(LOCKED_G2_CASE_IDS):
        target = g2 / "runs" / case / "engine"
        target.mkdir(parents=True)
        transparent = Image.new("RGBA", (12, 12), (255, 0, 0, 0))
        opaque = Image.new("RGBA", (12, 12), (255, 255, 255, 255))
        transparent.save(target / "preview.png")
        transparent.save(target / "preview-inkscape.png")
        opaque.save(target / "preview-chromium.png")
        names = ("preview.png", "preview-inkscape.png", "preview-chromium.png")
        _json(
            target / "run-manifest.json",
            {
                "auxiliary_renderers": [
                    {"name": name, "status": "success"} for name in ("inkscape", "chromium")
                ],
                "artifacts": [
                    {
                        "name": name,
                        "sha256": hashlib.sha256((target / name).read_bytes()).hexdigest(),
                    }
                    for name in names
                ],
            },
        )
    return g2, g3, g4, g2_repeat, g3_repeat, g4_repeat


def test_release_gate_composites_white_and_checks_repeat(tmp_path: Path) -> None:
    g2, g3, g4, g2_repeat, g3_repeat, g4_repeat = _fixture(tmp_path)
    report = build_e6_release_report(
        g2,
        g3,
        g4,
        g2_repeat=g2_repeat,
        g3_repeat=g3_repeat,
        g4_repeat=g4_repeat,
    )
    evaluation = report["evaluation"]
    assert isinstance(evaluation, dict)
    assert evaluation["passed"]
    assert evaluation["renderer_pair_count"] == 51
    assert evaluation["maximum_renderer_rmse"] == 0.0
    pairs = report["renderer_pairs"]
    assert isinstance(pairs, list)
    typed_pairs = cast(list[dict[str, object]], pairs)
    assert any(item["raw_alpha_rmse_observation"] == 1.0 for item in typed_pairs)
    assert report == build_e6_release_report(
        g2,
        g3,
        g4,
        g2_repeat=g2_repeat,
        g3_repeat=g3_repeat,
        g4_repeat=g4_repeat,
    )


def test_release_gate_fails_closed_on_incomplete_locked_corpus(tmp_path: Path) -> None:
    g2, g3, g4, g2_repeat, g3_repeat, g4_repeat = _fixture(tmp_path)
    report_path = g2 / "g2-report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["renderer_evidence"].pop()
    _json(report_path, payload)
    report = build_e6_release_report(
        g2,
        g3,
        g4,
        g2_repeat=g2_repeat,
        g3_repeat=g3_repeat,
        g4_repeat=g4_repeat,
    )
    evaluation = report["evaluation"]
    assert isinstance(evaluation, dict)
    assert not evaluation["passed"]
    assert not evaluation["complete_renderer_matrix"]
    assert evaluation["renderer_pair_count"] == 48


def test_release_gate_fails_when_artifact_or_repeat_is_wrong(tmp_path: Path) -> None:
    g2, g3, g4, g2_repeat, g3_repeat, g4_repeat = _fixture(tmp_path)
    target = g2 / "runs" / "multicolor-02" / "engine"
    Image.new("RGBA", (12, 12), (0, 0, 0, 255)).save(target / "preview.png")
    report = build_e6_release_report(
        g2,
        g3,
        g4,
        g2_repeat=g2_repeat,
        g3_repeat=g3_repeat,
        g4_repeat=g4_repeat,
    )
    evaluation = report["evaluation"]
    assert isinstance(evaluation, dict)
    assert not evaluation["passed"]
    assert not evaluation["complete_renderer_matrix"]
    _json(
        g3_repeat / "g3-report.json", {"semantic_digest": "d" * 64, "evaluation": {"passed": True}}
    )
    report = build_e6_release_report(
        g2,
        g3,
        g4,
        g2_repeat=g2_repeat,
        g3_repeat=g3_repeat,
        g4_repeat=g4_repeat,
    )
    evaluation = report["evaluation"]
    assert isinstance(evaluation, dict)
    assert not evaluation["repeat_digests_match"]
    with pytest.raises(ValueError):
        build_e6_release_report(g2, g3, g4, renderer_rmse_limit=0.0)
