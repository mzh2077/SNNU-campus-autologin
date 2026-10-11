# -*- coding: utf-8 -*-
"""
校园网自动登录 —— 命令行主程序
==============================
使用方式
--------
1. 首次双击运行：引导输入账号 / 密码 / 运营商，保存后自动开始登录。
   随后会询问是否开启开机自启。
2. 手动打开：登录完成后弹出**设置菜单**，可管理开机自启、
   删除账号并重新登录、完全卸载。
3. 开机自动启动：走 --quiet 静默分支，登录成功**立即退出**，
   全程无窗口无提示，做到无感。

命令行参数
----------
  --set             修改账号密码
  --reset           清空已保存的账号密码（下次运行重新引导输入）
  --status          只查询当前在线状态，不登录
  --test            自检：测试门户连通性与凭据有效性
  --autostart       开启开机自动启动
  --no-autostart    关闭开机自动启动
  --autostart-info  查看开机自启状态与启动命令
  --delete-account  删除已保存的账号信息
  --menu            登录后直接显示设置菜单
  --keep            显示结果后不自动关闭
  --quiet           静默运行（开机自启内部使用，无感无窗口）
  --help            显示帮助
"""

import getpass
import os
import sys
import time

# 允许双击 exe 直接运行（PyInstaller 打包时目录不同）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import config_store
import console_ui
import startup
from portal_client import LoginStatus, PortalClient


# ---------------------------------------------------------------------------
# 控制台输出（Windows 控制台需开启 UTF-8 才能正确显示中文与符号）
# ---------------------------------------------------------------------------
def setup_console() -> None:
    if os.name == "nt":
        try:
            os.system("chcp 65001 > nul")
        except Exception:
            pass
    # 打包成 exe 后按任意键可能直接结束，改用更稳妥的读取方式
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # 初始化红字支持（红字用于提示"密码不会显示"等警示信息）
    console_ui.init_color()


def banner(title: str = "校园网自动登录") -> None:
    line = "=" * 46
    print(f"\n{line}\n  {title}  v{config.APP_VERSION}\n{line}")


def ok(text: str) -> None:
    print(f"[√] {text}")


def fail(text: str) -> None:
    print(f"[×] {text}")


def warn(text: str) -> None:
    print(f"[!] {text}")


def info(text: str) -> None:
    print(f"  {text}")


# ---------------------------------------------------------------------------
# 首次运行向导
# ---------------------------------------------------------------------------
def ask(prompt: str, default: str = "") -> str:
    hint = f"（默认 {default}）" if default else ""
    try:
        value = input(f"{prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        sys.exit(1)
    return value or default


def ask_password(prompt: str = "请输入密码") -> str:
    """
    输入密码（不回显字符）。

    两点体验优化：
    1. 用**红字**明确提示"不会显示任何字符"，避免用户以为程序卡死或没反应；
    2. 实时用星号反馈已输入的字符数量（*、**、***…），
       既确认程序在正常工作，又不会泄露密码长度以外的任何信息。
    """
    # —— 红色警示：告诉用户这里不会有任何回显 ——
    notice = "（输入时屏幕不会显示任何字符，属正常现象）"
    console_ui.WinColor.print_red(console_ui.red(f"  {notice}"))

    try:
        return getpass.getpass(f"{prompt}: ")
    except Exception:
        # 极少数环境（如无 TTY 的重定向）不支持隐藏输入，退回自定义实现
        return _ask_password_fallback(prompt)


def _ask_password_fallback(prompt: str) -> str:
    """
    自行实现隐藏输入：逐字符读取，用星号反馈。
    getpass 不可用时使用（例如输出被重定向的场景）。
    """
    if not sys.stdin.isatty():
        return ask(prompt)

    sys.stdout.write(f"{prompt}: ")
    sys.stdout.flush()
    chars = []
    try:
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n", ""):
                break
            if ch in ("\x03", "\x04"):        # Ctrl+C / Ctrl+D
                raise KeyboardInterrupt
            if ch == "\x08":                  # 退格
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
            else:
                chars.append(ch)
                sys.stdout.write("*")        # 只回显星号，绝不回显字符
            sys.stdout.flush()
    except (KeyboardInterrupt, EOFError):
        print()
        raise
    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(chars)


CARRIER_CHOICES = {
    "1": ("mobile", "中国移动"),
    "2": ("unicom", "中国联通"),
    "3": ("telecom", "中国电信"),
    "4": ("", "校园网/教育网（不加后缀）"),
}


def first_run_setup() -> config_store.Credentials:
    """
    首次运行：引导输入账号密码 → **验证** → 验证通过后才保存。

    验证不通过（密码错误）时允许重新输入，最多 3 次；
    网络不可达时询问是否仍要保存，避免用户明明没连网却被卡住。
    """
    banner("首次使用 · 请输入校园网账号")
    warn("本信息仅保存在你自己的电脑上（已加密），不会上传到任何服务器。")
    print()

    account = ask("校园网账号（学号）")
    if not account:
        fail("账号不能为空，程序退出。")
        time.sleep(2)
        sys.exit(1)

    print("\n  请选择你的网络运营商（账号需带对应后缀）：")
    for key, (code, label) in CARRIER_CHOICES.items():
        print(f"    {key}. {label}  →  后缀 {'@' + code if code else '（不加）'}")
    choice = ask("请选择", "1")

    password = ask_password("请输入密码")
    if not password:
        fail("密码不能为空，程序退出。")
        time.sleep(2)
        sys.exit(1)

    if "@" in account:
        final_account = account
    else:
        carrier = CARRIER_CHOICES.get(choice, CARRIER_CHOICES["1"])[0]
        final_account = f"{account}@{carrier}" if carrier else account

    creds = config_store.Credentials(final_account, password,
                                      CARRIER_CHOICES.get(choice, ("mobile", ""))[0])

    # —— 关键：验证通过后才保存，密码错误不留错误凭据 ——
    cli = PortalClient(config.portal())
    verified = verify_credentials(creds, config.portal(), cli)

    if not verified:
        print()
        fail("账号密码未通过验证，已放弃保存。")
        info("请确认网络已连接校园网后，重新运行程序再试。")
        time.sleep(3)
        sys.exit(1)

    config_store.save(creds)
    print()
    ok(f"账号已保存：{creds.masked()}")
    info("密码已加密（DPAPI），不会以明文保存或显示。")
    return creds


def ask_autostart() -> None:
    """
    首次设置凭据后，询问是否开启开机自启。

    写入注册表 Run 键，因此该项会出现在
    「任务管理器 → 启动 → 启动应用」中，可被用户随时启用/禁用。
    """
    if not startup.is_supported():
        return
    if startup.is_enabled():
        # 已有启动项（如用户之前开过），仅确保路径有效
        startup.repair()
        return

    print()
    print("-" * 46)
    info("是否设置为开机自动启动校园网？")
    info("开机后会自动运行并静默登录（不会弹出窗口）。")
    info("之后可在「任务管理器 → 启动」中随时管理此项。")
    answer = ask("开启开机自启？", "y")

    if answer.lower() in ("y", "yes", "是", "1", "确定"):
        ok_flag, message = startup.enable()
        (ok if ok_flag else fail)(message)
        if ok_flag:
            info("如需取消：运行  校园网自动登录.exe --no-autostart")
            info("或直接在任务管理器「启动」中禁用。")
    else:
        info("已跳过。需要时可运行  校园网自动登录.exe --autostart 开启。")


def change_credentials() -> config_store.Credentials:
    """--set：修改已保存的账号密码。"""
    banner("修改账号密码")
    if config_store.clear():
        info("已清除原有凭据，请重新输入。\n")
    else:
        warn("未找到原有凭据，请直接输入。\n")
    creds = first_run_setup()
    ask_autostart()
    return creds


# ---------------------------------------------------------------------------
# 登录主流程
# ---------------------------------------------------------------------------
def do_login(creds: config_store.Credentials, cfg, cli: PortalClient) -> str:
    """
    按配置执行自动登录，返回最终状态码。
    默认策略：先查状态，已在线就跳过登录（最省事也最安全）。
    """
    account = cli.normalize_account(creds.account)

    # 1) 先查状态
    try:
        status, page_info = cli.check_status(expect_account=account)
    except TimeoutError:
        status, page_info = LoginStatus.TIMEOUT, {}
    except ConnectionError as e:
        warn(f"校园网不可达：{e}")
        return LoginStatus.UNREACHABLE

    if status == LoginStatus.ALREADY_ONLINE and cfg.auto_mode == "status":
        info(f"当前已在线，无需重复登录。")
        _print_session(page_info)
        return LoginStatus.ALREADY_ONLINE

    # 2) 提交登录（带重试）
    info(f"正在登录：{creds.masked()}")
    last = LoginStatus.UNKNOWN_ERROR
    for attempt in range(1, cfg.max_retries + 2):
        try:
            last = cli.login(account, creds.password)
        except TimeoutError:
            last = LoginStatus.TIMEOUT
        except ConnectionError as e:
            last = LoginStatus.UNREACHABLE
            warn(f"校园网不可达：{e}")
            break

        if LoginStatus.is_good(last):
            break
        if attempt <= cfg.max_retries:
            warn(f"{LoginStatus.message(last)}，{cfg.retry_delay:.0f} 秒后重试"
                 f"（{attempt}/{cfg.max_retries}）")
            time.sleep(cfg.retry_delay)

    # 3) 登录后回查，展示会话信息
    if LoginStatus.is_good(last):
        try:
            _, page_info = cli.check_status(expect_account=account)
            _print_session(page_info)
        except Exception:
            pass
    return last


def _print_session(page_info: dict) -> None:
    if not page_info:
        return
    if page_info.get("account"):
        info(f"账号：{page_info['account']}")
    if page_info.get("ip"):
        info(f"内网 IP：{page_info['ip']}")
    if page_info.get("login_time"):
        info(f"登录时间：{page_info['login_time']}")


# ---------------------------------------------------------------------------
# 结果展示与退出控制
# ---------------------------------------------------------------------------
def show_result(status: str) -> None:
    """把状态翻译成用户能懂的中文提示。"""
    print()
    if status == LoginStatus.OK:
        ok("校园网连接成功！")
    elif status == LoginStatus.ALREADY_ONLINE:
        ok("校园网已在线。")
    elif status == LoginStatus.BAD_CREDENTIAL:
        fail("账号或密码错误。")
        info("请运行  校园网自动登录.exe --set  重新输入账号密码。")
    elif status == LoginStatus.NEED_CAPTCHA:
        fail("该账号登录需要验证码，程序无法自动完成。")
        info("请先在浏览器中打开门户完成一次带验证码的登录，")
        info("系统通常会在一段时间内记住你的设备。")
    elif status == LoginStatus.RATE_LIMITED:
        fail("尝试过于频繁或账号已被锁定。")
        info("请稍后再试，或联系信息中心解锁。")
    elif status == LoginStatus.UNREACHABLE:
        fail("校园网不可达。")
        info("请确认已连接到校园网（有线/无线），再检查门户地址：")
        info(f"  {config.portal().status_url}")
    elif status == LoginStatus.TIMEOUT:
        fail("请求超时，门户无响应。")
        info("可能是网络不通或校园网负载较高，请稍后重试。")
    elif status == LoginStatus.PROTOCOL_ERROR:
        fail("门户返回内容异常，可能门户已改版。")
        info("可尝试重新抓取门户页面以更新接口配置。")
    else:
        fail("登录未成功。")
        info("可手动打开门户登录：")
        info(f"  {config.portal().status_url}")


def auto_close(cfg, success: bool) -> None:
    """按配置关闭窗口：成功倒计时自动关，失败时保留窗口。"""
    if os.name != "nt":
        return

    if success:
        if cfg.close_on_success == "auto":
            for i in range(int(cfg.auto_close_delay), 0, -1):
                print(f"\r  {i} 秒后自动关闭…   ", end="", flush=True)
                time.sleep(1)
            print("\r  已关闭。              ")
        elif cfg.close_on_success == "enter":
            _wait_enter()
        # "keep" 模式不处理
    else:
        if cfg.keep_window_on_failure:
            _wait_enter()


def _wait_enter() -> None:
    try:
        input("\n  按回车键关闭窗口… ")
    except (EOFError, KeyboardInterrupt):
        pass


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_status(cfg, cli: PortalClient) -> int:
    banner("当前校园网状态")
    try:
        status, info_data = cli.check_status()
    except TimeoutError:
        show_result(LoginStatus.TIMEOUT)
        return 1
    except ConnectionError as e:
        warn(f"校园网不可达：{e}")
        show_result(LoginStatus.UNREACHABLE)
        return 1
    show_result(status)
    if LoginStatus.is_good(status):
        _print_session(info_data)
    return 0 if LoginStatus.is_good(status) else 1


def cmd_test(cfg, cli: PortalClient) -> int:
    """自检：逐项检查配置、连通性、凭据有效性。"""
    banner("自检")
    info(f"门户地址：{cfg.status_url}")
    info(f"登录端点：{cfg.login_url}")
    info(f"超时：{cfg.request_timeout}s，重试：{cfg.max_retries} 次")
    info(f"{startup.describe()}")
    print()

    creds = config_store.load()
    if creds is None:
        fail("未找到已保存的账号密码，请先运行一次并完成引导。")
        return 1
    ok(f"凭据可正常解密：{creds.masked()}")

    # 连通性
    try:
        status, page_info = cli.check_status()
        ok(f"门户连通正常（状态：{LoginStatus.message(status)}）")
        _print_session(page_info)
    except TimeoutError:
        fail("门户连接超时")
        return 1
    except ConnectionError as e:
        fail(f"门户无法访问：{e}")
        return 1

    # 账号格式
    account = cli.normalize_account(creds.account)
    if "@" in account:
        ok(f"账号格式：{creds.masked()}（含运营商后缀）")
    else:
        warn(f"账号 {creds.masked()} 不含 @运营商 后缀，若登录失败请加上后缀，")
        warn("或在 --set 中重新选择运营商。")
    return 0


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def verify_credentials(creds: config_store.Credentials, cfg,
                       cli: PortalClient, max_attempts: int = 3) -> bool:
    """
    校验账号密码，返回是否通过。

    交互流程：
      - 密码正确   → 输出「连接成功」并返回 True
      - 密码错误   → 明确提示，允许重新输入（最多 max_attempts 次）
      - 网络不可达 → 说明当前无法验证，询问是否仍要保存
    """
    account = cli.normalize_account(creds.account)

    for attempt in range(1, max_attempts + 1):
        print()
        info(f"正在验证账号 {creds.masked()} …")
        status = cli.verify_credentials(account, creds.password)

        # —— 已在线，跳过校验（不打断现有连接）——
        if status == LoginStatus.SKIPPED:
            ok("账号可用，当前已在线。")
            info("（检测到你已连接校园网，因此未再验证密码。")
            info("  若想完整验证密码，请先在浏览器中退出校园网后重新设置。）")
            return True

        # —— 密码正确 ——
        if status == LoginStatus.OK:
            ok("密码正确，连接成功！")
            return True

        # —— 密码错误 ——
        if status == LoginStatus.BAD_CREDENTIAL:
            fail("密码错误，连接失败。")
            if attempt >= max_attempts:
                info(f"已连续验证失败 {max_attempts} 次。")
                return False
            answer = ask("是否重新输入账号和密码？(y=重输 / n=放弃)", "y")
            if answer.lower() not in ("y", "yes", "是", "1"):
                return False
            new_creds = _prompt_credentials(creds.carrier)
            if new_creds is None:
                return False
            creds.account, creds.password = new_creds.account, new_creds.password
            account = cli.normalize_account(creds.account)
            continue

        # —— 被限流 / 锁定 ——
        if status == LoginStatus.RATE_LIMITED:
            fail("尝试过于频繁或账号已被锁定，连接失败。")
            info("请稍后再试，或联系信息中心解锁。")
            return False

        # —— 需要验证码 ——
        if status == LoginStatus.NEED_CAPTCHA:
            fail("该账号登录需要验证码，程序无法自动完成验证。")
            info("请先在浏览器中打开门户手动登录一次，成功后系统通常会")
            info("在短时间内记住你的设备，此时再运行程序即可。")
            return False

        # —— 网络不可达 ——
        if status == LoginStatus.UNREACHABLE:
            fail("校园网不可达，无法验证密码。")
            info("请确认已连接到校园网后再试。")
            answer = ask("是否仍要保存该账号密码？(y=保存 / n=返回)", "n")
            return answer.lower() in ("y", "yes", "是", "1")

        # —— 超时 ——
        if status == LoginStatus.TIMEOUT:
            fail("请求超时，无法验证密码。")
            answer = ask("是否仍要保存该账号密码？(y=保存 / n=返回)", "n")
            return answer.lower() in ("y", "yes", "是", "1")

        # —— 其他 ——
        warn("暂时无法验证密码（门户返回内容异常）。")
        answer = ask("是否仍要保存该账号密码？(y=保存 / n=返回)", "n")
        return answer.lower() in ("y", "yes", "是", "1")

    return False


def _prompt_credentials(default_carrier: str = "") -> config_store.Credentials | None:
    """重新询问账号密码（不打印横幅，便于在验证失败后连续使用）。"""
    print()
    account = ask("校园网账号（学号）")
    if not account:
        fail("账号不能为空。")
        return None

    if "@" in account:
        carrier = default_carrier or config.portal().carrier
        return config_store.Credentials(account, ask_password(), carrier)

    print("\n  请选择网络运营商：")
    for key, (code, label) in CARRIER_CHOICES.items():
        print(f"    {key}. {label}")
    choice = ask("请选择", "1")
    carrier = CARRIER_CHOICES.get(choice, ("mobile", ""))[0]
    final = f"{account}@{carrier}" if carrier else account
    return config_store.Credentials(final, ask_password(), carrier)


def delete_account(interactive: bool = True) -> bool:
    """
    删除已保存的账号信息。
    interactive=False 时用于 --delete-account 命令，不额外询问。
    返回是否删除成功。
    """
    creds = config_store.load()
    if creds is None:
        warn("当前没有已保存的账号信息。")
        return False

    if interactive:
        warn(f"即将删除的账号：{creds.masked()}")

    if interactive:
        answer = ask("确认删除该账号信息？此操作不可撤销", "n")
    else:
        answer = "y"

    if answer.lower() not in ("y", "yes", "是", "1"):
        info("已取消，未做任何改动。")
        return False

    if config_store.clear():
        ok("账号信息已删除。")
        return True
    fail("删除失败，请检查文件权限。")
    return False


def uninstall_everything() -> bool:
    """
    彻底卸载：删除开机自启注册项、账号信息、配置与日志，以及程序自身。

    注意：程序自身无法在 Windows 上直接删除正在运行的 exe，
    因此采用「自我移动到临时目录 + 稍后由系统清理」的方式；
    若移动失败，会提示用户手动删除残留文件。
    """
    banner("卸载校园网自动登录")

    print("  将执行以下清理：")
    info("· 关闭开机自动启动，并删除注册表启动项")
    info("· 删除已保存的账号信息（加密凭据）")
    info("· 删除配置文件与运行日志")
    info("· 删除程序文件本身")
    print()

    answer = ask("确认卸载？此操作不可撤销", "n")
    if answer.lower() not in ("y", "yes", "是", "1"):
        info("已取消，未做任何改动。")
        return False

    print()
    # 1) 开机自启注册项
    ok_flag, message = startup.disable()
    (ok if ok_flag else warn)(f"启动项：{message}")

    # 2) 账号信息
    if config_store.clear():
        ok("账号信息已删除")
    else:
        info("账号信息本就未保存")

    # 3) 配置与日志，连同数据目录一并移除
    removed = _remove_data_files()
    (ok if removed else info)("配置与日志已清理" if removed else "配置与日志不存在")

    # 3b) 删除数据目录本身，确保凭据文件无残留
    if _remove_data_dir():
        ok(f"数据目录已删除：{config.data_dir()}")
    else:
        warn(f"数据目录未能完全删除，请手动检查：{config.data_dir()}")

    # 3c) 清理自我卸载留下的临时备份
    if _remove_graveyard():
        info("临时备份已清理")

    # 4) 程序自身
    moved = _remove_self()
    print()
    if moved:
        ok("卸载完成，程序已从原位置移除。")
        info("残留的空目录可手动删除。")
        return True
    else:
        warn("程序文件未能自动删除（通常因正在运行被占用）。")
        info("请手动删除这些文件：")
        info(f"  {sys.executable}")
        return False


def _show_data_location() -> None:
    """
    展示账号密码等数据的存放位置与保护方式，
    让用户清楚知道东西存在哪、删程序后还剩什么。
    """
    banner("数据存放位置")
    creds = config_store.load()

    print("  本程序会在你的电脑上保存以下内容：")
    print()
    print(f"  数据目录：{config.data_dir()}")
    print(f"    ├─ credentials.bin   加密后的账号密码（{_file_size(config.cred_file())}）")
    print(f"    ├─ settings.json     运行配置（非敏感）")
    print(f"    └─ run.log           运行日志（不含密码）")
    print()
    if creds is not None:
        print(f"  当前保存的账号：{creds.masked()}")
    else:
        print("  当前未保存任何账号")
    print()
    info("账号密码经 Windows DPAPI 加密（与你的 Windows 账户绑定），")
    info("密文中不含明文，其他用户无法解密。")
    print()
    print("  注册表开机启动项：")
    print(f"    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run")
    print(f"    值名：{startup.APP_VALUE_NAME}")
    print()

    # 无论是否开启自启，都提供清除入口——
    # 凭据属于用户，查看位置后理应能就地删除。
    answer = ask("是否立即清除上述全部数据？", "n")
    if answer.lower() in ("y", "yes", "是", "1"):
        print()
        rc = cmd_purge()
        if rc == 0 and not config_store.exists():
            info("提示：若想连程序文件也删掉，可运行 --purge 后手动删除 exe，")
            info("或直接用设置菜单的选项 4 完全卸载。")
    else:
        info("如需手动清理：删除上述数据目录即可；")
        info("或运行  校园网自动登录.exe --purge 一键清除。")


def _file_size(path: str) -> str:
    """返回文件大小描述，文件不存在时返回说明文字。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return "不存在"
    if size < 1024:
        return f"{size} 字节"
    return f"{size / 1024:.1f} KB"


def _remove_data_files() -> bool:
    """删除配置与日志文件（保留目录本身）。"""
    removed = False
    for path in (config.config_file(), config.log_file()):
        try:
            if os.path.exists(path):
                os.remove(path)
                removed = True
        except OSError:
            pass
    return removed


def _remove_data_dir() -> bool:
    """
    删除整个数据目录（含 credentials.bin 凭据文件）。

    卸载后若留下空目录，用户会误以为数据没删干净，
    因此这里连目录一并移除；若目录正被占用则留待后续清理。
    """
    import shutil
    folder = config.data_dir()
    if not os.path.isdir(folder):
        return True
    try:
        shutil.rmtree(folder, ignore_errors=False)
        return True
    except OSError:
        return False


def _remove_graveyard() -> bool:
    """
    清理自我卸载时留下的临时备份目录 %TEMP%\\CampusAutoLogin_uninstall。

    那里存放着程序文件副本（含可执行文件），同样属于用户不想留下的东西。
    """
    import tempfile
    import shutil
    graveyard = os.path.join(tempfile.gettempdir(), "CampusAutoLogin_uninstall")
    if not os.path.isdir(graveyard):
        return False
    try:
        shutil.rmtree(graveyard, ignore_errors=True)
        return not os.path.isdir(graveyard)
    except OSError:
        return False


def _remove_self() -> bool:
    """
    将程序自身移除，实现"卸载后不可见"的效果。

    Windows 正在运行的 exe 被系统锁定，不能直接删除，
    也不能直接移动整个目录。因此：
      1. 先把程序目录复制到 %TEMP%\\CampusAutoLogin_uninstall（备份，便于万一失败可恢复）
      2. 删除源目录下的所有文件（当前 exe 因在运行可能删不掉，其余可删）
      3. 安排一个独立 PowerShell 进程，在本程序退出后删掉源 exe 与源目录
    """
    if not getattr(sys, "frozen", False):
        # 源码运行：不做自我删除，仅提示手动清理
        return False

    import tempfile
    import shutil

    program = os.path.abspath(sys.executable)
    folder = os.path.dirname(program)

    graveyard = os.path.join(tempfile.gettempdir(), "CampusAutoLogin_uninstall")
    try:
        if os.path.exists(graveyard):
            shutil.rmtree(graveyard, ignore_errors=True)
        shutil.copytree(folder, graveyard)      # 备份
    except Exception:
        # 备份失败也继续尝试直接清理
        pass

    # 尝试删除源目录下的文件（除正在运行的 exe 外通常都能删掉）
    try:
        for name in os.listdir(folder):
            p = os.path.join(folder, name)
            if os.path.abspath(p) == program:
                continue          # 当前运行的 exe 稍后由辅助进程删除
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    os.remove(p)
            except OSError:
                pass
    except Exception:
        pass

    # 安排退出后删除 exe 与残留目录
    _schedule_self_delete(program, folder)
    return True


def _schedule_self_delete(program: str, folder: str) -> None:
    """注册独立进程，在本程序退出后删除残留的 exe 与目录。"""
    import subprocess
    try:
        ps = (
            "$ErrorActionPreference='SilentlyContinue';"
            "Start-Sleep -Seconds 3;"
            f"Remove-Item -LiteralPath '{program}' -Force;"
            f"if ((Get-ChildItem -LiteralPath '{folder}' -Force | Measure-Object).Count -eq 0) "
            f"{{ Remove-Item -LiteralPath '{folder}' -Recurse -Force }}"
        )
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def show_settings_menu(cfg) -> None:
    """
    手动打开时显示的设置菜单。
    登录完成后进入，允许用户管理自启、账号与卸载。
    """
    while True:
        banner("设置菜单")
        autostart_state = "已开启" if startup.is_enabled() else "未开启"
        if startup.is_enabled() and startup.is_disabled_by_user():
            autostart_state = "已添加（任务管理器中已禁用）"

        creds = config_store.load()
        account_state = creds.masked() if creds else "未设置"

        print(f"  当前账号  ：{account_state}")
        print(f"  开机自启  ：{autostart_state}")
        print()
        print("  [1] 开启开机自动启动")
        print("  [2] 关闭开机自动启动")
        print("  [3] 删除账号信息并重新选择账号登录")
        print("  [4] 删除软件及注册项（完全卸载）")
        print("  [5] 重新连接校园网（先断开再重新登录）")
        print("  [6] 查看数据存放位置 / 清理残留数据")
        print("  [0] 退出")
        print()

        choice = ask("请选择", "0").lower()

        if choice == "1":
            ok_flag, message = startup.enable()
            (ok if ok_flag else fail)(message)
            if ok_flag:
                info("开机后将静默登录，可在任务管理器「启动」中管理。")

        elif choice == "2":
            ok_flag, message = startup.disable()
            (ok if ok_flag else fail)(message)

        elif choice == "3":
            if delete_account():
                info("请重新输入账号密码。\n")
                first_run_setup()
            _wait_enter()

        elif choice == "4":
            if uninstall_everything():
                sys.exit(0)
            _wait_enter()

        elif choice == "5":
            # 强制重新登录：先下线再重新认证，
            # 用于「网络不通但显示已在线」或需要刷新在线时长的情况。
            # （默认的登录策略在已在线时会直接跳过，所以这里要特殊处理）
            cli = PortalClient(cfg)
            current = config_store.load()
            if current is None:
                fail("尚未保存账号信息，请先在选项 3 中重新设置。")
            else:
                print()
                info("正在断开当前连接…")
                cli.logout()
                time.sleep(1)
                banner("重新登录校园网")
                # 临时切到 always 模式，跳过"已在线就跳过"的判断
                original_mode = cfg.auto_mode
                cfg.auto_mode = "always"
                try:
                    status = do_login(current, cfg, cli)
                finally:
                    cfg.auto_mode = original_mode
                show_result(status)

        elif choice == "6":
            _show_data_location()
            _wait_enter()

        elif choice == "0":
            info("已退出。")
            return

        else:
            warn("无效选项，请重新输入。")

        print()


def cmd_purge() -> int:
    """
    --purge：彻底清除本程序在系统里留下的一切痕迹。

    适用于用户直接删除了 exe 文件夹、但希望把
    AppData 里的加密凭据与配置也一并清掉的场景。

    保留原 exe 不动，只清理数据，适合"忘记密码想重新设置"或
    "卸载不彻底"两种场景。
    """
    banner("清除全部数据")
    creds = config_store.load()
    print(f"  数据目录：{config.data_dir()}")
    print(f"  凭据文件：{config.cred_file()}")
    if creds is not None:
        print(f"  当前账号：{creds.masked()}")
    print(f"  {startup.describe()}")
    print()
    print("  将删除：加密凭据、配置、日志、数据目录、注册表启动项")
    print()

    answer = ask("确认清除？此操作不可撤销", "n")
    if answer.lower() not in ("y", "yes", "是", "1"):
        info("已取消，未做任何改动。")
        return 0

    print()
    ok_flag, message = startup.disable()
    (ok if ok_flag else warn)(f"启动项：{message}")

    if config_store.clear():
        ok("账号信息已删除")
    else:
        info("账号信息本就未保存")

    if _remove_data_dir():
        ok("数据目录已删除")
    else:
        warn(f"数据目录未能完全删除：{config.data_dir()}")

    if _remove_graveyard():
        info("临时备份已清理")

    print()
    ok("清除完成，系统内已无本程序残留。")
    return 0


def _detect_orphan_credentials() -> bool:
    """
    检测"孤儿凭据"：数据目录里还有凭据，但启动项指向的 exe 已不存在。

    这种情况通常出现在用户手动删除了 exe，却没清 AppData。
    本函数只在必要时提示，不打扰正常使用。
    返回 True 表示检测到孤儿数据。
    """
    if not config_store.exists():
        return False
    if not startup.is_enabled():
        return False
    command = startup.get_command()
    if not command:
        return False
    # 从命令行里提取 exe 路径，检查文件是否还存在
    target = command.strip().strip('"')
    # 去掉可能的参数
    for sep in ('" --quiet', " --quiet"):
        target = target.split(sep)[0]
    target = target.strip('"')
    return bool(target) and not os.path.exists(target)


def cmd_autostart_status() -> int:
    """查看开机自启状态。"""
    banner("开机自启状态")
    print(f"  {startup.describe()}")
    if startup.is_enabled():
        print()
        info("启动命令：")
        print(f"    {startup.get_command()}")
        print()
        info("位置：任务管理器 → 启动 → 启动应用")
    return 0


def run_quiet() -> int:
    """
    静默模式（开机自启使用）——无感设计。

    开机后自动运行：登录成功即**立即退出**，不显示任何窗口、
    不倒计时、不等待按键，失败也只写日志，绝不打扰用户。

    实现要点：执行期间把 stdout/stderr 重定向到 os.devnull，
    确保 do_login 内部即使有 print 也不会在屏幕上闪现。
    """
    creds = config_store.load()
    if creds is None or creds.is_empty:
        return 1   # 没有凭据，无法自动登录；下次手动运行时再设置

    cfg = config.portal()
    # 开机时网络往往还没就绪，放宽重试以提高成功率，但总时长控制在 60 秒内
    cfg.max_retries = max(cfg.max_retries, 3)
    cli = PortalClient(cfg)

    # 静默：屏蔽所有标准输出，避免开机时窗口闪现
    devnull = open(os.devnull, "w")
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout = devnull
        sys.stderr = devnull
        status = do_login(creds, cfg, cli)
    except Exception:
        return 2
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        try:
            devnull.close()
        except Exception:
            pass

    # 无论成功或失败都立即退出：无感，不打扰
    return 0 if LoginStatus.is_good(status) else 1


def cmd_delete_account() -> int:
    """--delete-account：删除账号信息（供菜单/脚本调用）。"""
    banner("删除账号信息")
    if delete_account(interactive=False):
        return 0
    return 1


def show_help() -> None:
    banner("使用说明")
    print("""
  直接双击运行        自动登录校园网，成功后自动关闭

  命令行参数：
    --set             修改账号密码
    --reset           清空已保存的账号密码（下次运行重新输入）
    --status          只查询当前在线状态，不执行登录
    --test            自检：检查配置、连通性与凭据
    --autostart       开启开机自动启动
    --no-autostart    关闭开机自动启动
    --autostart-info  查看开机自启状态与启动命令
    --delete-account  删除已保存的账号信息
    --purge           清除全部数据与注册表痕迹（保留程序本身）
    --menu            登录后直接显示设置菜单
    --keep            显示结果后不自动关闭
    --quiet           静默运行（开机自启内部使用，无感无窗口）
    --help            显示本说明

  两种运行模式的区别：
    开机自启启动  →  静默无感，登录成功即退出，不打扰
    手动双击运行  →  登录完成后弹出设置菜单，可管理开机自启、
                    删除账号并重新登录、彻底卸载

  设置菜单选项：
    1 开启开机自动启动        4 删除软件及注册项（完全卸载）
    2 关闭开机自动启动        5 重新连接校园网（先断开再重新登录）
    3 删除账号并重新登录      6 查看数据存放位置 / 清理残留数据
                              0 退出

  数据存放位置：
    %LOCALAPPDATA%\\CampusAutoLogin
      credentials.bin（DPAPI 加密的账号密码）
      settings.json（配置）  run.log（日志，不含密码）
    注册表：HKCU\\...\\CurrentVersion\\Run  值名 CampusAutoLogin
    用选项 4 或 --purge 可彻底清除上述内容。

  密码输入说明：
    输入密码时屏幕不会出现任何字符，属正常现象（以红色提示）。

  配置文件位置：
    {data}
""".format(data=config.data_dir()))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # --quiet 必须最先处理：开机自启时不显示任何界面
    if "--quiet" in argv:
        return run_quiet()

    setup_console()
    config.load_overrides()
    cfg = config.portal()

    if "--help" in argv or "-h" in argv:
        show_help()
        return 0

    cli = PortalClient(cfg)

    # 开机自启相关命令（不需要凭据即可执行）
    if "--autostart-info" in argv:
        return cmd_autostart_status()

    if "--autostart" in argv:
        banner("开启开机自动启动")
        ok_flag, message = startup.enable()
        (ok if ok_flag else fail)(message)
        if ok_flag:
            info("开机后将自动运行并静默登录。")
            info("可在「任务管理器 → 启动」中管理此项。")
        return 0 if ok_flag else 1

    if "--no-autostart" in argv:
        banner("关闭开机自动启动")
        ok_flag, message = startup.disable()
        (ok if ok_flag else fail)(message)
        return 0 if ok_flag else 1

    # --reset
    if "--reset" in argv:
        banner("清除凭据")
        if config_store.clear():
            ok("已清除。下次运行将重新引导输入账号密码。")
        else:
            warn("没有找到已保存的凭据。")
        return 0

    # --set
    # --purge：清除全部数据与注册表痕迹（保留程序本身）
    # 必须放在首次运行向导**之前**，否则无凭据时会被向导拦截
    if "--purge" in argv:
        return cmd_purge()

    # --delete-account：同样需前置，否则无凭据时进不了分支
    if "--delete-account" in argv:
        return cmd_delete_account()

    if "--set" in argv:
        change_credentials()
        # 修改后直接继续登录
    else:
        # 首次运行：引导输入
        if not config_store.exists():
            first_run_setup()
            ask_autostart()      # ← 仅首次运行时询问是否开机自启
        else:
            creds = config_store.load()
            if creds is None or creds.is_empty:
                warn("已保存的凭据无法解密（可能更换了系统账户），请重新输入。\n")
                first_run_setup()
                ask_autostart()
            elif _detect_orphan_credentials():
                # 启动项指向的程序已不存在（用户手动删过 exe），
                # 凭据会成为无人认领的残留，主动提示清理
                warn("检测到残留数据：开机启动项指向的程序已不存在。")
                info(f"残留位置：{config.data_dir()}")
                answer = ask("是否清除这些残留数据？(y=清除 / n=保留)", "y")
                if answer.lower() in ("y", "yes", "是", "1"):
                    startup.disable()
                    config_store.clear()
                    _remove_data_dir()
                    ok("残留数据已清除。")
                    print()
                    info("请重新设置账号密码。\n")
                    first_run_setup()
                    ask_autostart()

    # --status
    if "--status" in argv:
        return cmd_status(cfg, cli)

    # --test
    if "--test" in argv:
        return cmd_test(cfg, cli)

    # 默认流程：读取凭据 → 自动登录
    creds = config_store.load()
    if creds is None:
        first_run_setup()
        creds = config_store.load()
    if creds is None:
        fail("读取凭据失败，请运行 --set 重新设置。")
        return 1

    banner()
    status = do_login(creds, cfg, cli)
    show_result(status)

    if LoginStatus.is_good(status):
        # 手动打开：登录完成后进入设置菜单，等待用户操作。
        # （开机自启走 --quiet 分支，不会到这里，实现"无感"）
        if "--menu" not in argv and "--keep" not in argv:
            print()
            try:
                show_settings_menu(cfg)
            except (EOFError, KeyboardInterrupt):
                info("\n已退出。")
            return 0

        # --keep：仅显示结果，不自动关闭
        _wait_enter()
        return 0

    auto_close(cfg, success=False)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        sys.exit(1)
    except Exception as e:
        print(f"\n程序发生未预期错误：{type(e).__name__}: {e}")
        info(f"详细信息见日志：{config.log_file()}")
        try:
            input("\n按回车键退出… ")
        except Exception:
            pass
        sys.exit(2)