"""4x4 TRS 矩阵运算，与 three.js Matrix4 数值一致。

内部存储严格照搬 three.js 的列主序 4x4（te[r,c] 即 te.elements[c*4+r]），
compose/decompose/quaternion/euler 全部逐行对照 three.js 源码，
对外序列化的 16 元素与 THREE.Matrix4.elements 完全一致。
列主序下矩阵乘法对应 numpy 的 b @ a，即 multiply(a,b) = b @ a。
"""

from __future__ import annotations

import math
from typing import List

import numpy as np

EPS = 1e-10


def compose(position, quaternion, scale) -> np.ndarray:
    """THREE.Matrix4.compose 的逐行移植。"""
    x, y, z, w = quaternion
    x2 = x + x
    y2 = y + y
    z2 = z + z
    xx = x * x2
    xy = x * y2
    xz = x * z2
    yy = y * y2
    yz = y * z2
    zz = z * z2
    wx = w * x2
    wy = w * y2
    wz = w * z2
    sx, sy, sz = scale

    te = np.zeros((4, 4), dtype=np.float64)
    te[0, 0] = (1 - (yy + zz)) * sx
    te[0, 1] = (xy + wz) * sx
    te[0, 2] = (xz - wy) * sx
    te[0, 3] = 0

    te[1, 0] = (xy - wz) * sy
    te[1, 1] = (1 - (xx + zz)) * sy
    te[1, 2] = (yz + wx) * sy
    te[1, 3] = 0

    te[2, 0] = (xz + wy) * sz
    te[2, 1] = (yz - wx) * sz
    te[2, 2] = (1 - (xx + yy)) * sz
    te[2, 3] = 0

    te[3, 0] = position[0]
    te[3, 1] = position[1]
    te[3, 2] = position[2]
    te[3, 3] = 1
    return te


def quat_from_rotation_matrix(te: np.ndarray) -> np.ndarray:
    """THREE.Quaternion.setFromRotationMatrix 的逐行移植。"""
    # te 存储的是标准旋转的转置：标准矩阵 R[i,j] = te[j,i]
    m11 = te[0, 0]
    m12 = te[1, 0]
    m13 = te[2, 0]
    m21 = te[0, 1]
    m22 = te[1, 1]
    m23 = te[2, 1]
    m31 = te[0, 2]
    m32 = te[1, 2]
    m33 = te[2, 2]
    trace = m11 + m22 + m33

    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (m32 - m23) * s
        y = (m13 - m31) * s
        z = (m21 - m12) * s
    elif m11 > m22 and m11 > m33:
        s = 2.0 * math.sqrt(1.0 + m11 - m22 - m33)
        w = (m32 - m23) / s
        x = 0.25 * s
        y = (m12 + m21) / s
        z = (m13 + m31) / s
    elif m22 > m33:
        s = 2.0 * math.sqrt(1.0 + m22 - m11 - m33)
        w = (m13 - m31) / s
        x = (m12 + m21) / s
        y = 0.25 * s
        z = (m23 + m32) / s
    else:
        s = 2.0 * math.sqrt(1.0 + m33 - m11 - m22)
        w = (m21 - m12) / s
        x = (m13 + m31) / s
        y = (m23 + m32) / s
        z = 0.25 * s
    return np.array([x, y, z, w], dtype=np.float64)


def decompose(matrix: np.ndarray):
    """THREE.Matrix4.decompose 的逐行移植。"""
    te = matrix
    position = np.array([te[3, 0], te[3, 1], te[3, 2]], dtype=np.float64)

    a, b, c = te[0, 0], te[0, 1], te[0, 2]
    d, e, f = te[1, 0], te[1, 1], te[1, 2]
    g, h, i = te[2, 0], te[2, 1], te[2, 2]
    sx = math.sqrt(a * a + b * b + c * c)
    sy = math.sqrt(d * d + e * e + f * f)
    sz = math.sqrt(g * g + h * h + i * i)

    det = a * e * i - a * f * h - b * d * i + b * f * g + c * d * h - c * e * g
    if det < 0:
        sx = -sx

    rx = np.array([a, b, c]) / sx if sx > EPS else np.array([a, b, c])
    ry = np.array([d, e, f]) / sy if sy > EPS else np.array([d, e, f])
    rz = np.array([g, h, i]) / sz if sz > EPS else np.array([g, h, i])

    rot = np.zeros((4, 4), dtype=np.float64)
    rot[0, 0], rot[0, 1], rot[0, 2] = rx
    rot[1, 0], rot[1, 1], rot[1, 2] = ry
    rot[2, 0], rot[2, 1], rot[2, 2] = rz
    quaternion = quat_from_rotation_matrix(rot)
    scale = np.array([sx, sy, sz], dtype=np.float64)
    return position, quaternion, scale


def euler_xyz_from_quat(q) -> List[float]:
    """THREE.Euler 顺序 XYZ 的 setFromQuaternion 逐行移植。"""
    te = compose((0, 0, 0), q, (1, 1, 1))
    m11 = te[0, 0]
    m12 = te[0, 1]
    m13 = te[0, 2]
    m22 = te[1, 1]
    m23 = te[1, 2]
    m32 = te[2, 1]
    m33 = te[2, 2]
    y = math.asin(max(-1.0, min(1.0, m13)))
    if abs(m13) < 0.9999999:
        x = math.atan2(-m23, m33)
        z = math.atan2(-m12, m11)
    else:
        x = math.atan2(m32, m22)
        z = 0.0
    return [x, y, z]


def quat_from_euler_xyz(x: float, y: float, z: float) -> List[float]:
    """THREE.Quaternion.setFromEuler（默认 XYZ）。"""
    c1, c2, c3 = math.cos(x / 2), math.cos(y / 2), math.cos(z / 2)
    s1, s2, s3 = math.sin(x / 2), math.sin(y / 2), math.sin(z / 2)
    qx = s1 * c2 * c3 + c1 * s2 * s3
    qy = c1 * s2 * c3 - s1 * c2 * s3
    qz = c1 * c2 * s3 + s1 * s2 * c3
    qw = c1 * c2 * c3 - s1 * s2 * s3
    return [qx, qy, qz, qw]


def multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    # 列主序存储：three.js multiply(a,b) 结果为数学上的 b*a
    return b @ a


def inverse(a: np.ndarray) -> np.ndarray:
    return np.linalg.inv(a)


def to_elements(matrix: np.ndarray) -> List[float]:
    return matrix.flatten(order="C").tolist()
