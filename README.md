# h3-nowatermark

海螺 H3（hailuoai.com）无水印一键生成管线（图片 + 视频）。

一条命令完成：官方渠道生成 → 抓取 `-1/-2/-3` 三个水印变体 → 几何探测互补合成 + LaMa 死区重建 → 输出无水印成品与分段耗时。合成全程本地计算，不消耗额外积分。

> 本项目仅供个人学习与技术交流，请尊重生成服务方的服务条款，勿用于商业去水印用途。

## 仓库结构

```
h3-nowatermark/
├── SKILL.md                          # WorkBuddy skill 定义（用法/约束/已知限制）
├── scripts/
│   ├── h3_nowatermark.py             # 主程序：生成 + 取变体 + 无水印合成（单文件）
│   ├── requirements.txt
│   └── setup.cmd                     # Windows 一键建 venv 装依赖
└── portable/
    └── h3-nowatermark.skill.md       # 便携安装包：单文件携带全部内容，首次运行自动解包注册
```

## 快速开始

```bash
# 1. 安装依赖（Windows）
cd scripts && setup.cmd
# 或手动: pip install requests numpy pillow scipy opencv-contrib-python-headless torch
#         pip install --no-deps simple-lama-inpainting

# 2. 放置凭据（每行一个 JWT，来自你自己的海螺账号，仓库不含任何凭据）
#    %USERPROFILE%\.codex\credentials\hailuo-tokens.txt
#    或环境变量 HAILUO_CREDENTIAL_FILE

# 3. 运行
python scripts/h3_nowatermark.py balance                              # 查余额
python scripts/h3_nowatermark.py image "a cute cat" --outdir out      # 无水印图片 (1 积分/张)
python scripts/h3_nowatermark.py video "a cat" --outdir out --duration 4   # 无水印 4s 视频 (7 积分/秒)
```

便携安装包用法见 `portable/h3-nowatermark.skill.md` 内的「便携分发」章节——拷一个 .md 到新电脑，AI 解包或一行命令即可注册到 WorkBuddy 工作区。

## 实测耗时（Windows，2026-09-17 批量验证 12/12 成功）

| 类型 | 生成 | 取三变体 | 本地修复 | 端到端 |
|---|---|---|---|---|
| 图片 1024×1024 | 19–28s | ~1s | 16–18s | ≈40s |
| 视频 4s 768×1344@24fps | ~101s | ~2s | ~74s | ≈3min |

## 已知限制

- 死区（logo ∩ 角标交叠区，约 13000px）正中压"独立图形"（圆点/logo 图形）时 LaMa 可能补不出
- 视频半透明角标检测依赖差分阈值，极端背景可能需扩边兜底
- 水印几何在 1024×1024 / 768×1344 下实测固定，其它分辨率由自动探测适配

## License

MIT
