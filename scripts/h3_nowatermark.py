#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H3 无水印一键管线（自包含版）：生成 -> 抓三变体 -> 互补合成 + LaMa 死区重建。

子命令:
  install                       自安装：落出完整 skill 目录（--deps 同时装依赖）
  balance                       查询账号余额
  image  "提示词" [选项]        生成无水印图片 (1 积分/张)
  video  "提示词" [选项]        生成无水印 4s 视频 (7 积分/秒, 768x1344@24fps)

Token: %USERPROFILE%\\.codex\\credentials\\hailuo-tokens.txt (每行一个 JWT),
       或环境变量 HAILUO_CREDENTIAL_FILE。
输出:  stdout 最后一行为 JSON 结果（成品路径 + 分段耗时 + 水印几何）。
注意:  本脚本自行清除代理环境变量（官方域名直连即可）。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any

# 官方域名直连可用；清除代理避免 ProxyError
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

API_ORIGIN = "https://hailuoai.com"
DEFAULT_CRED = Path.home() / ".codex" / "credentials" / "hailuo-tokens.txt"
IMG_SUCCESS, IMG_FAILED = 2, {3, 6, 7, 8}
VID_SUCCESS, VID_PENDING, VID_FAILED = 2, {1, 11, 12}, {3, 5, 7, 9, 14, 16}

# 视频水印几何（768x1344 实测常量；脚本会做差分自检）
VID_W, VID_H = 768, 1344
L1 = (1250, 1316)            # v1 logo 行带（含余量）
B2C = (578, 732)             # v2 角标列带（含余量）
CY0, CY1, CX0, CX1 = 1210, 1344, 520, 768   # LaMa 上下文裁剪框

# ---------------------------------------------------------------- 自安装 payload
# 本文件既是主程序也是安装器：payload 内嵌全部辅助文件，`install` 子命令
# （或首次 image/video 自动触发）把 skill 落到 ~/.workbuddy/skills/h3-nowatermark/。
SKILL_NAME = "h3-nowatermark"
REQ_PKGS = ("requests", "numpy", "pillow", "scipy",
            "opencv-contrib-python-headless", "torch")

REQUIREMENTS_TXT_EMBEDDED = """\
requests
numpy
pillow
scipy
opencv-contrib-python-headless
torch
simple-lama-inpainting
"""

SETUP_CMD_EMBEDDED = """\
@echo off
rem H3 无水印 skill 一键环境安装（Windows）
rem 用法: 在本目录执行  setup.cmd
rem 产物: 本目录下 .venv 虚拟环境，之后用 .venv\\Scripts\\python.exe h3_nowatermark.py ...
cd /d "%~dp0"
python -m venv .venv || py -3 -m venv .venv
call .venv\\Scripts\\activate.bat
python -m pip install --upgrade pip
rem simple-lama-inpainting 依赖声明过严，用 --no-deps 安装，torch 单独装
pip install requests numpy pillow scipy opencv-contrib-python-headless torch
pip install --no-deps simple-lama-inpainting
echo.
echo 安装完成。运行示例:
rem   .venv\\Scripts\\python.exe h3_nowatermark.py balance
rem   .venv\\Scripts\\python.exe h3_nowatermark.py image "a cute cat" --outdir out
rem 注意: 首次跑图片/视频会自动下载 LaMa 修复模型(约200MB, 需外网)。
pause
"""

