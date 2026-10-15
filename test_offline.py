# -*- coding: utf-8 -*-
"""重构后回归测试（离线，不触网）"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from portal_client import LoginStatus, PortalClient

cfg = config.portal()

ZILI_ONLINE = """<html><body><table id="ec_table"><tr>
<th>上网IP</th><th>MAC地址</th><th>上网时间</th><th>上网设备</th></tr>
<tr><td>10.138.47.56</td><td>e2:dc:89:3a:38:6a</td><td>2026-10-14 18:27</td></tr>
</table></body></html>"""

ZILI_BADPASS = """<html><body><span>帐号或密码错误 &nbsp; 账号： 密码：</span>
<input type="password" name="passwd"/></body></html>"""

ZILI_LOGINPAGE = """<html><body><form method="post">
<input type="password" name="passwd"/></form></body></html>"""

SNNU_ONLINE = """<html><body>当前登录账号：42662134@mobile　登录时间：2026-10-14
断开连接</body></html>"""

SNNU_MIDPAGE = """<html><body><iframe src="/zili/auth_my_state.php"></iframe>
<input type="hidden" id="account" value="42662134@mobile"/></body></html>"""

UNKNOWN_PAGE = "<html><body>系统维护中</body></html>"


class Fake(PortalClient):
    def __init__(self, cfg, zili, snnu=None):
        super().__init__(cfg)
        self.zili, self.snnu = zili, snnu

    def _open(self, url, data=None, timeout=None, **_):
        return 200, (self.zili if "zili" in url else (self.snnu or SNNU_MIDPAGE))


print("=" * 62)
print("重构后回归（离线）")
print("=" * 62)
ok = True
cases = [
    ("明确报错 → BADCRED", ZILI_BADPASS, LoginStatus.BAD_CREDENTIAL),
    ("登录成功页 → OK", ZILI_ONLINE, LoginStatus.OK),
    ("未改动登录页 → None", ZILI_LOGINPAGE, None),
    ("陌生页面 → None", UNKNOWN_PAGE, None),
    ("snnuportal 中转页 → None", SNNU_MIDPAGE, None),
]
for name, page, expect in cases:
    got = Fake(cfg, page)._verify_via_zili("42662134@mobile", "x")
    good = got == expect
    ok &= good
    print(f"  {'✓' if good else '✗'} {name:26} → {got}  (期望 {expect})")

print()
print("=== 主门户兜底 ===")
r = Fake(cfg, ZILI_LOGINPAGE, UNKNOWN_PAGE)._verify_via_main_portal("a@m", "b")
good = r != LoginStatus.BAD_CREDENTIAL
ok &= good
print(f"  {'✓' if good else '✗'} 陌生页面 → {r}  (绝不能是 BADCRED)")

r2 = Fake(cfg, ZILI_LOGINPAGE, SNNU_ONLINE)._verify_via_main_portal("42662134@mobile", "b")
good2 = r2 == LoginStatus.OK
ok &= good2
print(f"  {'✓' if good2 else '✗'} 主门户在线页 → {r2}  (期望 OK)")

print()
print("=== verify_by_logout 的恢复登录不再被吞掉 ===")
import inspect
from portal_client import PortalClient as PC
src = inspect.getsource(PC.verify_by_logout)
good3 = "except Exception: pass" not in src and "重新登录未成功" in src
ok &= good3
print(f"  {'✓' if good3 else '✗'} 恢复失败会记录日志（不再静默 pass）")

print()
print("=== 死代码 ===")
import ast, re
srcs = {f: open(f, encoding="utf-8").read() for f in os.listdir(".") if f.endswith(".py")}
allsrc = "\n".join(srcs.values())
dead = []
for f, s in srcs.items():
    if f in ("build.py", "make_icon.py"):
        continue
    for node in ast.walk(ast.parse(s)):
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("__"):
            if len(re.findall(r"\b" + re.escape(node.name) + r"\b", allsrc)) <= 1:
                dead.append(f"{f}:{node.name}")
good4 = not dead
ok &= good4
print(f"  {'✓' if good4 else '✗'} 零调用函数：{dead if dead else '无'}")

print()
print("=" * 62)
print("全部通过" if ok else "存在失败项")
print("=" * 62)