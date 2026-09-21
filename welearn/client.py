"""WeLearn HTTP 客户端（净室重写）。

流程：prelogin 取 oauth code_challenge/state → SSO 登录 → 课程/单元/SCO →
刷时长或提交进度。参考 docs/reference-analysis.md。
"""

from __future__ import annotations

import re

from omnitask_sdk import http
from .crypto import generate_cipher_text

BASE_URL = "https://welearn.sflep.com"
SSO_URL = "https://sso.sflep.com/idsvr/account/login"
PRELOGIN = f"{BASE_URL}/user/prelogin.aspx?loginret=http://welearn.sflep.com/user/loginredirect.aspx"

_PROGRESS_DATA = (
    '{"cmi":{"completion_status":"completed","interactions":[],"launch_data":"",'
    '"progress_measure":"1","score":{"scaled":"%s","raw":"100"},"session_time":"0",'
    '"success_status":"unknown","total_time":"0","mode":"normal"},"adl":{"data":[]},'
    '"cci":{"data":[],"service":{"dictionary":{"headword":"","short_cuts":""},'
    '"new_words":[],"notes":[],"writing_marking":[],"record":{"files":[]},'
    '"play":{"offline_media_id":"9999"}},"retry_count":"0","submit_time":""}}'
    "[INTERACTIONINFO]"
)


class WeLearnError(RuntimeError):
    pass


def _extract(value: str, key: str) -> str:
    for part in value.split("%26"):
        if part.startswith(f"{key}%3D"):
            return part.split("%3D", 1)[1]
        if part.startswith(f"{key}="):
            return part.split("=", 1)[1]
    return ""


class WeLearnClient:
    def __init__(self, username: str, password: str, config, limiter=None) -> None:
        self.username = username
        self.password = password
        self.config = config
        self.limiter = limiter
        self.session = http.new_session(
            retries=config.http_retries,
            proxy=config.http_proxy,
            timeout=config.http_timeout,
        )

    def _guard(self):
        if self.limiter is None:
            from contextlib import nullcontext

            return nullcontext()
        return self.limiter.account_slot("welearn", self.username)

    def _get(self, url, **kwargs):
        with self._guard():
            return http.request(self.session, "GET", url, **kwargs)

    def _post(self, url, **kwargs):
        with self._guard():
            return http.request(self.session, "POST", url, **kwargs)

    # ---- 登录 ----
    def login(self) -> str:
        resp = self._get(PRELOGIN)
        code_challenge = _extract(resp.url, "code_challenge")
        state = _extract(resp.url, "state")
        if not code_challenge or not state:
            raise WeLearnError("prelogin 未取得 code_challenge/state")
        rturl = (
            "/connect/authorize/callback?client_id=welearn_web&redirect_uri=https%3A%2F%2Fwelearn.sflep.com"
            "%2Fsignin-sflep&response_type=code&scope=openid%20profile%20email%20phone%20address"
            f"&code_challenge={code_challenge}&code_challenge_method=S256&state={state}"
            "&x-client-SKU=ID_NET472&x-client-ver=6.32.1.0"
        )
        pwd, ts = generate_cipher_text(self.password)
        result = self._post(SSO_URL, data={"rturl": rturl, "account": self.username, "pwd": pwd, "ts": ts}).json()
        code = result.get("code", -1)
        if code == 1:
            raise WeLearnError("账号或密码错误")
        if code != 0:
            raise WeLearnError(f"登录失败 code={code}")
        self._get(PRELOGIN)
        return "登录成功"

    # ---- 课程 / 单元 ----
    def get_courses(self) -> list:
        resp = self._get(
            f"{BASE_URL}/ajax/authCourse.aspx",
            params={"action": "gmc"},
            headers={"Referer": f"{BASE_URL}/2019/student/index.aspx"},
        )
        data = resp.json()
        if not data.get("clist"):
            raise WeLearnError("没有找到课程")
        return data["clist"]

    def get_course_info(self, cid) -> dict:
        resp = self._get(f"{BASE_URL}/student/course_info.aspx", params={"cid": cid})
        uid_match = re.search(r'"uid":\s*(\d+),', resp.text)
        classid_match = re.search(r'"classid":"(\w+)"', resp.text)
        if not uid_match or not classid_match:
            raise WeLearnError("无法解析课程信息")
        uid, classid = uid_match.group(1), classid_match.group(1)
        data = self._get(
            f"{BASE_URL}/ajax/StudyStat.aspx",
            params={"action": "courseunits", "cid": cid, "uid": uid},
            headers={"Referer": f"{BASE_URL}/2019/student/course_info.aspx"},
        ).json()
        if "info" not in data:
            raise WeLearnError("单元信息格式错误")
        return {"uid": uid, "classid": classid, "units": data["info"]}

    def get_sco_leaves(self, cid, uid, classid, unit_idx) -> list:
        data = self._get(
            f"{BASE_URL}/ajax/StudyStat.aspx",
            params={"action": "scoLeaves", "cid": cid, "uid": uid, "unitidx": unit_idx, "classid": classid},
            headers={"Referer": f"{BASE_URL}/2019/student/course_info.aspx?cid={cid}"},
        ).json()
        return data.get("info", [])

    # ---- SCO 动作 ----
    def _sco(self, cid, uid, scoid, **form):
        return self._post(
            f"{BASE_URL}/Ajax/SCO.aspx",
            data={"cid": cid, "uid": uid, "scoid": scoid, **form},
            headers={"Referer": f"{BASE_URL}/student/StudyCourse.aspx"},
        )

    def start_sco(self, cid, uid, scoid):
        return self._sco(cid, uid, scoid, action="startsco160928")

    def keep_sco(self, cid, uid, scoid):
        return self._sco(cid, uid, scoid, action="keepsco_with_getticket_with_updatecmitime")

    def save_sco(self, cid, uid, scoid, progress="100", crate="0", status="unknown", cstatus="completed", trycount="0"):
        return self._sco(
            cid,
            uid,
            scoid,
            action="savescoinfo160928",
            progress=progress,
            crate=crate,
            status=status,
            cstatus=cstatus,
            trycount=trycount,
        )

    def submit_course_progress(self, cid, uid, classid, scoid, accuracy) -> bool:
        referer = f"{BASE_URL}/Student/StudyCourse.aspx?cid={cid}&classid={classid}&sco={scoid}"
        headers = {"Referer": referer}
        self._post(
            f"{BASE_URL}/Ajax/SCO.aspx",
            data={"action": "startsco160928", "cid": cid, "scoid": scoid, "uid": uid},
            headers=headers,
        )
        resp = self._post(
            f"{BASE_URL}/Ajax/SCO.aspx",
            data={
                "action": "setscoinfo",
                "cid": cid,
                "scoid": scoid,
                "uid": uid,
                "data": _PROGRESS_DATA % accuracy,
                "isend": "False",
            },
            headers=headers,
        )
        ok = '"ret":0' in resp.text
        resp = self._post(
            f"{BASE_URL}/Ajax/SCO.aspx",
            data={
                "action": "savescoinfo160928",
                "cid": cid,
                "scoid": scoid,
                "uid": uid,
                "progress": "100",
                "crate": accuracy,
                "status": "unknown",
                "cstatus": "completed",
                "trycount": "0",
            },
            headers=headers,
        )
        return ok and '"ret":0' in resp.text
