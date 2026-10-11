# -*- coding: utf-8 -*-
"""
凭据存储
========
账号密码不写死在代码里，也不明文落盘。

实现方式
--------
Windows : 使用 DPAPI（CryptProtectData / CryptUnprotectData）加密，
          密钥由系统绑定当前 Windows 用户账户，其他用户/换机无法解密。
          这是 Windows 上做本地凭据存储的标准做法。
其他系统: 退化为 AES-256-CBC，密钥由「机器指纹 + 用户名 + 本地盐」派生。
          安全性弱于 DPAPI，仅为跨平台可跑而设。

⚠️ 前提：首次运行时程序会**自动生成随机强密码**并在控制台提示你修改一次，
   避免与代码产生关联。
"""

import base64
import ctypes
import ctypes.wintypes
import getpass
import hashlib
import json
import os
import platform
import socket
import struct
import sys

from config import cred_file, data_dir

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    _HAS_CRYPTO = True
except Exception:
    _HAS_CRYPTO = False


# ---------------------------------------------------------------------------
# Windows DPAPI 封装
# ---------------------------------------------------------------------------
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _win_blob(data: bytes) -> DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
    return blob, buf  # 返回 buf 以防被 GC 回收


def _dpapi_encrypt(data: bytes) -> bytes | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob, in_buf = _win_blob(data)
        out_blob = DATA_BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x1
        if not crypt32.CryptProtectData(
                ctypes.byref(in_blob), "CampusAutoLogin", None, None, None,
                0x01, ctypes.byref(out_blob)):
            return None
        out_buf = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        kernel32.LocalFree(out_blob.pbData)
        del in_buf
        return out_buf
    except Exception:
        return None


def _dpapi_decrypt(data: bytes) -> bytes | None:
    if not sys.platform.startswith("win"):
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_blob, in_buf = _win_blob(data)
        out_blob = DATA_BLOB()
        if not crypt32.CryptUnprotectData(
                ctypes.byref(in_blob), None, None, None, None,
                0x01, ctypes.byref(out_blob)):
            return None
        out_buf = ctypes.string_at(out_blob.pbData, out_blob.cbData)
        kernel32.LocalFree(out_blob.pbData)
        del in_buf
        return out_buf
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 跨平台兜底：机器绑定的 AES 密钥
# ---------------------------------------------------------------------------
def _machine_key() -> bytes:
    """派生机器+用户绑定的密钥。仅为非 Windows 环境的兜底方案。"""
    seed = "|".join([
        platform.node(), getpass.getuser(), platform.system(),
        str(os.environ.get("COMPUTERNAME", "")),
        _STATIC_SALT,
    ])
    return hashlib.pbkdf2_hmac("sha256", seed.encode("utf-8"),
                               _STATIC_SALT.encode("utf-8"), 100_000)


# 静态盐：使相同机器/用户派生出稳定密钥
_STATIC_SALT = "CampusAutoLogin::v1::local-credential-store"


def _aes_encrypt(plain: bytes, key: bytes) -> bytes:
    if not _HAS_CRYPTO:
        raise RuntimeError("缺少 cryptography 库，无法加密存储凭据")
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    enc = cipher.encryptor()
    pad_len = 16 - (len(plain) % 16)
    padded = plain + bytes([pad_len]) * pad_len
    return iv + enc.update(padded) + enc.finalize()


def _aes_decrypt(token: bytes, key: bytes) -> bytes:
    if not _HAS_CRYPTO:
        raise RuntimeError("缺少 cryptography 库，无法解密凭据")
    iv, body = token[:16], token[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    dec = cipher.decryptor()
    padded = dec.update(body) + dec.finalize()
    pad_len = padded[-1]
    return padded[:-pad_len]


def encrypt(plain: bytes) -> bytes:
    token = _dpapi_encrypt(plain)
    if token is not None:
        return b"DPAPI1" + token
    return b"AES01" + _aes_encrypt(plain, _machine_key())


def decrypt(token: bytes) -> bytes:
    if token.startswith(b"DPAPI1"):
        out = _dpapi_decrypt(token[6:])
        if out is None:
            raise ValueError("DPAPI 解密失败（可能换了系统账户或用户）")
        return out
    if token.startswith(b"AES01"):
        return _aes_decrypt(token[5:], _machine_key())
    raise ValueError("凭据文件格式无法识别")


# ---------------------------------------------------------------------------
# 对外的读写接口
# ---------------------------------------------------------------------------
class Credentials:
    """保存账号、密码、运营商。password 仅在内存中存在。"""

    def __init__(self, account: str = "", password: str = "", carrier: str = ""):
        self.account = account
        self.password = password
        self.carrier = carrier

    @property
    def is_empty(self) -> bool:
        return not (self.account and self.password)

    def masked(self) -> str:
        """用于日志/展示的脱敏账号，例如 4266****@mobile"""
        if not self.account:
            return "(空)"
        acc = self.account
        if "@" in acc:
            user, domain = acc.split("@", 1)
            masked_user = (user[:4] + "****") if len(user) > 6 else (user[:2] + "**")
            return f"{masked_user}@{domain}"
        return (acc[:4] + "****") if len(acc) > 6 else (acc[:2] + "**")

    def __repr__(self) -> str:
        # 关键：避免密码被 print / 日志泄露
        return f"Credentials(account={self.masked()!r}, password=***, carrier={self.carrier!r})"


def exists() -> bool:
    return os.path.exists(cred_file())


def save(creds: Credentials) -> None:
    os.makedirs(data_dir(), exist_ok=True)
    payload = json.dumps({
        "account": creds.account,
        "password": creds.password,
        "carrier": creds.carrier,
    }, ensure_ascii=False).encode("utf-8")
    blob = encrypt(payload)
    path = cred_file()
    # 先写临时文件再原子替换，避免中断产生半截文件
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, path)
    _restrict(path)


def load() -> Credentials | None:
    """读取凭据；不存在或解密失败返回 None。"""
    path = cred_file()
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            token = f.read()
        data = json.loads(decrypt(token).decode("utf-8"))
        return Credentials(
            account=data.get("account", ""),
            password=data.get("password", ""),
            carrier=data.get("carrier", ""),
        )
    except Exception:
        return None


def clear() -> bool:
    """删除凭据文件（用于「忘记密码/重置」）。"""
    path = cred_file()
    if os.path.exists(path):
        try:
            os.remove(path)
            return True
        except OSError:
            return False
    return False


def _restrict(path: str) -> None:
    """把文件权限收紧到当前用户（类 Unix 有效；Windows 由 NTFS ACL 控制）。"""
    if os.name == "nt":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass