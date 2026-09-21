import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from omnitask_sdk import listing
from omnitask_sdk.config import Config
from omnitask_sdk.ratelimit import RateLimiter
from omnitask_sdk.runtime import serve

from welearn.runner import run

_CONFIG = Config.from_env()


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
    return [
        {
            "key": str(course.get("cid") or course.get("id")),
            "fields": {
                "cid": str(course.get("cid") or course.get("id") or ""),
                "name": str(course.get("cname") or course.get("name") or ""),
            },
        }
        for course in client.get_courses()
    ]


def main():
    if sys.stdin.isatty() or "--cli" in sys.argv:
        from cli import main as cli_main

        return cli_main()
    serve(run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
