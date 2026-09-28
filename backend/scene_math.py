"""Scene-graph math shared with the frontend.

Local TRS convention (identical to three.js Object3D):
- position: translation relative to parent
- rotation: Euler XYZ (intrinsic), radians
- scale: per-axis scale

Matrices are column-major flat lists of 16 floats, same byte layout as
THREE.Matrix4.elements, so frontend/backend results can be compared directly.
"""
from __future__ import annotations

import math
from typing import Iterable


def identity() -> list[float]:
    return [1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0]


def multiply(a: list[float], b: list[float]) -> list[float]:
    """Return a * b, column-major (same layout as THREE.Matrix4.multiply)."""
    out = [0.0] * 16
    for i in range(4):
        for j in range(4):
            out[i * 4 + j] = (
                a[0 * 4 + j] * b[i * 4 + 0]
                + a[1 * 4 + j] * b[i * 4 + 1]
                + a[2 * 4 + j] * b[i * 4 + 2]
                + a[3 * 4 + j] * b[i * 4 + 3]
            )
    return out


def compose(position: Iterable[float], rotation: Iterable[float],
            scale: Iterable[float]) -> list[float]:
    """TRS -> matrix, matching THREE.Matrix4.compose / Euler 'XYZ'."""
    x, y, z = rotation
    cx, sx = math.cos(x), math.sin(x)
    cy, sy = math.cos(y), math.sin(y)
    cz, sz = math.cos(z), math.sin(z)

    # three.js Matrix4.makeRotationFromEuler with order XYZ
    ae11 = cy * cz
    ae12 = -(cy * sz)
    ae13 = sy

    ae21 = sx * sy * cz + cx * sz
    ae22 = cx * cz - sx * sy * sz
    ae23 = -(sx * cy)

    ae31 = -(cx * sy * cz) + sx * sz
    ae32 = cx * sy * sz + sx * cz
    ae33 = cx * cy

    px, py, pz = list(position)
    kx, ky, kz = list(scale)
    return [
        ae11 * kx, ae21 * kx, ae31 * kx, 0.0,
        ae12 * ky, ae22 * ky, ae32 * ky, 0.0,
        ae13 * kz, ae23 * kz, ae33 * kz, 0.0,
        px, py, pz, 1.0,
    ]


def decompose(m: list[float]) -> tuple[list[float], list[float], list[float]]:
    """matrix -> TRS, matching THREE.Matrix4.decompose / Euler 'XYZ'."""
    sx = math.sqrt(m[0] * m[0] + m[1] * m[1] + m[2] * m[2])
    sy = math.sqrt(m[4] * m[4] + m[5] * m[5] + m[6] * m[6])
    sz = math.sqrt(m[8] * m[8] + m[9] * m[9] + m[10] * m[10])

    det = (
        m[0] * (m[5] * m[10] - m[6] * m[9])
        - m[4] * (m[1] * m[10] - m[2] * m[9])
        + m[8] * (m[1] * m[6] - m[2] * m[5])
    )
    if det < 0:
        sx = -sx

    if abs(sx) < 1e-10 or abs(sy) < 1e-10 or abs(sz) < 1e-10:
        rx = ry = rz = 0.0
    else:
        m11 = m[0] / sx
        m12 = m[4] / sy
        m13 = m[8] / sz
        m21 = m[1] / sx
        m22 = m[5] / sy
        m23 = m[9] / sz
        m32 = m[6] / sy
        m33 = m[10] / sz

        # Euler 'XYZ' extraction, identical to three.js Euler.setFromRotationMatrix
        ry = math.asin(max(-1.0, min(1.0, m13)))
        if abs(m13) < 0.9999999:
            rx = math.atan2(-m23, m33)
            rz = math.atan2(-m12, m11)
        else:
            rx = math.atan2(m32, m22)
            rz = 0.0

    return [m[12], m[13], m[14]], [rx, ry, rz], [sx, sy, sz]


