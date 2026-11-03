"""Rigid physical coordinate transforms shared by canonical producers."""

from forma_domain.stability_contracts import Point3


def transform_point(transform, point, *, inverse=False):
    p = [point.x, point.y, point.z]
    t = transform.translation_m
    offset = [t.x, t.y, t.z]
    r = transform.rotation
    values = (
        [sum(r[j][i] * (p[j] - offset[j]) for j in range(3)) for i in range(3)]
        if inverse
        else [sum(r[i][j] * p[j] for j in range(3)) + offset[i] for i in range(3)]
    )
    return Point3(x=values[0], y=values[1], z=values[2])
