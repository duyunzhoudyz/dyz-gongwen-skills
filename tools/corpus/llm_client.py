#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语料校准用的国产大模型统一调用模块（DeepSeek、通义千问、豆包）。

对应方案：docs/评测/语料校准方案.md 第二部分（二）、第六部分步骤 2。

做什么
    1. 三家都走 OpenAI 兼容的 /chat/completions 接口，只用标准库 urllib；
    2. 密钥从仓库根目录的 <name>.key.local 读取（取第一个非空行），绝不打印、不写入任何文件；
    3. 调用参数固定：不加系统提示词、不传 temperature（用服务端默认温度）、统一非思考模式；
    4. 提供连通性自检（ping）：每家只发 1 次极短请求，报告是否成功、模型名、耗时、返回字数。

用法
    python tools/corpus/llm_client.py ping                    # 三家都自检；缺密钥的跳过
    python tools/corpus/llm_client.py ping --only deepseek    # 只测一家
    python tools/corpus/llm_client.py ping --only deepseek --model deepseek-flash   # 换型号试一次

退出码
    0  自检的各家都成功（缺密钥跳过不算失败）
    1  有任何一家调用失败
    2  参数有误

后续的 generate.py 直接 import 本模块的 chat()，重试与并发在 generate.py 里做，这里一次调用只发一次请求。
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 三家模型配置
#   base_url / key_file 来自方案第二部分（二）的表格；model 为候选型号，方案明确"具体型号在步骤 2 试调时由用户确认"。
#   non_thinking：关闭思考模式要额外合并进请求体的字段（None 表示不传）。方案只要求"统一用非思考模式"，
#   没有写各家的参数名，见各条 TODO，需实测后才能定稿。
# ---------------------------------------------------------------------------
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "key_file": "deepseek.key.local",
        # 沿用 evals/compete 使用的 deepseek-chat；方案提示价格页只列 deepseek-flash、deepseek-v4-pro，需核对 deepseek-chat 是否仍可用
        "model": "deepseek-chat",
        "fallback_models": ["deepseek-flash", "deepseek-v4-pro"],
        # TODO: deepseek-chat 按旧版约定是非思考模式；若改用 deepseek-flash / deepseek-v4-pro，
        #       关闭思考的参数写法方案没写，需实测（不凭记忆写入）。
        "non_thinking": None,
    },
    "qwen": {
        "label": "通义千问",
        # 阿里云百炼，OpenAI 兼容接口，北京地域
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "key_file": "qwen.key.local",
        # 方案价格表候选：qwen-plus（轻量档）、qwen3.7-plus（旗舰档），具体型号待用户确认
        "model": "qwen-plus",
        "fallback_models": ["qwen3.7-plus"],
        # TODO: 方案未写关闭思考的参数名，也未写是否必须显式关闭，需实测。
        "non_thinking": None,
    },
    "doubao": {
        "label": "豆包",
        # 火山方舟，方案称"尽可能兼容 OpenAI"，需实测，不兼容之处单独适配
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "key_file": "doubao.key.local",
        # 方案价格表候选：doubao-seed-2.1-lite（轻量档）、doubao-seed-2.1-pro（旗舰档），具体型号待用户确认
        "model": "doubao-seed-2.1-lite",
        "fallback_models": ["doubao-seed-2.0-lite", "doubao-seed-2.1-pro"],
        # TODO: 方舟的 model 字段可能要求填接入点 ID（ep-...）而非型号名，需实测；
        #       关闭思考的参数写法方案没写，需实测。
        "non_thinking": None,
    },
}

DEFAULT_TIMEOUT = 180  # 单次请求超时（秒），写长文用；自检用较短值
PING_TIMEOUT = 60
PING_MAX_TOKENS = 20
PING_PROMPT = "请回复：好"
USER_AGENT = "gongwen-corpus-calibration/1.0 (research)"

# 已读到的密钥，输出前统一遮蔽，防止任何路径把密钥带进日志
_SECRETS: list[str] = []


class KeyFileError(Exception):
    """密钥文件缺失或内容为空。"""


