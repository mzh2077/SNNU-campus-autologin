# SNNU 校园网自动登录

> **本项目已归档，不再维护。**
>
> 请改用新版客户端：**[SNNUAutoLogin-GUI](https://github.com/mzh2077/SNNUAutoLogin-GUI)**
>
> 原生 WinUI 3 桌面客户端（Windows 11），有图形界面和安装包，
> 功能更完整、体验更好，不需要装 Python。
>
> 这个仓库保留下来是为了留个记录，里面仍是可用的 Python 版本，
> 但不建议再使用。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D4.svg)]()
[![Python: 3.9+](https://img.shields.io/badge/python-3.9+-3776AB.svg)]()

只适配陕西师范大学。其他学校需要改 `config.py`，见[移植到其他学校](#移植到其他学校)。

## 新版客户端

**[SNNUAutoLogin-GUI](https://github.com/mzh2077/SNNUAutoLogin-GUI)**

C# + WinUI 3 写的原生 Windows 客户端，Windows 版支持 Win10 2004+ 和 Win11。
比这个 Python 版本多了不少东西：

- 图形界面，不用对着命令行操作
- 附带安装包，双击安装，也能覆盖升级
- 托盘后台常驻，关闭主窗口后继续在后台保活
- 断线自动重连
- 可按有线、任意 Wi-Fi 或指定 Wi-Fi 名称分别配置账号和运营商
- 支持门户要求图形验证码的场景

Linux 桌面版和命令行预览版也有。

Releases 页下载 `SNNUAutoLogin-Setup-*.exe`。

## 下载（本 Python 版）

Releases 页下载 `SNNU-Campus-AutoLogin.exe`，不需要装 Python。

> 校验文件 `SHA256SUMS.txt` 里记录的就是这个文件名。
> GitHub 会把中文文件名降级成 `default.exe`，所以 Release 里用了英文名。

国内下载慢的话用网盘：<https://wwavz.lanzout.com/iQMyr4hcc2yh>，密码 `76b9`

## 杀毒软件会误报

PyInstaller 打包的程序基本都会被杀毒软件拦，这是打包方式的通病，不是程序有问题。

原因是它把 Python 解释器和代码压缩进一个 exe，这种「单文件塞满代码」的行为和恶意软件特征重合。任何用 PyInstaller 打包的程序都这样。

| 杀毒软件 | 怎么办 |
|---|---|
| Windows Defender | 点「更多信息」→「仍要运行」 |
| 360 / 火绒 | 加白名单，或信任该文件夹 |
| 都不行 | 右键 exe → 属性 → 勾「解除锁定」 |

程序是开源的，源码都在仓库里。行为也简单：只跟学校门户通信，密码用 Windows 自带的 DPAPI 加密存在本地。

实在不放心就别用现成的 exe，`git clone` 下来 `python main.py` 自己跑。

## 用法

1. 下载 exe，双击运行
2. 第一次会让你填账号、密码、运营商，照着填就行
3. 之后每次双击都会自动登录，成功后窗口自己关掉

想让它开机自动登录，在设置菜单里选开启即可。开机后完全静默，不弹窗、不倒计时，登录成功就退出。

### 命令行参数

平时不用管，需要的时候用：

| 参数 | 作用 |
|---|---|
| `--status` | 只看当前是否在线 |
| `--set` | 重新设置账号密码 |
| `--autostart` | 开启开机自启 |
| `--no-autostart` | 关闭开机自启 |
| `--purge` | 清除凭据与配置 |
| `--quiet` | 静默运行（开机自启用的，别手动用） |

## 常见问题

**开机后没反应 / 提示校园网不可达**

有些电脑开机后 WiFi 要过几秒才连上。程序会自己等，连上就继续登录，不用管它。
等太久还没连上，会提示你排查网络。

**提示密码错误**

程序会直接让你重新填，改完立刻重试，不用输什么命令。

有个例外：如果你**已经连着校园网**在改密码，门户这时分不清密码对不对，
程序会问你要不要断开网络验证一下。选择验证的话会断网几秒，验完自动连回。

**提示"无法判断密码是否正确"**

说明门户返回的页面和预期不一样，可能是门户改版了。
这**不代表你密码错了**。先用浏览器打开门户登录试试，确认密码无误即可。

**要不要用"登出验证"？**

想彻底确认密码对不对就选验证，会短暂断网几秒。
怕麻烦可以直接保存——即使密码错了，下次打开程序在界面里改就行，不会卡住。

## 数据存在哪

```
%LOCALAPPDATA%\CampusAutoLogin\
  ├── credentials.bin   加密后的账号密码
  ├── settings.json     配置
  └── run.log           运行日志
```

密码用 Windows DPAPI 加密，跟你的系统账户绑定，拷到别的电脑上解不开。
想彻底删除：设置菜单选 `4`。

## 开发者信息

<details>
<summary>展开</summary>

### 从源码运行

```bash
python main.py            # 运行
python test_offline.py    # 离线自测，不联网
python build.py           # 打包成 exe
```

### 门户接口

实测结论（2026-10）：

| 项目 | 结果 |
|---|---|
| 状态页 | `http://202.117.144.205:8603/snnuportal/userstatus.jsp` |
| 登录提交 | `http://202.117.144.205:80/zili/index.php` |
| 登录字段 | `mode=login` / `login` / `passwd` |
| 账号格式 | `学号@运营商`，如 `2024010101@mobile` |
| 密码错误响应 | 页面出现「帐号或密码错误」（注意是「帐号」） |
| 登录成功响应 | 含「上网IP / 上网时间 / MAC地址」表头的状态页 |

两个坑：

- `snnuportal/login.jsp` 现在只是个中转页，表单在 iframe 里，
  别往它提交密码
- 门户在本机已在线时**无法区分密码对错**，只有断开后重新登录才能验证

判定原则：**只有门户明确返回错误提示才判密码错，其他情况一律"无法判定"**。
不要把"认不出页面"当成"密码错误"，否则会拒绝正确密码。

### 改配置

大部分设置在 `config.py`：

| 字段 | 说明 |
|---|---|
| `status_url` | 状态页地址 |
| `login_url` | 登录提交地址 |
| `login_user_field` / `login_pass_field` | 登录表单字段名 |
| `max_retries` | 失败重试次数 |
| `wait_for_network` | 开机网络未就绪时是否等待 |
| `network_wait_timeout` | 最长等待秒数 |

### 移植到其他学校

改 `config.py` 里的接口地址和字段名，然后跑 `python test_offline.py`
确认判定逻辑没问题（需要把新学校的页面片段填进测试用例）。

多数情况下不需要动其他文件。

</details>

## 许可

MIT