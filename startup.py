# -*- coding: utf-8 -*-
"""
开机自启动管理
==============
通过 Windows 注册表实现「开机自启」，并且**能在任务管理器的
『启动』标签页中被看到和管理**（可启用/禁用/删除）。

为什么用注册表而不是自建启动文件夹
-----------------------------------
任务管理器「启动」页只收录以下位置的启动项：
  HKEY_CURRENT_USER  \\Software\\Microsoft\\Windows\\CurrentVersion\\Run
  HKEY_LOCAL_MACHINE \\Software\\Microsoft\\Windows\\CurrentVersion\\Run
放进「启动」文件夹或计划任务的程序**不会**出现在这里（需另装
「任务管理器隐藏」类工具才能看到），所以本模块统一写注册表。

关键实现细节
------------
1. 写在 HKCU（当前用户）下，**不需要管理员权限**。
2. 写完 Run 键后，还必须同步
   `HKCU\\...\\Explorer\\StartupApproved\\Run` 的同名值：
       02 00 00 00 + 8 字节时间戳 → 任务管理器显示「已启用」
       03 00 00 00 + 8 字节时间戳 → 任务管理器显示「已禁用」
   若不写这一项，部分系统上任务管理器会把它当作「已禁用」。
3. 程序路径变化（用户移动了 exe）后，启动项会失效，
   因此提供 repair() 自动按当前路径重写。
"""

import os
import sys

try:
    import winreg
    _HAS_WINREG = True
except ImportError:
    _HAS_WINREG = False


# 注册表路径
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"

# 启动项名称：任务管理器「启动」标签页显示的就是这个名字
APP_TITLE = "校园网自动登录"
APP_VALUE_NAME = "CampusAutoLogin"

# 任务管理器状态字节
_STATE_ENABLED = b"\x02"
_STATE_DISABLED = b"\x03"


def is_supported() -> bool:
    """仅支持 Windows。"""
    return _HAS_WINREG and os.name == "nt"


# ---------------------------------------------------------------------------
# 获取当前程序的启动命令
# ---------------------------------------------------------------------------
def get_executable() -> str:
    """
    返回应当被启动的完整路径。

    打包成 exe 后 sys.executable 即 exe 本身；
    以脚本方式运行时，返回 pythonw.exe + 脚本路径（避免开机弹出黑窗）。
    """
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)

    # 脚本方式运行：sys.argv[0] 才是脚本路径。
    # 若是以 python -c "..." 内联执行，则 argv[0] 为 "-c"，不是有效脚本，
    # 此时回退到同目录下的 main.py。
    script = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    if not script or script.startswith("-") or not os.path.exists(script):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")

    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if os.path.exists(pythonw):
        return f'"{pythonw}" "{script}"'
    return f'"{sys.executable}" "{script}"'


def build_command(quiet: bool = True) -> str:
    """
    组装启动命令字符串。

    quiet=True 时附加 --quiet：开机自启会静默执行，
    不弹出控制台窗口、不显示提示，失败也只在日志里记录。
    """
    cmd = get_executable()
    if quiet:
        cmd += " --quiet"
    return cmd


# ---------------------------------------------------------------------------
# 读写注册表
# ---------------------------------------------------------------------------
def _set_approved(state: bytes) -> None:
    """写入 StartupApproved，让任务管理器正确显示启用/禁用状态。"""
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            # 2 字节状态 + 8 字节 FILETIME（任务管理器按此格式解析）
            winreg.SetValueEx(key, APP_VALUE_NAME, 0, winreg.REG_BINARY,
                              state + b"\x00" * 8)
    except OSError:
        # 该键缺失不影响启动项本身，忽略即可
        pass


def is_enabled() -> bool:
    """启动项是否存在且未被任务管理器禁用。"""
    if not is_supported():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_VALUE_NAME)
    except (FileNotFoundError, OSError):
        return False
    return bool(value)


def is_disabled_by_user() -> bool:
    """用户是否在任务管理器里手动禁用了它。"""
    if not is_supported():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as key:
            data, _ = winreg.QueryValueEx(key, APP_VALUE_NAME)
        return bool(data) and data[:1] == _STATE_DISABLED
    except (FileNotFoundError, OSError):
        return False


def get_command() -> str:
    """读取当前已写入的启动命令。"""
    if not is_supported():
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_VALUE_NAME)
        return str(value)
    except (FileNotFoundError, OSError):
        return ""


def enable(quiet: bool = True) -> tuple[bool, str]:
    """
    添加/启用开机自启。
    返回 (是否成功, 提示信息)。
    """
    if not is_supported():
        return False, "仅支持 Windows 系统"

    command = build_command(quiet)
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_VALUE_NAME, 0, winreg.REG_SZ, command)
    except OSError as e:
        return False, f"写入注册表失败：{e}"

    _set_approved(_STATE_ENABLED)
    return True, "已设置开机自动启动"


def disable() -> tuple[bool, str]:
    """
    删除开机自启启动项。
    返回 (是否成功, 提示信息)。
    """
    if not is_supported():
        return False, "仅支持 Windows 系统"

    removed = False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_VALUE_NAME)
            removed = True
    except FileNotFoundError:
        pass
    except OSError as e:
        return False, f"删除启动项失败：{e}"

    # 一并清理状态记录，避免残留
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_VALUE_NAME)
    except (FileNotFoundError, OSError):
        pass

    return True, "已取消开机自动启动" if removed else "启动项本就不存在"


def repair() -> tuple[bool, str]:
    """
    启动项存在但指向的路径已失效时（如 exe 被移动），
    按当前实际路径重写，使其恢复可用。
    """
    if not is_enabled():
        return False, "启动项不存在，无需修复"
    current = build_command()
    if get_command() == current:
        return False, "启动项路径正常，无需修复"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_VALUE_NAME, 0, winreg.REG_SZ, current)
    except OSError as e:
        return False, f"修复失败：{e}"
    _set_approved(_STATE_ENABLED)
    return True, "已修复启动项路径"


def describe() -> str:
    """生成状态描述，用于命令行展示。"""
    if not is_supported():
        return "当前系统不支持开机自启（仅 Windows 可用）"
    if not is_enabled():
        return "开机自启：未开启"
    if is_disabled_by_user():
        return "开机自启：已添加，但在任务管理器中被禁用"
    return "开机自启：已开启"