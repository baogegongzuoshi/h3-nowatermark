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

从 `%USERPROFILE%\.codex\credentials\hailuo-tokens.txt` 读取（每行一个 JWT），
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
4. 放 Token：`%USERPROFILE%\.codex\credentials\hailuo-tokens.txt`（每行一个 JWT），
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
