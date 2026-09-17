@echo off
rem H3 无水印 skill 一键环境安装（Windows）
rem 用法: 在本目录执行  setup.cmd
rem 产物: 本目录下 .venv 虚拟环境，之后用 .venv\Scripts\python.exe h3_nowatermark.py ...
cd /d "%~dp0"
python -m venv .venv || py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
rem simple-lama-inpainting 依赖声明过严，用 --no-deps 安装，torch 单独装
pip install requests numpy pillow scipy opencv-contrib-python-headless torch
pip install --no-deps simple-lama-inpainting
echo.
echo 安装完成。运行示例:
rem   .venv\Scripts\python.exe h3_nowatermark.py balance
rem   .venv\Scripts\python.exe h3_nowatermark.py image "a cute cat" --outdir out
rem 注意: 首次跑图片/视频会自动下载 LaMa 修复模型(约200MB, 需外网)。
pause