def invert(m: list[float]) -> list[float]:
    """Invert an affine matrix (same general algorithm as three.js)."""
    n11, n21, n31, n41 = m[0], m[1], m[2], m[3]
    n12, n22, n32, n42 = m[4], m[5], m[6], m[7]
    n13, n23, n33, n43 = m[8], m[9], m[10], m[11]
    n14, n24, n34, n44 = m[12], m[13], m[14], m[15]

    t11 = n23 * n34 * n42 - n24 * n33 * n42 + n24 * n32 * n43 - n22 * n34 * n43 - n23 * n32 * n44 + n22 * n33 * n44
    t12 = n14 * n33 * n42 - n13 * n34 * n42 - n14 * n32 * n43 + n12 * n34 * n43 + n13 * n32 * n44 - n12 * n33 * n44
    t13 = n13 * n24 * n42 - n14 * n23 * n42 + n14 * n22 * n43 - n12 * n24 * n43 - n13 * n22 * n44 + n12 * n23 * n44
    t14 = n14 * n23 * n32 - n13 * n24 * n32 - n14 * n22 * n33 + n12 * n24 * n33 + n13 * n22 * n34 - n12 * n23 * n34

    det = n11 * t11 + n21 * t12 + n31 * t13 + n41 * t14
    if det == 0:
        return identity()
    di = 1.0 / det

    t21 = n24 * n33 * n41 - n23 * n34 * n41 - n24 * n31 * n43 + n21 * n34 * n43 + n23 * n31 * n44 - n21 * n33 * n44
    t22 = n13 * n34 * n41 - n14 * n33 * n41 + n14 * n31 * n43 - n11 * n34 * n43 - n13 * n31 * n44 + n11 * n33 * n44
    t23 = n14 * n23 * n41 - n13 * n24 * n41 - n14 * n21 * n43 + n11 * n24 * n43 + n13 * n21 * n44 - n11 * n23 * n44
    t24 = n13 * n24 * n31 - n14 * n23 * n31 + n14 * n21 * n33 - n11 * n24 * n33 - n13 * n21 * n34 + n11 * n23 * n34
    t31 = n22 * n34 * n41 - n24 * n32 * n41 + n24 * n31 * n42 - n21 * n34 * n42 - n22 * n31 * n44 + n21 * n32 * n44
    t32 = n14 * n32 * n41 - n12 * n34 * n41 - n14 * n31 * n42 + n11 * n34 * n42 + n12 * n31 * n44 - n11 * n32 * n44
    t33 = n12 * n24 * n41 - n14 * n22 * n41 + n14 * n21 * n42 - n11 * n24 * n42 - n12 * n21 * n44 + n11 * n22 * n44
    t34 = n14 * n22 * n31 - n12 * n24 * n31 - n14 * n21 * n32 + n11 * n24 * n32 + n12 * n21 * n34 - n11 * n22 * n34
    t41 = n23 * n32 * n41 - n22 * n33 * n41 + n21 * n33 * n42 - n23 * n31 * n42 - n21 * n32 * n43 + n22 * n31 * n43
    t42 = n12 * n33 * n41 - n13 * n32 * n41 - n11 * n33 * n42 + n13 * n31 * n42 + n11 * n32 * n43 - n12 * n31 * n43
    t43 = n13 * n22 * n41 - n12 * n23 * n41 - n11 * n22 * n42 + n12 * n21 * n42 + n11 * n23 * n43 - n13 * n21 * n43
    t44 = n12 * n23 * n31 - n13 * n22 * n31 - n11 * n23 * n32 + n13 * n21 * n32 + n11 * n22 * n33 - n12 * n21 * n33

    return [
        t11 * di, t21 * di, t31 * di, t41 * di,
        t12 * di, t22 * di, t32 * di, t42 * di,
        t13 * di, t23 * di, t33 * di, t43 * di,
        t14 * di, t24 * di, t34 * di, t44 * di,
    ]