SKILL_MD_EMBEDDED = """\
---
name: h3-nowatermark
description: 海螺 H3 无水印一键生成管线（图片+视频）。一条命令完成：官方渠道生成 → 抓取 -1/-2/-3 三个水印变体 → 几何探测互补合成 + LaMa 死区重建 → 输出无水印成品与分段耗时。触发词：H3 无水印、去水印生成、nowatermark、无水印图/视频、H3 干净出图。
---

# H3 无水印一键管线（图片 + 视频）

基于海螺 H3 官网渠道（hailuoai.com）的水印机制：每次生成免费附带三个水印变体
`-1`(仅品牌 logo) / `-2`(仅 AI 角标) / `-3`(双标)。三者互补后只剩一个"死区"
（logo ∩ 角标交叠），死区用 LaMa 深度重建。全程本地合成，0 额外积分。

## 用法

```bash
PY=scripts/.venv/Scripts/python.exe    # Windows；其它系统为 scripts/.venv/bin/python
# 余额
"$PY" scripts/h3_nowatermark.py balance
# 无水印图片（1 积分/张）
"$PY" scripts/h3_nowatermark.py image "提示词" --outdir OUT_DIR
# 无水印 4s 视频（28 积分/条，768x1344@24fps）
"$PY" scripts/h3_nowatermark.py video "提示词" --outdir OUT_DIR --duration 4
# 自安装：把完整 skill 落到 ~/.workbuddy/skills/h3-nowatermark/
"$PY" h3_nowatermark.py install [--deps]
```

可选：`--account N`（Token 文件第 N 行，默认 1）、图片 `--ratio 1:1`、`--model image-01`。

输出（stdout 最后一行 JSON）：成品路径、各阶段绝对时间戳与耗时
（submit → gen → fetch → repair → total）、水印几何与重建方式。
产物：`OUT_DIR/final.png` 或 `OUT_DIR/final.mp4`，中间三变体同目录保留。

## Token

从 `%USERPROFILE%\\.codex\\credentials\\hailuo-tokens.txt` 读取（每行一个 JWT），
可用环境变量 `HAILUO_CREDENTIAL_FILE` 覆盖。不落日志、不进产物。

## 跨机部署（单文件自安装）

**最便携的方式：只拷一个文件。** `scripts/h3_nowatermark.py` 既是主程序也是安装器，
内嵌了 SKILL.md / requirements.txt / setup.cmd 全部辅助文件。换电脑只需：

1. 拷贝 `h3_nowatermark.py` 到任意位置（如桌面）
2. 执行 `python h3_nowatermark.py install`
   → 自动在 `~/.workbuddy/skills/h3-nowatermark/` 落出完整 skill 目录
   （SKILL.md + scripts/h3_nowatermark.py + requirements.txt + setup.cmd），
   WorkBuddy 对话中即刻可调用；也可 `install 自定义路径` 指定落盘位置
3. 装依赖：`python h3_nowatermark.py install --deps`（直接装进当前解释器），
   或在落出的 `scripts/` 下执行 `setup.cmd`（生成独立 .venv）
4. 放 Token：`%USERPROFILE%\\.codex\\credentials\\hailuo-tokens.txt`（每行一个 JWT），
   或设环境变量 `HAILUO_CREDENTIAL_FILE`
5. ffmpeg：装过就直接被探测到；否则设环境变量 `H3_FFMPEG` 指向 ffmpeg.exe
6. 首次跑图片/视频会自动下载 LaMa 修复模型（约 200MB，需外网，之后离线可用）

注：直接运行 `balance/image/video` 时，若脚本发现自身不在 skill 目录里
（旁边没有 SKILL.md），会先自动完成第 2 步落盘再执行任务。

## 依赖

- Python 3.10+：requests / numpy / pillow / scipy / opencv-contrib-python-headless /
  torch / simple-lama-inpainting（见 scripts/requirements.txt）
- ffmpeg（仅视频重编码需要）

## 已验证的实测耗时（2026-09-17 批量冒烟，12/12 成功）

- 图片：生成 19–28s（偶发慢批次 74s）、取三变体 ~1s、修复 16–18s → 单张端到端约 40s
- 视频 4s：生成饱和 ~101s、取回 ~2s、逐帧修复+重编码 ~74s → 单条约 3 分钟

## 关键实现约束（改代码前必读）

1. **不要设 HTTP_PROXY**：7897 代理已失效，hailuoai.com 直连正常。
2. **水印几何**：1024×1024 图片与 768×1344 视频实测固定（多样本验证），
   但脚本仍做差分自检/自动探测，换分辨率也能适配；视频几何常量
   `L1=(1250,1316)`（v1 logo 行带）、`B2C=(578,732)`（v2 角标列带），仅适用 768×1344。
3. **图片检测阈值**：v2 角标框线 alpha≈0.09，v2 检测阈值必须降到 6（v1 logo 用 10）；
   badge 连通域过滤：跨度≥60 或 像素≥150，防止文字笔画噪声拉宽 bbox；
   badge 框右缘 +14px 兜底（亮背景上右框线差异 ~2/255 任何阈值都检不出）。
4. **死区守护只保留一条规则**：环带 std<6 判纯色 → 直接填色（快路径 1.5s）。
   不要再加"伪影守护"（TELEA 对照/饱和度判据/块级填充都实测误伤，已回退）。
5. **LaMa 掩码语义**：非零 = 待重建（与 cv2.xphoto 相反）。
6. **视频 selfcheck 必须用独立 VideoCapture**：在主循环 caps 上 seek 会污染
   读取顺序导致读到 None。
7. **已知限制**：死区正中压"独立图形"（圆点/logo 图形）时 LaMa 可能补不出
   （实测装饰圆点变暗斑）；文字笔画因真实像素互换不受影响。v2 角标是双层
   alpha 贴片（框线 0.09 / 字符 0.41），数学剥离是后续可选优化方向。
8. 提交类接口有签名（`yy` 参数），已内置于脚本，勿手工拼请求。
"""


