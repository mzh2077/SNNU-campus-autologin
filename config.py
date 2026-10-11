# -*- coding: utf-8 -*-
"""
配置中心
========
把「门户地址 / 接口路径 / 请求字段名 / 运营商取值 / 超时重试」全部集中在这里。
门户改版时**只需要改本文件**，其余代码无需改动。

⚠️ 安全约定：本文件严禁写入任何真实账号 / 密码。
   账号密码保存在 %LOCALAPPDATA%\\CampusAutoLogin 下，经 Windows DPAPI 加密。
"""

import os
from dataclasses import dataclass, field, asdict

APP_NAME = "CampusAutoLogin"
APP_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# 1. 数据目录（凭据与配置的存放位置）
# ---------------------------------------------------------------------------
def data_dir() -> str:
    """
    返回配置目录。优先使用 %LOCALAPPDATA%，退回 %APPDATA%，再退回用户目录。
    该目录不会同步到 OneDrive 网盘，安全性优于放在「文档」目录。
    """
    for env in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env)
        if base:
            return os.path.join(base, APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".campus_autologin")


def cred_file() -> str:
    """加密后的凭据文件路径。内容为 DPAPI 密文，非明文。"""
    return os.path.join(data_dir(), "credentials.bin")


def config_file() -> str:
    """明文可读的运行配置（非敏感：门户地址、运营商等）。"""
    return os.path.join(data_dir(), "settings.json")


def log_file() -> str:
    return os.path.join(data_dir(), "run.log")


# ---------------------------------------------------------------------------
# 2. 门户端点配置
# ---------------------------------------------------------------------------
# 经实测，该门户为「深澜 snnuportal」认证系统（陕西师范大学）：
#   - http://202.117.144.205:8603/snnuportal/  → 302 跳转至 userstatus.jsp
#   - userstatus.jsp：在线时显示账号/登录时间/内网 IP；离线时应显示登录表单
#   - /zili/index.php：自助服务系统登录，表单字段 mode/login/passwd
#   注意：门户页面 charset 为 GB2312，但 /zili/ 的错误响应是 UTF-8，
#   因此下面按端点分别配置编码，不要全局统一。
#
# ── 适配其它学校 / 门户改版时改这里 ──────────────────────────────────────────

@dataclass
class Endpoint:
    """单个 HTTP 端点描述。"""
    name: str                      # 端点用途标识，写入日志便于排查
    url: str                       # 完整 URL
    encoding: str = "utf-8"        # 该端点响应的字符编码
    timeout: float = 8.0           # 单次请求超时（秒）


@dataclass
class PortalConfig:
    # ---- 状态页：用于判断「是否已在线」 ----
    # 该页面即用户提供的地址，是程序的判定入口。
    status_url: str = "http://202.117.144.205:8603/snnuportal/userstatus.jsp"
    status_encoding: str = "gb18030"     # 实测 GB2312，用 gb18030 兼容更全

    # ---- 登录提交端点（备用方案，见下方 auto_mode 说明）----
    # 自助服务系统表单：POST mode=login / login=账号 / passwd=密码
    login_url: str = "http://202.117.144.205:80/zili/index.php"
    login_encoding: str = "utf-8"        # 实测该端点返回 UTF-8

    # ---- 登录接口的表单字段名（门户改版时主要改这里）----
    login_mode_field: str = "mode"
    login_mode_value: str = "login"
    login_user_field: str = "login"
    login_pass_field: str = "passwd"

    # ---- 运营商（yys）----
    # snnuportal 的账号常带运营商后缀，形式为「学号@运营商」。
    # 移动 = mobile，联通 = unicom，电信 = telecom，教育网/未分运营商可留空。
    carrier: str = "mobile"

    # ---- snnuportal 登录页的备用字段名（备用登录路径使用）----
    alt_user_field: str = "account"
    alt_pass_field: str = "password"
    alt_yys_field: str = "yys"

    # ---- 登录策略 ----
    # "status" = 仅查状态，已在线即成功，未在线再尝试登录（默认，最安全）
    # "always" = 每次强制走一次登录提交（部分学校需要，用于刷新在线时长）
    auto_mode: str = "status"

    # ---- 账号格式 ----
    # True  : 输入时可直接填「学号@运营商」，程序原样使用
    # False : 只填学号，程序按下方 carrier 自动拼接后缀
    account_include_carrier: bool = True

    # ---- 网络行为 ----
    request_timeout: float = 8.0      # 单次请求超时
    max_retries: int = 2              # 失败重试次数
    retry_delay: float = 1.5          # 重试间隔（秒）
    verify_tls: bool = False          # 自签证书校园网可置 False

    # ---- 交互行为 ----
    # 登录成功后是否自动关闭窗口：
    #   "auto"  = 倒计时结束自动关闭（符合「连接完自动关闭」的需求）
    #   "enter" = 等待用户按回车关闭（便于看清结果）
    #   "keep"  = 不自动关闭
    close_on_success: str = "auto"
    auto_close_delay: float = 3.0     # auto 模式下的倒计时秒数
    # 登录失败时保留窗口，避免用户看不到错误原因
    keep_window_on_failure: bool = True

    # ---- 浏览器伪装 ----
    # 实测该门户对 curl 默认 UA 返回 403，必须伪装成浏览器
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    # ---- 状态页判定关键词（门户改版时改这里）----
    # 页面出现「当前登录账号」说明已在线
    online_markers: list = field(default_factory=lambda: [
        "当前登录账号", "登录时间", "断开连接", "logoff",
    ])
    # 页面出现这些关键词说明当前未登录、停留在登录页
    offline_markers: list = field(default_factory=lambda: [
        "account", "password", "登录", "登陆",
    ])
    # 登录错误提示关键词 → 映射到状态码，用于区分「密码错」等
    error_markers: dict = field(default_factory=lambda: {
        # 注意「帐号」是错别字变体，门户实际用的是「帐号或密码错误」，
        # 两种写法都要匹配，否则漏判会把密码错误当成登录成功。
        "bad_credential": ["帐号或密码错误", "账号或密码错误", "密码错误",
                           "用户不存在", "帐号不存在", "账号不存在", "登录失败"],
        "need_captcha":   ["验证码错误", "请输入验证码"],
        "rate_limited":   ["过于频繁", "稍后再试", "已锁定"],
        "not_open":       ["暂停", "未开放", "禁止"],
    })

    # ---- 密码正确性校验专用的成功标志 ----
    # 实测：snnuportal 在本机已在线时，即使密码错误也返回含
    # 「当前登录账号」的页面，**无法**用它判断密码对错；
    # 而 /zili/index.php 会明确返回「帐号或密码错误」，
    # 因此校验密码必须优先使用 zili 端点。
    verify_success_markers: list = field(default_factory=lambda: [
        "退出登录", "退出", "我的状态", "当前登录", "已登录", "欢迎",
    ])

    def to_dict(self) -> dict:
        return asdict(self)


# 全局单例：程序各处通过 `portal()` 获取
_CONFIG = PortalConfig()


def portal() -> PortalConfig:
    return _CONFIG


def load_overrides() -> None:
    """
    从 settings.json 读取用户/学校差异化的字段覆盖默认配置。
    未写入的文件字段保持 PortalConfig 默认值。

    只允许覆盖非敏感字段——账号密码不在这里存。
    """
    import json
    path = config_file()
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if hasattr(_CONFIG, key):
            setattr(_CONFIG, key, value)


def save_current() -> None:
    """把当前内存中的配置写回 settings.json（用于「修改设置」功能）。"""
    import json
    os.makedirs(data_dir(), exist_ok=True)
    with open(config_file(), "w", encoding="utf-8") as f:
        json.dump(_CONFIG.to_dict(), f, ensure_ascii=False, indent=2)