"""WeLearn runner：刷时长 / 提交进度。"""

from __future__ import annotations

import time

from omnitask_sdk.config import Config
from omnitask_sdk.events import event
from omnitask_sdk.params import resolve
from omnitask_sdk.ratelimit import RateLimiter

from .client import WeLearnClient, WeLearnError, ret_ok

_CONFIG = Config.from_env()


def _as_int(value, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_visible(item) -> bool:
    if not isinstance(item, dict):
        return True
    return str(item.get("isvisible", "")).strip().lower() != "false"


def _entry(item):
    """返回 (scoid, 名称)；原项目以 id 作为 SCO 标识。"""
    if not isinstance(item, dict):
        text = str(item).strip()
        return (text, "") if text else None
    scoid = ""
    for key in ("id", "scoid", "sco", "sco_id"):
        value = item.get(key)
        if value not in (None, ""):
            scoid = str(value)
            break
    if not scoid:
        return None
    name = str(item.get("location") or item.get("name") or "")
    return scoid, name


def _pick_course(courses: list, want) -> dict:
    if not courses:
        raise WeLearnError("账号下没有课程")
    if want in (None, ""):
        return courses[0]
    for course in courses:
        if str(course.get("cid")) == str(want) or str(course.get("id")) == str(want):
            return course
    raise WeLearnError(f"未找到课程 cid={want}")


def _collect_scos(
    client, cid, uid, classid, units, params, action, max_count: int = 0
) -> tuple[list[tuple[str, str]], list[str]]:
    """收集待处理 SCO，按 id 去重。

    注意：WeLearn 的 unitidx 是单元的数字下标（0-based），不是单元 id；
    传错会导致每个单元返回同一批 SCO。挂时长只需收集够本次时长所需的 SCO；
    提交进度默认只处理未完成项，开启 include_completed 后才重提已完成项。
    max_count > 0 时收满即停，避免为了挂 60 秒遍历整门课。
    返回 (SCO 列表, 单元错误列表)；单个单元失败不影响其他单元。
    """
    include_completed = str(params.get("include_completed", "")).lower() in ("1", "true", "yes", "on")
    raw_unit = params.get("unit_idx")
    if raw_unit in (None, ""):
        unit_indices = range(len(units))
    else:
        unit_idx = _as_int(raw_unit, -1)
        if unit_idx < 0:
            raise WeLearnError(f"单元下标无效: {raw_unit}")
        unit_indices = [unit_idx]

    seen: set[str] = set()
    scos: list[tuple[str, str]] = []
    errors: list[str] = []
    for unit_index in unit_indices:
        try:
            items = client.get_sco_leaves(cid, uid, classid, unit_index)
        except Exception as exc:  # noqa: BLE001 - 单元失败继续下一个单元
            errors.append(f"单元 {unit_index + 1}: {exc}")
            continue
        for item in items:
            if not _is_visible(item):
                continue
            if action != "time" and not include_completed:
                if "未" not in str(item.get("iscomplete", "")):
                    continue
            entry = _entry(item)
            if entry is None or entry[0] in seen:
                continue
            seen.add(entry[0])
            scos.append(entry)
            if max_count and len(scos) >= max_count:
                break
        if max_count and len(scos) >= max_count:
            break
    return scos, errors


def _fail_text(detail) -> str:
    if isinstance(detail, dict):
        return "setscoinfo=%s, savescoinfo=%s" % (
            "成功" if detail.get("setscoinfo") else "失败",
            "成功" if detail.get("savescoinfo") else "失败",
        )
    return str(detail)


def _pct(value) -> int:
    """单个 SCO 的事件最高 99，100 保留给任务完成。"""
    return min(99, max(0, int(value)))


def run(action: str, params: dict, credentials: dict):
    if action not in ("time", "progress"):
        raise WeLearnError(f"未知动作: {action}")
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

    limit = _as_int(resolved.get("limit"), 0)
    total_duration = max(0, _as_int(resolved.get("duration"), 60))
    # 挂时长不遍历整门课：按 60 秒一个 SCO 估算所需数量；limit 仍是最多 SCO 数。
    target_count = 0
    if action == "time":
        target_count = max(1, (total_duration + 59) // 60)
        if limit > 0:
            target_count = min(target_count, limit)
    elif limit > 0:
        target_count = limit

    scos, unit_errors = _collect_scos(
        client, cid, uid, classid, info["units"], resolved, action, max_count=target_count
    )
    for err in unit_errors:
        yield event(6, f"[警告] {err}")
    if limit > 0:
        scos = scos[:limit]
    if action == "time" and target_count > 0:
        scos = scos[:target_count]
    if not scos:
        if unit_errors:
            raise WeLearnError(f"获取 SCO 失败: {unit_errors[0]}")
        yield event(
            100,
            "没有可处理的 SCO",
            {"total": 0, "succeeded": 0, "failed": 0, "units_failed": 0},
        )
        return

    seconds_base, seconds_extra = divmod(total_duration, len(scos))
    if action == "time":
        yield event(8, f"本次挂时长 {total_duration}s，处理 {len(scos)} 个 SCO")
    else:
        yield event(8, f"待处理 SCO 数 {len(scos)}")
    accuracy = str(resolved.get("accuracy", 100) or 100)
    succeeded = 0
    failed: list[tuple[str, object]] = []
    for index, (scoid, name) in enumerate(scos, start=1):
        label = name or scoid
        base = (index - 1) / len(scos) * 92 + 8
        seconds = seconds_base + (1 if index <= seconds_extra else 0)
        try:
            if action == "progress":
                result = client.submit_course_progress(cid, uid, classid, scoid, accuracy)
                if result["ok"]:
                    succeeded += 1
                    yield event(_pct(base + 92 / len(scos)), f"[完成] {label}")
                else:
                    failed.append((label, result))
                    yield event(_pct(base + 92 / len(scos)), f"[失败] {label} {_fail_text(result)}")
                continue

            client.start_sco(cid, uid, scoid)
            for elapsed in range(1, seconds + 1):
                time.sleep(1)
                if elapsed % 60 == 0:
                    client.keep_sco(cid, uid, scoid)
                if elapsed % 10 == 0 or elapsed == seconds:
                    within = elapsed / seconds * (92 / len(scos))
                    yield event(_pct(base + within), f"[进行] {label} 已挂 {elapsed}s/{seconds}s")
            resp = client.save_sco(cid, uid, scoid)
            if ret_ok(resp):
                succeeded += 1
                yield event(_pct(base + 92 / len(scos)), f"[完成] {label}")
            else:
                failed.append((label, "savescoinfo 未返回 ret:0"))
                yield event(_pct(base + 92 / len(scos)), f"[失败] {label} 保存未确认")
        except Exception as exc:  # noqa: BLE001 - 单个 SCO 失败不中断整个任务
            failed.append((label, str(exc)))
            yield event(_pct(base + 92 / len(scos)), f"[失败] {label}: {exc}")

    if succeeded == 0:
        raise WeLearnError(f"全部 SCO 处理失败: {_fail_text(failed[0][1])}")
    message = "全部 SCO 处理完成" if not failed else f"完成 {succeeded}/{len(scos)}，失败 {len(failed)}"
    yield event(
        100,
        message,
        {"total": len(scos), "succeeded": succeeded, "failed": len(failed), "units_failed": len(unit_errors)},
    )