def install_skill(target: str | None = None, with_deps: bool = False) -> dict:
    """把内嵌 payload 落出完整 skill 目录；脚本自身一并复制到 scripts/ 下。"""
    root = Path(target).expanduser().resolve() if target else \
        Path.home() / ".workbuddy" / "skills" / SKILL_NAME
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    self_path = Path(__file__).resolve()
    written = []
    for rel, content in (("SKILL.md", SKILL_MD_EMBEDDED),
                         (str(Path("scripts") / "requirements.txt"),
                          REQUIREMENTS_TXT_EMBEDDED),
                         (str(Path("scripts") / "setup.cmd"),
                          SETUP_CMD_EMBEDDED)):
        p = root / rel
        p.write_text(content, encoding="utf-8", newline="\n")
        written.append(str(p))
    dst = scripts / self_path.name
    try:
        same_file = self_path.resolve() == dst.resolve()
    except OSError:
        same_file = False
    if not same_file and (not dst.exists()
                          or self_path.read_bytes() != dst.read_bytes()):
        shutil.copyfile(self_path, dst)
        written.append(str(dst))
    deps_note = "skipped"
    if with_deps:
        r1 = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade",
                             "pip", *REQ_PKGS], capture_output=True, text=True)
        r2 = subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps",
                             "simple-lama-inpainting"],
                            capture_output=True, text=True)
        deps_note = ("installed" if r1.returncode == 0 and r2.returncode == 0
                     else f"FAILED: {(r1.stderr or r2.stderr)[-300:]}")
    return {"ok": True, "action": "install", "target": str(root),
            "written": written, "deps": deps_note}


class ConnectorError(RuntimeError):
    pass


# ---------------------------------------------------------------- 基础工具
def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def md5_text(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def decode_claims(token: str) -> dict[str, Any]:
    """容错 JWT 解码（Token 原样发服务端，本地仅取 deviceID）。"""
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)
    raw = base64.urlsafe_b64decode(part)
    try:
        return json.loads(raw)
    except UnicodeDecodeError:
        return json.loads(raw.decode("utf-8", errors="replace"))


def load_tokens(path: Path | None = None) -> list[str]:
    path = Path(os.environ.get("HAILUO_CREDENTIAL_FILE") or path or DEFAULT_CRED)
    raw = path.read_text(encoding="utf-8")
    pattern = r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    tokens = re.findall(pattern, raw) or [ln.strip() for ln in raw.splitlines() if ln.strip()]
    tokens = list(dict.fromkeys(tokens))
    if not tokens:
        raise ConnectorError(f"凭证文件中没有可用账号: {path}")
    return tokens


def prompt_struct(prompt: str) -> str:
    return compact_json({
        "value": [{"type": "paragraph", "children": [{"text": prompt}]}],
        "length": len(prompt), "plainLength": len(prompt), "rawLength": len(prompt),
    })


def find_ffmpeg() -> str:
    cand = os.environ.get("H3_FFMPEG") or shutil.which("ffmpeg") \
        or r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
    if not Path(cand).exists() and not shutil.which(cand or "x"):
        raise ConnectorError("未找到 ffmpeg，请设置环境变量 H3_FFMPEG 指向 ffmpeg.exe")
    return cand


def download_media(url: str, output_path: Path, min_size: int = 64) -> None:
    import requests
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + f".{uuid.uuid4().hex}.part")
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)
    if tmp.stat().st_size < min_size:
        tmp.unlink(missing_ok=True)
        raise ConnectorError(f"下载文件为空或不完整: {output_path.name}")
    if min_size >= 1024 and b"ftyp" not in tmp.open("rb").read(12):
        tmp.unlink(missing_ok=True)
        raise ConnectorError("下载结果不是有效 MP4")
    tmp.replace(output_path)


