# -*- coding: utf-8 -*-
"""
门户网络层
==========
封装对「深澜 snnuportal / 自助服务系统」的请求与结果判定。

实测结论（用于理解代码为何这样写）
----------------------------------
1. 门户对 curl 默认 UA 返回 **403**，必须伪装浏览器 UA，否则一切请求失败。
2. http://202.117.144.205:8603/snnuportal/ 会 302 跳到 userstatus.jsp，
   即 userstatus.jsp 是统一入口：
     - 已在线 → 页面含「当前登录账号 / 登录时间 / 断开连接」字样
     - 未在线 → 呈现登录表单（含 account、password 输入框）
3. 登录表单 POST 到 login.jsp，字段为 account / password / yys（运营商）。
4. 自助服务系统 http://202.117.144.205:80/zili/index.php 表单字段为
   mode=login / login / passwd，且其错误响应是 **UTF-8**（与主门户的 GB2312 不同）。
5. snnuportal 账号常带运营商后缀，形如 `2024010101@mobile`。
"""

import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from config import PortalConfig


class LoginStatus:
    """登录结果状态枚举（值即程序内部标识）。"""
    OK = "OK"                     # 登录成功
    ALREADY_ONLINE = "ONLINE"     # 本来就已在线
    BAD_CREDENTIAL = "BADCRED"    # 账号或密码错误
    NEED_CAPTCHA = "CAPTCHA"      # 需要验证码
    RATE_LIMITED = "RATE"         # 尝试过于频繁 / 被锁定
    UNREACHABLE = "UNREACHABLE"   # 校园网不可达
    TIMEOUT = "TIMEOUT"           # 请求超时
    PROTOCOL_ERROR = "PROTOCOL"   # 返回内容不符合预期
    UNKNOWN_ERROR = "UNKNOWN"     # 其它错误
    SKIPPED = "SKIPPED"           # 已在线，跳过校验

    MESSAGES = {
        OK:              "登录成功",
        ALREADY_ONLINE:  "已在线",
        BAD_CREDENTIAL:  "账号或密码错误",
        NEED_CAPTCHA:    "需要输入验证码",
        RATE_LIMITED:    "尝试过于频繁或账号被锁定",
        UNREACHABLE:     "校园网不可达",
        TIMEOUT:         "请求超时",
        PROTOCOL_ERROR:  "门户返回内容异常",
        UNKNOWN_ERROR:   "未知错误",
        SKIPPED:         "已在线，跳过密码校验",
    }

    @classmethod
    def message(cls, status: str) -> str:
        return cls.MESSAGES.get(status, cls.MESSAGES[cls.UNKNOWN_ERROR])

    @classmethod
    def is_good(cls, status: str) -> bool:
        return status in (cls.OK, cls.ALREADY_ONLINE)


# 配置 error_markers 使用可读键名，这里映射到 LoginStatus 常量
MARKER_TO_STATUS = {
    "bad_credential": LoginStatus.BAD_CREDENTIAL,
    "need_captcha":   LoginStatus.NEED_CAPTCHA,
    "rate_limited":   LoginStatus.RATE_LIMITED,
    "not_open":       LoginStatus.UNKNOWN_ERROR,
}


