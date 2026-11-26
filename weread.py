"""微信读书 Agent Gateway 的轻量客户端。

只依赖 Python 标准库。Key 从环境变量 WEREAD_API_KEY 读取，只放进 HTTP header，
绝不拼进 URL、不写日志、不写入任何产物。
"""

import gzip
import json
import os
import time
import urllib.error
import urllib.request

GATEWAY = "https://i.weread.qq.com/api/agent/gateway"
SKILL_VERSION = "1.0.6"
KEY_ENV = "WEREAD_API_KEY"

# 重试策略：网络抖动 / 5xx / 429 时指数退避
MAX_RETRIES = 3
RETRY_BASE = 0.8
TIMEOUT = 30
USER_AGENT = "shuji/1.0 (+https://github.com/)"


class WereadError(RuntimeError):
    """网关返回 errcode 非 0，或请求失败。"""


def get_key():
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        raise WereadError(
            "未找到 API Key。请先设置环境变量：\n"
            "  Windows PowerShell: $env:WEREAD_API_KEY='wrk-xxxx'\n"
            "  macOS / Linux:     export WEREAD_API_KEY=wrk-xxxx"
        )
    return key


def call(api_name, **params):
    """调用网关。业务参数平铺在 body 顶层，不包 params。"""
    body = {"api_name": api_name, "skill_version": SKILL_VERSION}
    body.update(params)
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    key = get_key()

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(
            GATEWAY,
            data=payload,
            headers={
                "Authorization": "Bearer " + key,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "gzip",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                data = json.loads(raw.decode("utf-8"))
            errcode = data.get("errcode")
            if errcode not in (None, 0):
                # 不在日志里回显任何凭据，只报 errcode 与 errmsg
                raise WereadError(
                    "%s 返回 errcode=%s：%s"
                    % (api_name, errcode, data.get("errmsg", ""))
                )
            return data
        except urllib.error.HTTPError as exc:
            # 429/5xx 可重试；401/403 是 Key 问题，不重试
            if exc.code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
                last_error = exc
                time.sleep(RETRY_BASE * (2 ** attempt))
                continue
            raise WereadError("%s HTTP %s（请确认 Key 是否有效）" % (api_name, exc.code))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < MAX_RETRIES:
                last_error = exc
                time.sleep(RETRY_BASE * (2 ** attempt))
                continue
            raise WereadError("%s 网络请求失败：%s" % (api_name, exc))
        except json.JSONDecodeError as exc:
            raise WereadError("%s 返回内容不是合法 JSON：%s" % (api_name, exc))

    raise WereadError("%s 重试 %d 次后仍失败：%s" % (api_name, MAX_RETRIES, last_error))