# ---------------------------------------------------------------- H3 客户端
class H3Client:
    """官方网页签名接口的图片+视频统一客户端。"""

    def __init__(self, token: str, account_index: int = 1):
        self.token = token
        self.account_index = account_index
        claims = decode_claims(token)
        user = claims.get("user") if isinstance(claims.get("user"), dict) else {}
        self.device_id = str(user.get("deviceID") or "")
        import requests
        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json",
            "content-type": "application/json",
            "referer": "https://hailuoai.com/",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/140.0 Safari/537.36",
        })

    def _public_params(self, now_ms: int) -> dict[str, str]:
        values = {
            "device_platform": "web", "app_id": "3001", "version_code": "22203",
            "biz_id": "0", "unix": str(now_ms), "lang": "zh-Hans",
            "device_id": self.device_id, "os_name": "Mac", "browser_name": "chrome",
            "browser_language": "zh-CN", "browser_platform": "MacIntel",
            "screen_width": "1512", "screen_height": "982",
        }
        return {k: v for k, v in values.items() if v}

    def request(self, method: str, path: str, body: dict | None = None) -> Any:
        now_ms = time.time_ns() // 1_000_000
        sep = "&" if "?" in path else "?"
        signed = f"{path}{sep}{urllib.parse.urlencode(self._public_params(now_ms))}"
        m = method.upper()
        body_text = compact_json(body or {}) if m in {"POST", "DELETE"} else "{}"
        yy = md5_text(f"{urllib.parse.quote(signed, safe='')}_{body_text}{md5_text(str(now_ms))}ooui")
        resp = self.session.request(
            m, f"{API_ORIGIN}{signed}",
            data=body_text.encode() if m in {"POST", "DELETE"} else None,
            headers={"token": self.token, "yy": yy},
            timeout=120, allow_redirects=False)
        if 300 <= resp.status_code < 400:
            raise ConnectorError("海螺接口返回了非预期重定向")
        resp.raise_for_status()
        payload = resp.json()
        status = payload.get("statusInfo") or {}
        if status.get("code", 0) != 0:
            err = ConnectorError(status.get("message") or f"海螺接口错误 {status.get('code')}")
            err.code = status.get("code")
            raise err
        return payload.get("data")

    def balance(self) -> int:
        return int((self.request("GET", "/v1/api/billing/credit") or {}).get("total_credit") or 0)

    # ---------------- 图片 ----------------
    def image_catalog(self) -> list[dict]:
        data = self.request("GET", "/public/v2/api/multimodal/video/model/info") or {}
        catalog = []
        for raw in data.get("imageModels") or []:
            mid = str(raw.get("modelID") or "")
            if not mid:
                continue
            meta = raw.get("metaInfo") or {}
            parameter = raw.get("parameter") or {}
            catalog.append({
                "modelID": mid,
                "displayName": meta.get("displayName") or mid,
                "mode": meta.get("mode") or "image-reference",
                "maxSupportImageCount": meta.get("maxSupportImageCount"),
                "parameter": {
                    "resolutions": parameter.get("resolutions") or [],
                    "aspectRatios": parameter.get("aspectRatios") or [],
                    "qualities": parameter.get("qualities") or [],
                },
                "costs": raw.get("costs") or [],
                "defaultCost": raw.get("defaultCost"),
            })
        if not catalog:
            raise ConnectorError("官网未返回可用图片模型配置")
        return catalog

    @staticmethod
    def _option_values(options: list[dict]) -> list[str]:
        return [str(o["value"]) for o in options
                if o.get("canUse") is not False and not o.get("disable") and o.get("value") is not None]

    @staticmethod
    def _default_option(options: list[dict]) -> str | None:
        usable = [o for o in options if o.get("canUse") is not False and not o.get("disable")]
        sel = next((o for o in usable if o.get("defaultSelect")), None) or (usable[0] if usable else None)
        return str(sel["value"]) if sel and sel.get("value") is not None else None

    @staticmethod
    def _matches(allowed: list, value: str | None) -> bool:
        return not allowed or (value is not None and str(value) in {str(i) for i in allowed})

    def _cost_for(self, model: dict, resolution: str | None, quality: str | None) -> int:
        matches = []
        for cost in model.get("costs") or []:
            rc = cost.get("realCost")
            if rc is None or int(rc) <= 0:
                continue
            if self._matches(cost.get("resolutions") or [], resolution) and \
               self._matches(cost.get("qualities") or [], quality):
                matches.append(int(rc))
        if matches:
            return min(matches)
        dc = model.get("defaultCost")
        if dc is not None and int(dc) > 0 and not model.get("costs"):
            return int(dc)
        raise ConnectorError(f"模型 {model.get('modelID')} 不支持 {resolution}/{quality} 组合")

    def resolve_image_options(self, model_id="image-01", aspect_ratio="1:1",
                              resolution=None, quality=None) -> dict:
        selected = next((m for m in self.image_catalog() if m["modelID"] == model_id), None)
        if not selected:
            raise ConnectorError(f"官网没有模型 {model_id}")
        p = selected["parameter"]
        if aspect_ratio and aspect_ratio not in self._option_values(p["aspectRatios"]):
            raise ConnectorError(f"模型不支持画幅 {aspect_ratio}；可选 {self._option_values(p['aspectRatios'])}")
        combos = []
        for res in ([resolution] if resolution else self._option_values(p["resolutions"])) or [None]:
            for q in ([quality] if quality else self._option_values(p["qualities"])) or [None]:
                try:
                    combos.append((self._cost_for(selected, res, q), res, q))
                except ConnectorError:
                    continue
        if not combos:
            raise ConnectorError(f"模型 {model_id} 没有可用的官方参数组合")
        unit_cost, resolution, quality = min(combos, key=lambda i: i[0])
        return {
            "modelID": selected["modelID"], "modelName": selected["displayName"],
            "mode": selected["mode"], "aspectRatio": aspect_ratio or self._default_option(p["aspectRatios"]),
            "resolution": resolution, "quality": quality,
            "estimatedCost": unit_cost,
        }

    def submit_image(self, prompt: str, model_id="image-01", aspect_ratio="1:1") -> dict:
        opt = self.resolve_image_options(model_id, aspect_ratio)
        bal = self.balance()
        if bal < opt["estimatedCost"]:
            raise ConnectorError(f"余额不足: {bal} < {opt['estimatedCost']}")
        body = {
            "quantity": 1,
            "parameter": {
                "modelID": opt["modelID"], "desc": prompt, "fileList": [],
                "useOriginPrompt": True, "referenceMode": opt["mode"],
                "aspectRatio": opt["aspectRatio"],
            },
            "projectID": "0",
            "imageExtra": {"promptStruct": prompt_struct(prompt)},
        }
        for f in ("resolution", "quality"):
            if opt[f]:
                body["parameter"][f] = opt[f]
        data = self.request("POST", "/v2/api/multimodal/generate/image", body) or {}
        task = data.get("task") or {}
        if not data.get("id") or not task.get("batchID"):
            raise ConnectorError("图片提交响应缺少任务/批次 ID")
        return {"imageTaskId": str(data["id"]), "batchID": str(task["batchID"]),
                "estimatedCost": opt["estimatedCost"]}

    def image_processing(self, batch_id: str) -> dict:
        data = self.request("POST", "/api/feed/creation/my/processing", {
            "projectID": "0",
            "batchInfoList": [{"batchID": str(batch_id)}],
            "type": 1,
        }) or {}
        for batch in data.get("batchFeeds") or []:
            if str(batch.get("batchID")) == str(batch_id):
                return batch
        return {}

    # ---------------- 视频 ----------------
    def submit_video(self, prompt: str, duration: int = 4) -> dict:
        bal = self.balance()
        if bal < duration * 7:
            raise ConnectorError(f"余额不足: {bal} < {duration * 7}")
        body = {
            "quantity": 1,
            "parameter": {
                "modelID": "hailuo3.0-t2v", "desc": prompt, "fileList": [],
                "useOriginPrompt": True, "resolution": "768",
                "duration": int(duration), "aspectRatio": "9:16",
            },
            "videoExtra": {}, "projectID": "0",
        }
        data = self.request("POST", "/v2/api/multimodal/generate/video", body) or {}
        if not data.get("id"):
            raise ConnectorError("视频提交响应缺少任务 ID")
        return {"videoTaskId": str(data["id"])}

    def video_feed_raw(self, task_id: str) -> dict:
        try:
            return self.request("GET", f"/api/feed/detail?id={urllib.parse.quote(task_id)}") or {}
        except ConnectorError as e:
            if getattr(e, "code", None) == 2400016:
                return {}          # 详情未建立，视作 pending
            raise

    @staticmethod
    def _video_variant_urls(raw: dict) -> dict[str, str]:
        media = (((raw.get("feed") or {}).get("metaInfo") or {})
                 .get("videoMetaInfo") or {}).get("mediaInfo") or {}
        dl = media.get("downloadURL") or {}
        got: dict[str, str] = {}
        for key, url in dl.items():
            lk = key.lower()
            if "without" in lk:
                got["v0"] = url
            elif "hailuo" in lk:
                got["v1"] = url
            elif "ai" in lk:
                got["v2"] = url
            elif "watermark" in lk:
                got["v3"] = url
        return got


