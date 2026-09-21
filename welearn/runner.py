"""WeLearn runner：刷时长 / 提交进度。"""

from __future__ import annotations

import time

from omnitask_sdk.config import Config
from omnitask_sdk.events import event
from omnitask_sdk.params import resolve
from omnitask_sdk.ratelimit import RateLimiter
from .client import WeLearnClient, WeLearnError

_CONFIG = Config.from_env()


def _is_actionable(item, include_completed: bool) -> bool:
    if not isinstance(item, dict):
        return True
    if str(item.get("isvisible")) == "false":
        return False
    if include_completed:
        return True
    return "未" in str(item.get("iscomplete", ""))


def _sco_id(item) -> str | None:
    if isinstance(item, dict):
        for key in ("scoid", "sco", "sco_id", "id"):
            if item.get(key) not in (None, ""):
                return str(item[key])
        return None
    return str(item)


def _pick_course(courses: list, want) -> dict:
    if not courses:
        raise WeLearnError("账号下没有课程")
    if want in (None, ""):
        return courses[0]
    for course in courses:
        if str(course.get("cid")) == str(want) or str(course.get("id")) == str(want):
            return course
    raise WeLearnError(f"未找到课程 cid={want}")


def _collect_sco_ids(client, cid, uid, classid, units, params) -> list[str]:
    """收集待处理 SCO id，按单元去重。

    注意：WeLearn 的 unitidx 是单元的数字下标（0-based），不是单元 id；
    传错会导致每个单元返回同一批 SCO。
    """
    include_completed = str(params.get("include_completed", "")).lower() in ("1", "true", "yes")
    if params.get("unit_idx") not in (None, ""):
        items = client.get_sco_leaves(cid, uid, classid, int(params["unit_idx"]))
    else:
        items = []
        for unit_index in range(len(units)):
            items.extend(client.get_sco_leaves(cid, uid, classid, unit_index))
    actionable = [item for item in items if _is_actionable(item, include_completed)]
    return list(dict.fromkeys(sid for sid in (_sco_id(item) for item in actionable) if sid))


def run(action: str, params: dict, credentials: dict):
    username = credentials.get("username") or params.get("username")
    password = credentials.get("password") or params.get("password")
    if not username or not password:
        raise WeLearnError("WeLearn 需要账号密码凭据")

    resolved = resolve("welearn", params, _CONFIG)
    limiter = RateLimiter(
        resolved["platform_concurrency"],
        resolved["request_min_interval"],
        resolved["request_max_interval"],
    )
    client = WeLearnClient(username, password, _CONFIG, limiter)
    message = client.login()
    yield event(2, message)

    courses = client.get_courses()
    yield event(5, f"课程数 {len(courses)}")
    course = _pick_course(courses, params.get("cid"))
    cid = course.get("cid") or course.get("id")
    info = client.get_course_info(cid)
    uid, classid = info["uid"], info["classid"]

    include_completed = str(params.get("include_completed", "")).lower() in ("1", "true", "yes")
    include_completed = str(params.get("include_completed", "")).lower() in ("1", "true", "yes")
    scoids = _collect_sco_ids(client, cid, uid, classid, info["units"], resolved)
    limit = resolved.get("limit")
    if limit:
        scoids = scoids[: int(limit)]
    if not scoids:
        yield event(100, "没有未完成的 SCO")
        return
    yield event(8, f"待处理 SCO 数 {len(scoids)}")

    duration = int(resolved.get("duration", 60))
    accuracy = resolved.get("accuracy", "100")
    for index, scoid in enumerate(scoids, start=1):
        base = (index - 1) / len(scoids) * 92 + 8
        if action == "progress":
            client.submit_course_progress(cid, uid, classid, scoid, accuracy)
            yield event(int(base + 92 / len(scoids)), f"SCO {scoid} 进度已提交")
            continue
        client.start_sco(cid, uid, scoid)
        for elapsed in range(1, duration + 1):
            time.sleep(1)
            if elapsed % 60 == 0:
                client.keep_sco(cid, uid, scoid)
            if elapsed % 10 == 0:
                within = elapsed / duration * (92 / len(scoids))
                yield event(int(base + within), f"SCO {scoid} 已挂 {elapsed}s/{duration}s")
        client.save_sco(cid, uid, scoid)
        yield event(int(base + 92 / len(scoids)), f"SCO {scoid} 完成")
    yield event(100, "全部 SCO 处理完成")