class PortalClient:
    """与校园网门户交互的客户端。"""

    def __init__(self, cfg: PortalConfig):
        self.cfg = cfg

    # ------------------------------------------------------------------
    # 底层 HTTP
    # ------------------------------------------------------------------
    def _open(self, url: str, data: bytes | None = None,
              timeout: float | None = None) -> tuple[int, str]:
        """
        发起请求并返回 (http状态码, 正文文本)。
        网络异常统一转换为 PortalClient 内部状态，不向上抛。
        """
        headers = {
            "User-Agent": self.cfg.user_agent,          # 必须：否则 403
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "close",                      # 避免连接复用挂起
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = urllib.request.Request(url, data=data, headers=headers)
        opener = urllib.request.build_opener()
        # 门户可能挂在带认证/怪跳转的代理后面，统一关闭代理继承
        opener.add_handler(urllib.request.ProxyHandler({}))

        try:
            with opener.open(req, timeout=timeout or self.cfg.request_timeout) as resp:
                raw = resp.read()
                enc = self._guess_encoding(resp.headers.get("Content-Type", ""), raw)
                return resp.status, raw.decode(enc, errors="replace")
        except urllib.error.HTTPError as e:
            # 403/404 也要把响应体带回来，页面里通常写着错误原因
            try:
                raw = e.read()
                return e.code, raw.decode(self._guess_encoding("", raw), errors="replace")
            except Exception:
                return e.code, ""
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
                raise TimeoutError(str(reason))
            raise ConnectionError(str(reason))
        except (TimeoutError, ConnectionError):
            raise
        except Exception as e:
            raise ConnectionError(str(e))

    def _guess_encoding(self, content_type: str, raw: bytes) -> str:
        """按 Content-Type → meta charset → 兜底顺序判定编码。"""
        m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
        if m:
            return m.group(1).lower()
        head = raw[:1024].decode("latin-1", errors="ignore").lower()
        m = re.search(r'charset=["\']?([\w-]+)', head)
        if m:
            return m.group(1).lower()
        return self.cfg.status_encoding

    # ------------------------------------------------------------------
    # 网络就绪探测
    # ------------------------------------------------------------------
    def is_network_ready(self, timeout: float | None = None) -> bool:
        """
        探测是否已连上校园网（门户是否可达）。

        开机后 WiFi/网线就绪往往需要几秒，此时门户不可达，
        直接登录只会得到"校园网不可达"。本方法用于等待网络就绪。

        与 check_status 的区别：不解析页面内容、不判断登录状态，
        只关心"能不能连上门户"，因此不受在线状态影响。
        """
        saved = self.cfg.request_timeout
        if timeout is not None:
            self.cfg.request_timeout = timeout
        try:
            code, _ = self._open(self.cfg.status_url)
            # 只要门户有响应（哪怕 403/404）就说明网络通了
            return code < 600
        except (TimeoutError, ConnectionError, OSError):
            return False
        except Exception:
            return False
        finally:
            self.cfg.request_timeout = saved

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def check_status(self, expect_account: str | None = None) -> tuple[str, dict]:
        """
        查询当前在线状态。
        返回 (状态标识, 附加信息{账号/时间/IP})。

        expect_account 不为空时，会核验在线账号是否为该账号，
        避免「别人/别的号已在线」被误判成本账号登录成功。
        """
        code, text = self._open(self.cfg.status_url)
        if code == 403:
            # 极少见于带正常 UA 的请求；视为门户侧异常
            return LoginStatus.PROTOCOL_ERROR, {}

        info = self._parse_status_page(text)

        if self._looks_online(text):
            if expect_account and not self._account_matches(text, expect_account):
                # 在线的是另一个账号，对我们而言等同于未登录
                return LoginStatus.UNKNOWN_ERROR, info
            return LoginStatus.ALREADY_ONLINE, info

        # 未在线：若页面里有登录表单，说明门户正常只是需要登录
        if self._has_login_form(text):
            return LoginStatus.UNKNOWN_ERROR, info  # 交由调用方走登录流程

        # 页面不像状态页也不像登录页 → 可能跳到了别的页面
        return LoginStatus.PROTOCOL_ERROR, info

    def _looks_online(self, text: str) -> bool:
        """按配置关键词判断是否已在线（命中任一即可，规避个别关键词缺失）。"""
        return any(m in text for m in self.cfg.online_markers)

    def _has_login_form(self, text: str) -> bool:
        """判断页面是否含登录表单的账号输入框。"""
        return bool(re.search(
            r'(?is)<input[^>]*name=["\']?' + re.escape(self.cfg.alt_user_field) + r'["\']?',
            text)) or (self.cfg.alt_user_field in text and self.cfg.alt_pass_field in text)

    def _parse_status_page(self, text: str) -> dict:
        """从状态页抽出账号、登录时间、IP 等展示信息。"""
        info = {}
        for key, pattern in (
            ("account", r'id=["\']account["\'][^>]*value=["\']([^"\']*)'),
            ("ip",      r'id=["\']ipaddr["\'][^>]*value=["\']([^"\']*)'),
        ):
            m = re.search(pattern, text, re.I)
            if m:
                info[key] = m.group(1).strip()
        m = re.search(r'登录时间[：:]\s*([0-9:\-\s]+)', text)
        if m:
            info["login_time"] = m.group(1).strip()
        return info

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    def login(self, account: str, password: str) -> str:
        """
        提交登录。
        按优先级尝试：snnuportal login.jsp → 自助服务 zili/index.php。
        返回 LoginStatus 状态标识。
        """
        account = self.normalize_account(account)

        attempts = [
            ("snnuportal", self._try_snnuportal),
            ("zili", self._try_zili),
        ]
        last_status = LoginStatus.UNKNOWN_ERROR
        # 记录各端点的网络层失败情况：
        # 若主端点因「不可达/超时」失败，而备用端点给出密码错误，
        # 说明真正的问题是网络不通，应报不可达而非密码错误。
        primary_net_failed = False

        for label, func in attempts:
            try:
                # 传入目标账号，登录后需核验页面上的账号确实是它
                status = func(account, password)
            except TimeoutError:
                last_status = LoginStatus.TIMEOUT
                if label == "snnuportal":
                    primary_net_failed = True
                self._log(f"{label}: 超时")
                continue
            except ConnectionError as e:
                last_status = LoginStatus.UNREACHABLE
                if label == "snnuportal":
                    primary_net_failed = True
                self._log(f"{label}: 连接失败 {e}")
                continue
            except Exception as e:  # 兜底，避免整个程序崩掉
                last_status = LoginStatus.UNKNOWN_ERROR
                self._log(f"{label}: 异常 {type(e).__name__}: {e}")
                continue

            self._log(f"{label} => {status}")
            if LoginStatus.is_good(status):
                return status

            # 明确的「密码错/需验证码」直接返回，不必再试下一个端点
            if status in (LoginStatus.BAD_CREDENTIAL, LoginStatus.NEED_CAPTCHA,
                          LoginStatus.RATE_LIMITED):
                # 但若主端点不可用，密码错误就不可信——
                # 备用端点与主端点并非同一服务，此时应报网络/门户问题。
                if primary_net_failed and label != "snnuportal":
                    return LoginStatus.UNREACHABLE
                return status
            if status == LoginStatus.UNREACHABLE:
                return status   # 网络不通，换端点也没用
            # 主端点连 HTTP 层都不正常（连接被拒/404/非门户响应），
            # 同样标记为不可用，避免备用端点的密码错误误导用户
            if status == LoginStatus.PROTOCOL_ERROR and label == "snnuportal":
                primary_net_failed = True
            last_status = status

        return last_status

    def _try_snnuportal(self, account: str, password: str) -> str:
        """主路径：POST snnuportal/login.jsp，字段 account / password / yys。"""
        login_url = self.cfg.status_url.rsplit("/", 1)[0] + "/login.jsp"
        payload = {
            self.cfg.alt_user_field: account,
            self.cfg.alt_pass_field: password,
            self.cfg.alt_yys_field: self.cfg.carrier,
        }
        body = urllib.parse.urlencode(payload).encode("utf-8")
        code, text = self._open(login_url, data=body)

        if code in (301, 302, 303, 307):
            # 门户重定向通常代表登录成功（跳回状态页），但仍需核验账号
            return self._verify_after_login(account)
        if code >= 400:
            return LoginStatus.PROTOCOL_ERROR

        if self._looks_online(text) and self._account_matches(text, account):
            return LoginStatus.OK
        return self._classify_error(text)

    def _try_zili(self, account: str, password: str) -> str:
        """备用路径：POST /zili/index.php，字段 mode=login / login / passwd。"""
        payload = {
            self.cfg.login_mode_field: self.cfg.login_mode_value,
            self.cfg.login_user_field: account,
            self.cfg.login_pass_field: password,
        }
        body = urllib.parse.urlencode(payload).encode("utf-8")
        code, text = self._open(self.cfg.login_url, data=body)
        if code >= 400:
            return LoginStatus.PROTOCOL_ERROR

        if self._looks_online(text) and self._account_matches(text, account):
            return LoginStatus.OK

        # 出现「已登录/我的状态/自助服务」等字样也视为成功
        if re.search(r'(已登录|我的状态|当前登录|退出登录|欢迎)', text):
            return LoginStatus.OK
        return self._classify_error(text)

    def verify_credentials(self, account: str, password: str) -> str:
        """
        校验账号密码是否正确。

        ⚠️ 曾经的错误实现：用 /zili/index.php（校园宽带自助服务系统）校验。
        这是**另一套账号体系**，与 snnuportal 的上网账号密码往往不同，
        会导致用户输入正确密码也永远返回"密码错误"。现已废弃该方案。

        现在的正确做法：
        1. 若本机**已在线**且在线账号与目标一致 —— 说明这套凭据确实能上网
           （用户既然能在线，就证明密码有效），直接返回 OK，不打断连接。
        2. 若**未在线** —— 用主门户 snnuportal 的 login.jsp 真实校验。
           未登录时登录失败会回到登录页（含 password 输入框），
           成功则跳回状态页，据此可准确区分。

        返回 LoginStatus。
        """
        account = self.normalize_account(account)

        # 1) 已在线时不做破坏性校验
        try:
            online_status, page_info = self.check_status(expect_account=account)
            if online_status == LoginStatus.ALREADY_ONLINE:
                self._log("verify: 当前已在线，跳过密码校验")
                return LoginStatus.SKIPPED
        except (TimeoutError, ConnectionError):
            return LoginStatus.UNREACHABLE
        except Exception:
            pass

        # 2) 未在线：用主门户真实校验
        return self._verify_via_main_portal(account, password)

    def _verify_via_main_portal(self, account: str, password: str) -> str:
        """用主门户 snnuportal 校验密码（要求当前未在线）。"""
        login_url = self.cfg.status_url.rsplit("/", 1)[0] + "/login.jsp"
        payload = {
            self.cfg.alt_user_field: account,
            self.cfg.alt_pass_field: password,
            self.cfg.alt_yys_field: self.cfg.carrier,
        }
        body = urllib.parse.urlencode(payload).encode("utf-8")

        try:
            code, text = self._open(login_url, data=body)
        except TimeoutError:
            return LoginStatus.UNREACHABLE
        except ConnectionError:
            return LoginStatus.UNREACHABLE
        except Exception as e:
            self._log(f"verify: 异常 {type(e).__name__}: {e}")
            return LoginStatus.UNKNOWN_ERROR

        if code >= 400:
            return LoginStatus.UNREACHABLE

        # 出现登录表单（password 输入框）= 认证失败，页面退回登录页
        if self._has_login_form(text):
            return LoginStatus.BAD_CREDENTIAL

        # 出现验证码提示
        if "验证码" in text and self._looks_online(text) is False:
            for key, markers in self.cfg.error_markers.items():
                if key == "need_captcha" and any(m in text for m in markers):
                    return LoginStatus.NEED_CAPTCHA

        if self._looks_online(text) and self._account_matches(text, account):
            return LoginStatus.OK

        # 既没登录框也没在线信息：无法判定，按需验证码/未知处理
        if self._looks_online(text):
            return LoginStatus.OK
        return LoginStatus.BAD_CREDENTIAL

    def _account_matches(self, text: str, account: str) -> bool:
        """
        核验页面上的账号是否就是本次提交的目标账号。

        为什么必须做这一步：若本机本来已在线，任何登录请求（包括密码错误）
        之后的页面回查都会显示「已在线」，若只看在线标识就会把密码错误
        误判成登录成功。因此要求页面上出现的账号与目标账号一致。
        """
        info = self._parse_status_page(text)
        online_account = info.get("account")
        if online_account:
            return online_account.lower() == account.lower()
        # 页面没有账号字段（部分门户只在 JS 变量里带账号）
        m = re.search(r'(?:vloginid|loginid|userid)["\']?\s*[:=]\s*["\']?([^"\'&\s,]+)',
                      text, re.I)
        if m:
            return m.group(1).lower() == account.lower()
        # 完全没有账号信息时无法核验，保守地认为不匹配，交由上层提示
        return False

    def _verify_after_login(self, account: str) -> str:
        """登录提交后回查状态页确认，避免把重定向误判为成功。"""
        try:
            code, text = self._open(self.cfg.status_url)
        except Exception:
            # 回查失败但登录请求本身已被接受，乐观判定成功
            return LoginStatus.OK
        if code < 400 and self._looks_online(text) and self._account_matches(text, account):
            return LoginStatus.OK
        return LoginStatus.PROTOCOL_ERROR

    def _classify_error(self, text: str) -> str:
        """按错误关键词把页面文本映射成状态码。"""
        for key, markers in self.cfg.error_markers.items():
            for marker in markers:
                if marker in text:
                    return MARKER_TO_STATUS.get(key, LoginStatus.UNKNOWN_ERROR)
        # 页面同时含登录框 → 说明又回到登录页，即未登录成功
        if self._has_login_form(text):
            return LoginStatus.BAD_CREDENTIAL
        return LoginStatus.UNKNOWN_ERROR

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------
    def normalize_account(self, account: str) -> str:
        """
        按配置补齐运营商后缀。
        配置 account_include_carrier=False 时，裸学号会自动拼成 学号@运营商。
        """
        account = (account or "").strip()
        if not account:
            return account
        if "@" in account:
            return account
        if not self.cfg.account_include_carrier and self.cfg.carrier:
            return f"{account}@{self.cfg.carrier}"
        return account

    def logout(self) -> bool:
        """尝试下线（用于「重新登录」场景）。"""
        try:
            base = self.cfg.status_url.rsplit("/", 1)[0]
            code, _ = self._open(base + "/logoff")
            return code < 400
        except Exception:
            return False

    def _log(self, msg: str) -> None:
        from config import log_file
        try:
            os.makedirs(os.path.dirname(log_file()), exist_ok=True)
            with open(log_file(), "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception:
            pass


import os  # 供 _log 使用（放在末尾避免循环导入时的顺序问题）