# ---------------------------------------------------------------- 图片合成
def merge_image(v1_path: str, v2_path: str, v3_path: str, out_path: str) -> dict:
    import numpy as np
    from PIL import Image
    from scipy import ndimage

    def union_box(boxes, pad, shape):
        x0 = min(b["x0"] for b in boxes) - pad
        y0 = min(b["y0"] for b in boxes) - pad
        x1 = max(b["x1"] for b in boxes) + pad
        y1 = max(b["y1"] for b in boxes) + pad
        return (max(0, x0), max(0, y0), min(shape[1] - 1, x1), min(shape[0] - 1, y1))

    def region_boxes(mask, thr=30):
        labeled, n = ndimage.label(mask)
        boxes = []
        for i in range(1, n + 1):
            ys, xs = np.where(labeled == i)
            if len(ys) >= thr:
                boxes.append({"x0": int(xs.min()), "x1": int(xs.max()),
                              "y0": int(ys.min()), "y1": int(ys.max()), "pixels": int(len(ys))})
        return boxes

    def detect(v1, v2, v3, thr=10):
        # v2 角标框线 alpha≈0.09，亮背景差异可能 <10，必须用 6；v1 logo 用 10
        d12 = (np.abs(v1 - v2).max(axis=2) > 6)
        d13 = (np.abs(v1 - v3).max(axis=2) > thr)
        d23 = (np.abs(v2 - v3).max(axis=2) > 6)
        return region_boxes(d12 & d13), region_boxes(d12 & d23)

    v1 = np.asarray(Image.open(v1_path).convert("RGB"), dtype=np.int16)
    v2i = np.asarray(Image.open(v2_path).convert("RGB"), dtype=np.int16)
    v3 = np.asarray(Image.open(v3_path).convert("RGB"), dtype=np.int16)
    h, w, _ = v1.shape
    v1_boxes, v2_boxes = detect(v1, v2i, v3)
    if not v1_boxes or not v2_boxes:
        raise ConnectorError("未检测到水印几何（三变体差分为空）")
    lx0, ly0, lx1, ly1 = union_box(v1_boxes, 6, (h, w))
    # badge 连通域过滤：跨度>=60 或像素>=150，防文字笔画噪声拉宽 bbox
    big = [b for b in v2_boxes if (b["x1"] - b["x0"]) >= 60 or (b["y1"] - b["y0"]) >= 60
           or b["pixels"] >= 150] or v2_boxes
    bx0, by0, bx1, by1 = union_box(big, 2, (h, w))
    bx1 = min(w - 1, bx1 + 14)   # 右框线亮背景不可检，右缘兜底；左缘保持紧

    logo_band = np.zeros((h, w), bool); logo_band[ly0:ly1 + 1, lx0:lx1 + 1] = True
    badge = np.zeros((h, w), bool); badge[by0:by1 + 1, bx0:bx1 + 1] = True
    replace_mask = logo_band & ~badge
    dead_mask = logo_band & badge

    base = np.asarray(Image.open(v1_path).convert("RGB"), dtype=np.uint8).copy()
    base[replace_mask] = np.asarray(Image.open(v2_path).convert("RGB"), dtype=np.uint8)[replace_mask]

    ring = ndimage.binary_dilation(dead_mask, iterations=8) & ~dead_mask
    ring_std = base[ring].astype(np.float64).std(axis=0).mean()
    if ring_std < 6.0:                      # 纯色背景快路径（约 1.5s）
        med = np.median(base[ring].astype(np.float64), axis=0)
        rng = np.random.default_rng(7)
        fill = np.clip(med[None, None, :] + rng.normal(0, 1.5, (h, w, 3)), 0, 255).astype(np.uint8)
        base[dead_mask] = fill[dead_mask]
        method = f"flat-fill(ring_std={ring_std:.1f})"
    else:                                   # LaMa 死区重建（掩码非零=待重建）
        from simple_lama_inpainting import SimpleLama
        lama = SimpleLama()
        mask_img = Image.fromarray(np.where(dead_mask, 255, 0).astype(np.uint8))
        base = np.asarray(lama(Image.fromarray(base), mask_img).convert("RGB"), dtype=np.uint8).copy()
        method = f"lama(ring_std={ring_std:.1f})"
    Image.fromarray(base).save(out_path)
    return {"method": method, "v1_logo_band": [lx0, ly0, lx1, ly1],
            "v2_badge": [bx0, by0, bx1, by1], "dead_zone_px": int(dead_mask.sum()),
            "replace_px": int(replace_mask.sum())}


