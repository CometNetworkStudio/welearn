import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from omnitask_sdk import listing
from omnitask_sdk.config import Config
from omnitask_sdk.ratelimit import RateLimiter
from omnitask_sdk.runtime import serve

from welearn.runner import run

_CONFIG = Config.from_env()


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _duration(hour: int, minute: int) -> str:
    if hour and minute:
        return f"{hour}小时{minute}分钟"
    if hour:
        return f"{hour}小时"
    return f"{minute}分钟"


@listing()
def courses(ctx):
    """发现：列出该账号的课程（供 OmniTask 选择）。"""
    from welearn.client import WeLearnClient

    username = ctx.credentials.get("username") or ""
    password = ctx.credentials.get("password") or ""
    if not username or not password:
        raise RuntimeError("缺少账号密码凭据")
    limiter = RateLimiter(
        _CONFIG.platform_concurrency,
        _CONFIG.request_min_interval,
        _CONFIG.request_max_interval,
    )
    client = WeLearnClient(username, password, _CONFIG, limiter)
    client.login()
    result = []
    for course in client.get_courses():
        cid = str(course.get("cid") or course.get("id") or "")
        name = str(course.get("cname") or course.get("name") or "")
        per = str(course.get("per") or "")
        try:
            percent = float(per.strip().rstrip("%"))
        except (TypeError, ValueError):
            percent = 0
        if percent >= 100:
            state = "已完成:success"
        elif percent > 0:
            state = "学习中:primary"
        else:
            state = "未开始:grey"
        fields = {"cid": cid, "name": name, "per": per, "state": state}
        try:
            uid, _ = client.get_course_identity(cid)
            stats = client.get_scogeneral(cid, uid)
            total = _int(stats.get("Totalcount"))
            done = _int(stats.get("Finishcount"))
            avg = str(stats.get("ExAvgRate") or "")
            fields.update(
                {
                    "total": str(total),
                    "done": str(done),
                    "remaining": str(max(0, total - done)),
                    "avg_accuracy": f"{avg}%" if avg else "",
                    "study_time": _duration(_int(stats.get("Hour")), _int(stats.get("Minute"))),
                }
            )
        except Exception:
            # 统计失败不影响课程列表本身。
            pass
        result.append({"key": cid, "fields": fields})
    return result


def main():
    if sys.stdin.isatty() or "--cli" in sys.argv:
        from cli import main as cli_main

        return cli_main()
    serve(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