class ApiError(Exception):
    """调用失败。retryable：重试可能恢复；fatal：认证失败或余额不足，重试无意义。"""

    def __init__(self, message: str, retryable: bool = False, fatal: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.fatal = fatal
        self.status = status


RETRYABLE_HTTP = {408, 409, 425, 429, 500, 502, 503, 504}
FATAL_HTTP = {401, 402, 403}


def scrub(text: str) -> str:
    for secret in _SECRETS:
        if secret:
            text = text.replace(secret, "***")
    return text


def key_path(provider: str) -> Path:
    return REPO / PROVIDERS[provider]["key_file"]


def read_key(provider: str) -> str:
    """读取 <name>.key.local 的第一个非空行作为密钥。文件缺失或没有非空行时抛 KeyFileError。"""
    path = key_path(provider)
    name = PROVIDERS[provider]["key_file"]
    if not path.is_file():
        raise KeyFileError(f"未找到密钥文件：{name}（仓库根目录）")
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise KeyFileError(f"无法读取密钥文件：{name}（{exc.__class__.__name__}）") from None
    for line in text.splitlines():
        line = line.strip()
        if line:
            _SECRETS.append(line)
            return line
    raise KeyFileError(f"密钥文件是空的：{name}")


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """取出服务端返回的错误说明（截断）；不含请求头。"""
    try:
        raw = exc.read(2000).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - 读错误体失败不影响主流程
        return ""
    msg = ""
    try:
        obj = json.loads(raw)
        err = obj.get("error", obj) if isinstance(obj, dict) else {}
        msg = err.get("message", "") if isinstance(err, dict) else ""
    except (ValueError, AttributeError):
        pass
    return scrub((msg or raw).strip().replace("\n", " "))[:200]


def build_payload(provider: str, prompt: str, model: str | None = None, max_tokens: int | None = None) -> dict:
    """组装请求体：只有一条 user 消息（无系统提示词），不传 temperature。"""
    cfg = PROVIDERS[provider]
    payload: dict = {
        "model": model or cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if cfg.get("non_thinking"):
        payload.update(cfg["non_thinking"])
    return payload


def chat(provider: str, prompt: str, *, model: str | None = None, max_tokens: int | None = None,
         timeout: int = DEFAULT_TIMEOUT, key: str | None = None) -> dict:
    """发一次请求，返回 {"content", "finish_reason", "usage", "model", "elapsed"}；失败抛 ApiError / KeyFileError。

    max_tokens 为 None 时不传（用服务端默认上限）。不重试。
    """
    if provider not in PROVIDERS:
        raise ValueError(f"未知模型提供方：{provider}")
    cfg = PROVIDERS[provider]
    key = key or read_key(provider)
    payload = build_payload(provider, prompt, model, max_tokens)
    req = urllib.request.Request(
        cfg["base_url"] + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
            "User-Agent": USER_AGENT,
        },
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:  # 必须先于 URLError（它是 URLError 的子类）
        code = exc.code
        detail = _error_detail(exc)
        raise ApiError(f"HTTP {code}" + (f"：{detail}" if detail else ""),
                       retryable=code in RETRYABLE_HTTP, fatal=code in FATAL_HTTP, status=code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ApiError(scrub(f"网络错误：{reason}"), retryable=True) from None
    elapsed = time.monotonic() - t0

    try:
        obj = json.loads(raw.decode("utf-8"))
        choice = obj["choices"][0]
        content = choice["message"]["content"]
        finish = choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError):
        raise ApiError("返回内容无法解析", retryable=True) from None
    if not isinstance(content, str) or not content.strip():
        raise ApiError("返回的正文为空", retryable=True)
    return {"content": content, "finish_reason": finish, "usage": obj.get("usage"),
            "model": obj.get("model") or payload["model"], "elapsed": elapsed}


# ---------------------------------------------------------------------------
# 连通性自检
# ---------------------------------------------------------------------------
def ping(provider: str, model: str | None = None) -> dict:
    """对一家发 1 次极短请求。返回 {"provider","label","status","model","elapsed","chars","error"}。

    status：ok 成功；missing_key 缺密钥（跳过）；fail 调用失败。不返回、不打印密钥与回复原文。
    """
    cfg = PROVIDERS[provider]
    out = {"provider": provider, "label": cfg["label"], "status": "fail",
           "model": model or cfg["model"], "elapsed": None, "chars": None, "error": ""}
    try:
        key = read_key(provider)
    except KeyFileError:
        out["status"] = "missing_key"
        out["error"] = "缺密钥，待用户提供"
        return out
    t0 = time.monotonic()
    try:
        res = chat(provider, PING_PROMPT, model=model, max_tokens=PING_MAX_TOKENS, timeout=PING_TIMEOUT, key=key)
    except ApiError as exc:
        out["elapsed"] = time.monotonic() - t0
        out["error"] = scrub(str(exc))
        return out
    out.update(status="ok", model=res["model"], elapsed=res["elapsed"], chars=len(res["content"].strip()))
    return out


def format_ping(r: dict) -> str:
    if r["status"] == "missing_key":
        return f"[跳过] {r['label']}：缺密钥，待用户提供"
    if r["status"] == "ok":
        return f"[成功] {r['label']}：模型 {r['model']}，耗时 {r['elapsed']:.2f} 秒，返回 {r['chars']} 字"
    t = f"，耗时 {r['elapsed']:.2f} 秒" if r["elapsed"] is not None else ""
    return f"[失败] {r['label']}：模型 {r['model']}{t}，错误：{r['error']}"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="llm_client.py", description="语料校准用国产大模型统一调用模块。")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ping", help="连通性自检：每家只发 1 次极短请求")
    p.add_argument("--only", choices=sorted(PROVIDERS), help="只测一家")
    p.add_argument("--model", help="覆盖型号（须与 --only 同用）")
    args = parser.parse_args(argv)
    if args.cmd == "ping" and args.model and not args.only:
        parser.error("--model 须与 --only 一起使用")
    return args


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = parse_args(argv)
    names = [args.only] if args.only else list(PROVIDERS)
    failed = False
    for name in names:
        r = ping(name, args.model if args.only else None)
        print(format_ping(r), flush=True)
        failed = failed or r["status"] == "fail"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
