# 归档说明

本项目于 2026-11-26 归档，不再维护。

## 为什么归档

这个 Python 版本能跑，但界面是命令行的，设置项要靠记忆输入参数，
配置多个网络的账号也不方便。功能上已被
**[SNNUAutoLogin-GUI](https://github.com/mzh2077/SNNUAutoLogin-GUI)** 全面覆盖。

## 新项目

**[SNNUAutoLogin-GUI](https://github.com/mzh2077/SNNUAutoLogin-GUI)**

C# + WinUI 3 原生客户端。相比这边的 Python 版：

| | Python 版（本项目） | WinUI 3 版 |
|---|---|---|
| 界面 | 命令行 | 图形界面 |
| 安装 | 绿色单文件 exe | 安装包 / 便携版 |
| 后台运行 | 静默无感 | 托盘常驻 |
| 断线重连 | 无 | 有 |
| 多网络配置 | 不支持 | 按有线/Wi-Fi 分别配账号 |
| 图形验证码 | 不支持 | 支持 |
| 跨平台 | 仅 Windows | 另有 Linux 版 |

## 代码还能用吗

能用。源码完整保留，`python main.py` 仍可运行。

已知问题（新版已修复或规避）：

- 在线状态下门户无法区分密码对错，改密码时需断开网络才能真正验证
- 门户改版后登录接口可能失效，需按 `README.md` 里的接口表更新 `config.py`
- 打包的 exe 会被杀毒软件误报（PyInstaller 通病）

## 技术备忘

给以后维护或二次开发的人：

- 门户接口：`http://202.117.144.205:80/zili/index.php`，
  字段 `mode=login` / `login` / `passwd`
- `snnuportal/login.jsp` 只是中转页，别往它提交密码
- 判定密码对错的唯一可靠依据是门户**明确**返回「帐号或密码错误」，
  其余情况都应判为"无法判定"——把"认不出"当成"密码错"会拒绝正确密码
- 密码用 Windows DPAPI 加密（`config_store.py`），
  cryptography 只是非 Windows 兜底，打包时可排除
- `python test_offline.py` 是离线回归测试，不联网就能跑

## 许可

MIT