# ---------------------------------------------------------------- 视频合成
def merge_video(v1_path: str, v2_path: str, v3_path: str, out_path: str) -> dict:
    import cv2
    import numpy as np
    from PIL import Image
    from simple_lama_inpainting import SimpleLama

    ffmpeg = find_ffmpeg()
    frames_dir = Path(out_path).parent / "frames_repair"
    frames_dir.mkdir(exist_ok=True)

    t0 = time.time()
    lama = SimpleLama()
    lama_load = time.time() - t0

    caps = [cv2.VideoCapture(p) for p in (v1_path, v2_path, v3_path)]
    fps = caps[0].get(cv2.CAP_PROP_FPS)
    n = int(min(c.get(cv2.CAP_PROP_FRAME_COUNT) for c in caps))

    in_l1 = np.zeros((VID_H, VID_W), bool); in_l1[L1[0]:L1[1], :] = True
    in_b2 = np.zeros((VID_H, VID_W), bool); in_b2[:, B2C[0]:B2C[1]] = True

    # 几何自检（独立 caps：seek 会污染主循环读取顺序）
    for probe in (5, n // 2, n - 6):
        p1 = cv2.VideoCapture(v1_path); p2 = cv2.VideoCapture(v2_path)
        p1.set(cv2.CAP_PROP_POS_FRAMES, probe); p2.set(cv2.CAP_PROP_POS_FRAMES, probe)
        f1 = p1.read()[1]; f2 = p2.read()[1]
        p1.release(); p2.release()
        if f1 is None or f2 is None:
            continue
        d = cv2.absdiff(f1, f2).max(axis=2) > 6
        rows = np.where(d[L1[0]:L1[1], :].any(axis=1))[0]
        if len(rows):
            br, bc = np.where(d[L1[0]:L1[1], :])
            print(f"selfcheck f{probe}: band rows {L1[0]+br.min()}-{L1[0]+br.max()} "
                  f"cols {bc.min()}-{bc.max()} px={len(br)}", flush=True)

    t1 = time.time()
    total_dead = 0
    last = None
    for idx in range(n):
        fr = [c.read()[1] for c in caps]
        if any(f is None for f in fr):
            if idx == 0:
                raise ConnectorError("视频首帧读取失败")
            fr = [f if f is not None else g for f, g in zip(fr, last)]
        last = fr
        v1, v2, v3 = fr
        d12 = cv2.absdiff(v1, v2).max(axis=2)
        d31 = cv2.absdiff(v3, v1).max(axis=2)
        d32 = cv2.absdiff(v3, v2).max(axis=2)
        marked = cv2.dilate(((d12 > 6) | (d31 > 6) | (d32 > 6)).astype(np.uint8) * 255,
                            np.ones((5, 5), np.uint8)) > 0
        base = v1.copy()
        logo_only = marked & in_l1 & ~in_b2
        base[logo_only] = v2[logo_only]
        dead = marked & in_l1 & in_b2
        total_dead += int(dead.sum())
        if dead.any():
            om = cv2.morphologyEx(cv2.dilate(dead.astype(np.uint8) * 255, np.ones((5, 5), np.uint8)),
                                  cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            crop = base[CY0:CY1, CX0:CX1]
            omc = om[CY0:CY1, CX0:CX1]
            res = lama(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)),
                       Image.fromarray(omc))
            o = cv2.cvtColor(np.array(res), cv2.COLOR_RGB2BGR)
            if o.shape[:2] != crop.shape[:2]:
                o = cv2.resize(o, (crop.shape[1], crop.shape[0]))
            m3 = cv2.GaussianBlur(omc, (0, 0), 1.0).astype(np.float32)[..., None] / 255.0
            base[CY0:CY1, CX0:CX1] = (crop.astype(np.float32) * (1 - m3)
                                      + o.astype(np.float32) * m3).astype(np.uint8)
        cv2.imwrite(str(frames_dir / f"{idx:05d}.png"), base)
        if idx % 40 == 0:
            print(f"  frame {idx}/{n}", flush=True)
    for c in caps:
        c.release()
    merge_s = time.time() - t1

    t2 = time.time()
    subprocess.run([ffmpeg, "-y", "-framerate", f"{fps:.4f}", "-i", str(frames_dir / "%05d.png"),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p",
                    out_path], capture_output=True, text=True)
    encode_s = time.time() - t2
    if not Path(out_path).exists():
        raise ConnectorError("ffmpeg 编码失败")
    return {"frames": n, "fps": round(fps, 2), "lama_load_s": round(lama_load, 1),
            "merge_s": round(merge_s, 1), "encode_s": round(encode_s, 1),
            "avg_dead_px": total_dead // max(n, 1)}


# ---------------------------------------------------------------- 管线
def _variant_urls_image(client: H3Client, batch_id: str) -> dict[str, str]:
    batch = client.image_processing(batch_id)
    feeds = batch.get("feeds") or []
    if not feeds:
        raise ConnectorError("批次详情无 feeds")
    media = (((feeds[0].get("metaInfo") or {}).get("imageMetaInfo") or {})
             .get("mediaInfo") or {})
    dl = media.get("downloadURL") or {}
    got: dict[str, str] = {}
    for key, url in dl.items():
        lk = key.lower()
        if "without" in lk:
            got["v0"] = url
        elif "hailuo" in lk:
            got["v1"] = url
        elif "ai" in lk:
            got["v2"] = url
        elif "watermark" in lk:
            got["v3"] = url
    return got


def run_image(args) -> dict:
    tokens = load_tokens()
    client = H3Client(tokens[args.account - 1], args.account)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    timing: dict[str, Any] = {}
    t0 = time.time()
    task = client.submit_image(args.prompt, args.model, args.ratio)
    timing["submit"] = round(time.time(), 3)
    print(f"submitted imageTaskId={task['imageTaskId']} cost={task['estimatedCost']}", flush=True)
    # 轮询
    while True:
        batch = client.image_processing(task["batchID"])
        feeds = batch.get("feeds") or []
        status = ((feeds[0].get("commonInfo") or {}).get("status")) if feeds else None
        if status == IMG_SUCCESS:
            break
        if status in IMG_FAILED:
            raise ConnectorError(f"图片生成失败 status={status}")
        if time.time() - t0 > 900:
            raise ConnectorError("图片轮询超时")
        time.sleep(3)
    timing["gen"] = round(time.time(), 3)
    # 取三变体（会员账号可能直接给无水印 URL）
    urls = _variant_urls_image(client, task["batchID"])
    task_id = str(((feeds[0].get("commonInfo") or {}).get("id")) or "task")
    paths: dict[str, str] = {}
    for tag in ("v0", "v1", "v2", "v3"):
        if tag in urls:
            p = outdir / f"{task_id}_{tag}.png"
            download_media(urls[tag], p)
            paths[tag] = str(p)
    timing["fetch"] = round(time.time(), 3)
    if "v0" in paths:                       # 官方无水印直出（会员）
        shutil.copyfile(paths["v0"], outdir / "final.png")
        merge_info = {"method": "official-without-watermark"}
    else:
        if not {"v1", "v2", "v3"} <= set(paths):
            raise ConnectorError(f"变体不全: {sorted(paths)}")
        merge_info = merge_image(paths["v1"], paths["v2"], paths["v3"],
                                 str(outdir / "final.png"))
    timing["repair"] = round(time.time(), 3)
    return {"ok": True, "type": "image", "out": str(outdir / "final.png"),
            "task_id": task_id, "timing": timing,
            "elapsed": {k: (timing[k] - v) for k, v in
                        zip(["submit", "gen", "fetch"], [t0, timing["submit"], timing["gen"]])}
            | {"total": timing["repair"] - t0},
            "merge": merge_info}


def run_video(args) -> dict:
    tokens = load_tokens()
    client = H3Client(tokens[args.account - 1], args.account)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    timing: dict[str, Any] = {}
    t0 = time.time()
    task = client.submit_video(args.prompt, args.duration)
    timing["submit"] = round(time.time(), 3)
    tid = task["videoTaskId"]
    print(f"submitted videoTaskId={tid}", flush=True)
    raw = {}
    while True:
        raw = client.video_feed_raw(tid)
        status = ((raw.get("feed") or {}).get("commonInfo") or {}).get("status")
        if status == VID_SUCCESS:
            break
        if status in VID_FAILED:
            raise ConnectorError(f"视频生成失败 status={status}")
        if time.time() - t0 > 1500:
            raise ConnectorError("视频轮询超时")
        time.sleep(10)
    timing["gen"] = round(time.time(), 3)
    urls = client._video_variant_urls(raw)
    paths: dict[str, str] = {}
    for tag in ("v0", "v1", "v2", "v3"):
        if tag in urls:
            p = outdir / f"{tid}_{tag}.mp4"
            download_media(urls[tag], p, min_size=1024)
            paths[tag] = str(p)
    timing["fetch"] = round(time.time(), 3)
    if "v0" in paths:
        shutil.copyfile(paths["v0"], outdir / "final.mp4")
        merge_info = {"method": "official-without-watermark"}
    else:
        if not {"v1", "v2", "v3"} <= set(paths):
            raise ConnectorError(f"变体不全: {sorted(paths)}")
        merge_info = merge_video(paths["v1"], paths["v2"], paths["v3"],
                                 str(outdir / "final.mp4"))
    timing["repair"] = round(time.time(), 3)
    return {"ok": True, "type": "video", "out": str(outdir / "final.mp4"),
            "task_id": tid, "timing": timing,
            "elapsed": {k: (timing[k] - v) for k, v in
                        zip(["submit", "gen", "fetch"], [t0, timing["submit"], timing["gen"]])}
            | {"total": timing["repair"] - t0},
            "merge": merge_info}


def main() -> None:
    parser = argparse.ArgumentParser(description="H3 无水印一键管线")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("balance", help="查询余额")
    p_img = sub.add_parser("image", help="无水印图片")
    p_img.add_argument("prompt")
    p_img.add_argument("--outdir", default="./h3-nowatermark-out")
    p_img.add_argument("--account", type=int, default=1)
    p_img.add_argument("--model", default="image-01")
    p_img.add_argument("--ratio", default="1:1")
    p_vid = sub.add_parser("video", help="无水印视频")
    p_vid.add_argument("prompt")
    p_vid.add_argument("--outdir", default="./h3-nowatermark-out")
    p_vid.add_argument("--account", type=int, default=1)
    p_vid.add_argument("--duration", type=int, default=4)
    p_ins = sub.add_parser("install", help="自安装：落出完整 skill 目录")
    p_ins.add_argument("target", nargs="?", default=None,
                       help="落盘位置（默认 ~/.workbuddy/skills/h3-nowatermark）")
    p_ins.add_argument("--deps", action="store_true",
                       help="同时把依赖装进当前解释器")
    args = parser.parse_args()

    # 自动落盘：脚本不在 skill 目录里（旁边没有 SKILL.md）时先安装再执行
    auto_note = None
    if args.cmd in ("balance", "image", "video"):
        sp = Path(__file__).resolve()
        sr = sp.parent.parent if sp.parent.name == "scripts" else sp.parent
        if not (sr / "SKILL.md").exists():
            auto_note = install_skill()
            print(json.dumps({"note": "auto-installed skill", **auto_note},
                             ensure_ascii=False), flush=True)

    try:
        if args.cmd == "install":
            result = install_skill(args.target, args.deps)
        elif args.cmd == "balance":
            tokens = load_tokens()
            result = {"ok": True,
                      "balances": {f"account{i+1}": H3Client(t, i + 1).balance()
                                   for i, t in enumerate(tokens)}}
        elif args.cmd == "image":
            result = run_image(args)
        else:
            result = run_video(args)
    except ConnectorError as e:
        result = {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
