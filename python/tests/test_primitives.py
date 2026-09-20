from __future__ import annotations

import math

import pytest

from vectorai_engine.errors import EngineFailure
from vectorai_engine.primitives import (
    PrimitiveKind,
    fit_arc,
    fit_circle,
    fit_ellipse,
    fit_line,
    fit_rectangle,
    fit_rounded_rectangle,
    recover_closed_primitives,
)


def rotate(point: tuple[float, float], angle: float) -> tuple[float, float]:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return (
        cosine * point[0] - sine * point[1] + 12.0,
        sine * point[0] + cosine * point[1] - 7.0,
    )


def ellipse_points(
    radius_x: float, radius_y: float, angle: float, count: int = 128
) -> tuple[tuple[float, float], ...]:
    return tuple(
        rotate(
            (
                radius_x * math.cos(2.0 * math.pi * index / count),
                radius_y * math.sin(2.0 * math.pi * index / count),
            ),
            angle,
        )
        for index in range(count)
    )


def rounded_rectangle_points(
    half_width: float, half_height: float, radius: float, angle: float
) -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    centers = (
        (half_width - radius, half_height - radius, 0.0),
        (-half_width + radius, half_height - radius, math.pi / 2.0),
        (-half_width + radius, -half_height + radius, math.pi),
        (half_width - radius, -half_height + radius, 3.0 * math.pi / 2.0),
    )
    for center_x, center_y, start in centers:
        for step in range(17):
            theta = start + step * math.pi / 32.0
            points.append(
                rotate(
                    (
                        center_x + radius * math.cos(theta),
                        center_y + radius * math.sin(theta),
                    ),
                    angle,
                )
            )
    return tuple(points)


def angular_error(first: float, second: float) -> float:
    return min(abs(first - second), abs(first - second + math.pi), abs(first - second - math.pi))


def test_line_and_circle_parameter_recovery() -> None:
    line_points = tuple((float(index), 2.0 * index + 3.0) for index in range(-5, 6))
    line = fit_line(line_points)
    assert line.kind is PrimitiveKind.LINE
    assert line.error < 1.0e-10

    circle = fit_circle(ellipse_points(9.0, 9.0, 0.0))
    assert circle.center == pytest.approx((12.0, -7.0), abs=1.0e-9)
    assert circle.radius_x == pytest.approx(9.0, abs=1.0e-9)
    assert circle.error < 1.0e-9


def test_rotated_ellipse_and_elliptical_arc_recovery() -> None:
    angle = 0.47
    points = ellipse_points(11.0, 4.0, angle)
    ellipse = fit_ellipse(points)
    assert ellipse.kind is PrimitiveKind.ELLIPSE
    assert ellipse.center == pytest.approx((12.0, -7.0), abs=1.0e-9)
    assert ellipse.radius_x == pytest.approx(11.0, abs=1.0e-9)
    assert ellipse.radius_y == pytest.approx(4.0, abs=1.0e-9)
    assert angular_error(ellipse.rotation_radians, angle) < 1.0e-9
    assert ellipse.error < 1.0e-9

    arc_points = tuple(points[:33])
    arc = fit_arc(arc_points, elliptical=True)
    assert arc.kind is PrimitiveKind.ELLIPTICAL_ARC
    assert arc.radius_x > arc.radius_y > 0.0
    assert abs(arc.end_angle - arc.start_angle) > 1.0


def test_rotated_rectangle_and_rounded_radius_recovery() -> None:
    angle = 0.31
    rectangle_points = tuple(
        rotate(point, angle)
        for point in (
            (-8.0, -4.0),
            (8.0, -4.0),
            (8.0, 4.0),
            (-8.0, 4.0),
        )
    )
    rectangle = fit_rectangle(rectangle_points)
    assert rectangle.kind is PrimitiveKind.RECTANGLE
    assert rectangle.error < 1.0e-9
    assert sorted((rectangle.radius_x, rectangle.radius_y)) == pytest.approx([4.0, 8.0])

    rounded_points = rounded_rectangle_points(10.0, 6.0, 2.5, angle)
    rounded = fit_rounded_rectangle(rounded_points)
    assert rounded.kind is PrimitiveKind.ROUNDED_RECTANGLE
    assert rounded.center == pytest.approx((12.0, -7.0), abs=1.0e-6)
    assert rounded.corner_radius == pytest.approx(2.5, abs=0.06)
    assert rounded.error < 0.06
    recovered = recover_closed_primitives(rounded_points, tolerance=0.2)
    assert recovered.selected.kind is PrimitiveKind.ROUNDED_RECTANGLE


def test_circle_recovery_prefers_primitive_over_polyline() -> None:
    result = recover_closed_primitives(ellipse_points(7.0, 7.0, 0.0), tolerance=0.1)
    assert result.selected.kind is PrimitiveKind.CIRCLE
    assert result.selected.complexity < result.candidates[-1].complexity


def test_degenerate_ellipse_is_rejected() -> None:
    points = tuple((float(index), 0.0) for index in range(8))
    with pytest.raises(EngineFailure):
        fit_ellipse(points)
