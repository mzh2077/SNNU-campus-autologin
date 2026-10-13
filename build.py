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

import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_NAME = "校园网自动登录"
ICON_PATH = os.path.join(HERE, "icon.ico")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_installed_copies() -> list[str]:
    """
    找出本机已安装/使用中的 exe 副本。

    场景：用户常把 exe 复制到别处（如 Documents\\App）并让开机自启指向它。
    若只重新构建 dist/ 而不更新这些副本，开机仍会运行**旧版本**，
    表现为"改了代码却没生效"。

    这里主动扫描常见位置 + 读取开机自启注册表项，
    确保构建后能提示并替换所有副本。
    """
    name = APP_NAME + ".exe"
    found: list[str] = []

    # 1) 开机自启项指向的位置（最权威——这才是实际运行的副本）
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            n = winreg.QueryInfoKey(k)[1]
            for i in range(n):
                val_name, val_data, _ = winreg.EnumValue(k, i)
                if val_name == "CampusAutoLogin" and val_data:
                    exe = val_data.split('"')[0].split(" --")[0].strip()
                    if exe.lower().endswith(".exe") and os.path.exists(exe):
                        found.append(exe)
    except Exception:
        pass

    # 2) 常见位置
    home = os.path.expanduser("~")
    for folder in ("Desktop", "Downloads", "Documents", "App"):
        root = os.path.join(home, folder)
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, files in os.walk(root):
            # 限制扫描深度，避免遍历整个文档库
            if dirpath[len(root):].count(os.sep) >= 2:
                dirnames[:] = []
                continue
            if name in files:
                found.append(os.path.join(dirpath, name))

    # 去重，并排除项目自身的 dist
    dist_exe = os.path.abspath(os.path.join(HERE, "dist", name))
    result = []
    for p in found:
        ap = os.path.abspath(p)
        if ap == dist_exe:
            continue
        if ap not in result:
            result.append(ap)
    return result


def sync_copies(new_exe: str) -> list[tuple[str, str]]:
    """
    把新构建的 exe 同步到所有已安装副本，返回 [(路径, 状态)]。

    若某个副本正在运行（开机自启的进程），Windows 会锁文件导致复制失败，
    此时给出明确提示而不是静默跳过。
    """
    results = []
    for copy_path in find_installed_copies():
        try:
            if os.path.abspath(copy_path) == os.path.abspath(new_exe):
                results.append((copy_path, "同一文件，跳过"))
                continue
            same = (os.path.exists(copy_path)
                    and os.path.getsize(copy_path) == os.path.getsize(new_exe)
                    and _sha256(copy_path) == _sha256(new_exe))
            if same:
                results.append((copy_path, "已是最新，无需替换"))
                continue
            shutil.copy2(new_exe, copy_path)
            results.append((copy_path, "✓ 已替换为新版"))
        except PermissionError:
            results.append((copy_path,
                            "✗ 替换失败：文件被占用（程序正在运行），"
                            "请关闭后重新执行 build.py"))
        except Exception as e:
            results.append((copy_path, f"✗ 替换失败：{e}"))
    return results


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

        # —— 自动同步到本机所有已安装副本（含开机自启指向的那份）——
        copies = find_installed_copies()
        if copies:
            print("\n检测到本机已安装的副本，正在同步新版：")
            for path, state in sync_copies(exe_path):
                print(f"  {state}")
                print(f"    {path}")
            print("\n提示：开机自启运行的是上面这些副本，"
                  "已全部替换为本次构建的版本。")
        else:
            print("\n（本机未检测到其他 exe 副本，无需替换）")

        print("=" * 50)
        return 0
    print("打包结束但未找到 exe，请检查 dist 目录。")
    return 1


if __name__ == "__main__":
    sys.exit(build())