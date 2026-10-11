# -*- coding: utf-8 -*-
"""
打包脚本：一键生成可双击运行的 exe
==================================
用法：
    python build.py

产物：
    dist/校园网自动登录.exe   —— 单文件，双击即可运行，无需安装 Python

说明：
  - 主程序是控制台程序（用户要求命令行界面），
    因此不加 -w 参数，保留黑色控制台窗口。
  - 图标由 make_icon.py 生成（"师"字，校园网主题青色）。
    若 icon.ico 不存在，会自动调用 make_icon.py 生成。
  - DPAPI 加密为 Windows 原生能力，无需打包额外依赖；
    cryptography 仅在非 Windows 兜底时使用，一并打进去以保证跨平台可运行。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "校园网自动登录"
ICON_PATH = os.path.join(HERE, "icon.ico")


def ensure_icon() -> str | None:
    """确保图标存在；没有则调用 make_icon.py 生成。返回图标路径。"""
    if os.path.exists(ICON_PATH):
        return ICON_PATH
    script = os.path.join(HERE, "make_icon.py")
    if not os.path.exists(script):
        print("[!] 未找到 icon.ico 且无 make_icon.py，将不设置图标。")
        return None
    print("未找到 icon.ico，正在生成图标 …")
    try:
        subprocess.run([sys.executable, script], cwd=HERE, check=True)
        return ICON_PATH if os.path.exists(ICON_PATH) else None
    except Exception as e:
        print(f"[!] 图标生成失败（{e}），将不设置图标。")
        return None


def build() -> int:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",                 # 单文件 exe，方便携带
        "--console",                 # 保留命令行窗口
        "--name", APP_NAME,
    ]

    icon = ensure_icon()
    if icon:
        cmd += ["--icon", icon]
        print(f"使用图标：{icon}")

    cmd += [
        "--hidden-import", "cryptography.hazmat.primitives.ciphers",
        "--hidden-import", "ctypes.wintypes",
        "--exclude-module", "tkinter",
        "--exclude-module", "matplotlib",
        "--exclude-module", "numpy",
        "--exclude-module", "PIL",     # 图标仅在打包期用，运行时无需 Pillow
        os.path.join(HERE, "main.py"),
    ]
    print("\n执行：", " ".join(cmd), "\n")
    result = subprocess.run(cmd, cwd=HERE)
    if result.returncode != 0:
        print("\n打包失败，请检查上方错误信息。")
        return result.returncode

    exe_path = os.path.join(HERE, "dist", APP_NAME + ".exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / 1024 / 1024
        print("\n" + "=" * 50)
        print(f"打包成功：{exe_path}")
        print(f"文件大小：{size_mb:.1f} MB")
        # 顺带把图标复制到 dist，便于用户替换/查看
        try:
            import shutil
            shutil.copy2(ICON_PATH, os.path.join(HERE, "dist", "icon.ico"))
        except Exception:
            pass
        print("=" * 50)
        return 0
    print("打包结束但未找到 exe，请检查 dist 目录。")
    return 1


if __name__ == "__main__":
    sys.exit(build())