"""WeLearn 登录密码加密（按协议规范独立重写）。

算法：
    T0 = 毫秒时间戳
    V  = (T0 >> 16) & 0xFF，再依次 XOR 密码每个字节
    T1 = (T0 // 100) * 100 + (V % 100)
    pwd = base64(f"{T1}*" + hex(password bytes))
"""

from __future__ import annotations

import base64
import time


def generate_cipher_text(password: str, now_ms: int | None = None) -> tuple[str, str]:
    t0 = int(round(time.time() * 1000)) if now_ms is None else int(now_ms)
    raw = password.encode("utf-8")
    value = (t0 >> 16) & 0xFF
    for byte in raw:
        value ^= byte
    t1 = (t0 // 100) * 100 + value % 100
    hex_password = "".join(f"{byte:02x}" for byte in raw)
    encoded = base64.b64encode(f"{t1}*{hex_password}".encode("utf-8")).decode("utf-8")
    return encoded, str(t1)
