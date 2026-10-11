# -*- coding: utf-8 -*-
"""
控制台彩色输出
==============
Windows 传统控制台默认不支持 ANSI 颜色，需要先调用
`SetConsoleTextAttribute` 手动切换颜色，否则 \033[31m 会被原样打印出来。

这里做能力探测 + 自动降级：
  - Windows 控制台  → 真实红字 / 绿字
  - 不支持 ANSI 的环境 → 退回普通文字，不打印乱码
"""

import os
import sys

# 是否已初始化（避免重复调用系统 API）
_initialized = False
_use_ansi = False


def init_color() -> bool:
    """
    初始化颜色支持，返回是否可用。

    优先尝试启用 Windows 10/11 的 VT 序列处理（可同时支持
    前景色 + 背景色 + 亮色，效果最好）；失败则退回 Win32 API 方案。
    """
    global _initialized, _use_ansi
    if _initialized:
        return _use_ansi

    # 非 TTY（重定向/管道）时不上色，避免污染日志与管道输出
    if not sys.stdout.isatty():
        _initialized = True
        return False

    if os.name != "nt":
        _use_ansi = True
        _initialized = True
        return _use_ansi

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        STD_OUTPUT_HANDLE = -11
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(
                handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
            _use_ansi = True
    except Exception:
        _use_ansi = False

    _initialized = True
    return _use_ansi


# ANSI 颜色码
_RESET = "\033[0m"
_RED = "\033[91m"        # 亮红（比标准红更醒目）
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_CYAN = "\033[96m"
_DIM = "\033[2m"


def red(text: str) -> str:
    """红色文字。"""
    return f"{_RED}{text}{_RESET}" if init_color() else text


def green(text: str) -> str:
    return f"{_GREEN}{text}{_RESET}" if init_color() else text


def yellow(text: str) -> str:
    return f"{_YELLOW}{text}{_RESET}" if init_color() else text


def cyan(text: str) -> str:
    return f"{_CYAN}{text}{_RESET}" if init_color() else text


def dim(text: str) -> str:
    return f"{_DIM}{text}{_RESET}" if init_color() else text


def supports_color() -> bool:
    return init_color()


# ---------------------------------------------------------------------------
# Windows 原生颜色（备用方案）
# ---------------------------------------------------------------------------
class WinColor:
    """
    直接调用 Windows 控制台 API 设置文字颜色。
    当 ANSI 不可用时作为备选方案（例如极老的控制台主机）。
    """

    RED = 0x04        # FOREGROUND_RED
    GREEN = 0x02
    YELLOW = 0x06
    CYAN = 0x03
    WHITE = 0x07
    RESET = 0x07

    _kernel32 = None
    _handle = None

    @classmethod
    def _ensure(cls) -> bool:
        # 无真实控制台（重定向/管道）时不上色
        if not sys.stdout.isatty():
            return False
        if cls._handle is not None:
            return True
        if os.name != "nt":
            return False
        try:
            import ctypes
            cls._kernel32 = ctypes.windll.kernel32
            cls._handle = cls._kernel32.GetStdHandle(-11)
            return True
        except Exception:
            return False

    @classmethod
    def set_text(cls, color: int) -> None:
        """设置后续输出的文字颜色。"""
        if cls._ensure():
            try:
                cls._kernel32.SetConsoleTextAttribute(cls._handle, color)
            except Exception:
                pass

    @classmethod
    def reset(cls) -> None:
        cls.set_text(cls.RESET)

    @classmethod
    def print_red(cls, text: str) -> None:
        """以红色打印一行，然后自动恢复默认色。"""
        if not cls._ensure():
            print(text)
            return
        cls.set_text(cls.RED)
        print(text, flush=True)
        cls.reset()

    @classmethod
    def print_green(cls, text: str) -> None:
        if not cls._ensure():
            print(text)
            return
        cls.set_text(cls.GREEN)
        print(text, flush=True)
        cls.reset()