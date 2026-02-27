# Grok 批量注册工具

批量注册 Grok 账号并自动开启 NSFW 功能。

## 功能

- 自动创建临时邮箱
- 自动获取验证码
- 自动完成注册流程
- 自动开启 NSFW/Unhinged 模式
- 注册完成后自动清理临时邮箱（可通过 `KEEP_SUCCESS_EMAIL=true` 保留成功邮箱）
- 支持多线程并发注册
- 弱网保护：支持尝试上限与失败摘要输出

## 文件说明

| 文件 | 说明 |
|------|------|
| `grok.py` | 主程序，批量注册入口 |
| `StartAll.bat` | 一键启动（自动设代理、拉起 Solver、执行 grok） |
| `start_all.ps1` | 一键启动脚本主体（支持传参） |
| `TurnstileSolver.bat` | Turnstile Solver 启动脚本 |
| `api_solver.py` | Turnstile 验证码解决器 |
| `browser_configs.py` | 浏览器指纹配置 |
| `db_results.py` | 验证结果存储 |
| `g/email_service.py` | 临时邮箱服务（moemail API） |
| `g/turnstile_service.py` | Turnstile 验证服务 |
| `g/user_agreement_service.py` | 用户协议同意服务 |
| `g/nsfw_service.py` | NSFW 设置服务 |
| `.env.example` | 环境变量模板 |
| `requirements.txt` | Python 依赖列表 |

## 依赖

- [moemail](https://docs.moemail.app/api.html#openapi) - 临时邮箱服务（基于官方 API）
- Turnstile Solver - 内置验证码解决方案
- Quart / Patchright / Rich（本地 Turnstile Solver 运行依赖）

## 安装

```bash
pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env` 并填写配置：

Linux / macOS:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

配置项说明：

| 配置项 | 说明 |
|--------|------|
| MOEMAIL_API_URL | moemail API 地址（默认 `https://api.moemail.app`） |
| MOEMAIL_API_KEY | moemail API Key |
| MOEMAIL_PROXY_URL | moemail 请求代理（可选，空字符串视为未设置） |
| MOEMAIL_VERIFY_SSL | moemail HTTPS 证书校验（可选，`1/0`，空字符串视为未设置） |
| YESCAPTCHA_KEY | YesCaptcha API Key（可选，不填使用本地 Solver） |
| GROK_PROXY_URL | Grok 主流程代理（可选） |
| KEEP_SUCCESS_EMAIL | 注册成功后是否保留邮箱（可选，`true/false`，默认 `false`） |

## 使用

### 1. 启动 Turnstile Solver

双击运行 `TurnstileSolver.bat` 或执行：

```bash
python api_solver.py --browser_type camoufox --thread 5 --debug
```

等待 Solver 启动完成（默认监听 `http://127.0.0.1:5072`）

### 2. 运行注册程序

新开一个终端，运行：

```bash
python grok.py
```

按提示输入：
- 并发数（默认 8）
- 注册数量（默认 100）

可选：限制失败环境下的总尝试次数（避免长时间无界重试）：

```bash
python grok.py --threads 3 --count 30 --max-attempts 120
```

未传 `--max-attempts` 时，默认按 `max(count*4, count+10)` 自动计算。

注册成功的 SSO Token 保存在 `keys/grok_时间戳_数量.txt`

### 一键启动（推荐）

双击 `StartAll.bat`，默认会：

- 设置本地代理 `127.0.0.1:10808`
- 启动 Solver（`--thread 5`）
- Solver 初始化完成后提示输入 `threads` 和 `count`（回车使用默认 `3/5`）
- 运行日志分别写入 `logs/oneclick/`、`logs/solver/`、`logs/grok/`

也可以命令行传参：

```bash
StartAll.bat -Threads 3 -Count 30 -SolverThread 5 -MaxAttempts 120
```

参数优先级：

- 传了 `-Threads/-Count`：直接使用，不再询问
- 未传 `-Threads/-Count`：在初始化后交互输入（支持回车使用默认值）
- 可传 `-MaxAttempts`：限制最大尝试次数（不传则由 `grok.py` 自动计算）
- 可传 `-ProxyHttp/-ProxySocks`：覆盖默认本地代理地址

禁用代理：

```bash
StartAll.bat -NoProxy
```

### 日志目录

- 新日志统一写入 `logs/`
- `logs/solver/`：solver 相关日志（`solver*`、`camoufox.fetch*`）
- `logs/grok/`：grok 相关日志（`grok*`）
- `logs/oneclick/`：一键流程日志（`start_all.*.log`、`release_smoke.*.log`）
- `logs/others/`：无法归类的日志
- 一键流程失败时会自动输出失败摘要（网络超时、TLS 错误、初始化失败等）

迁移历史日志（仅迁移已停止写入文件）：

```bash
powershell -ExecutionPolicy Bypass -File .\organize_logs.ps1
```

### 发布前冒烟检查

```powershell
powershell -ExecutionPolicy Bypass -File .\release_smoke.ps1
```

说明：
- 运行全部 `unittest`
- 检查 solver 基础 API 健康（`/result`、`/turnstile`）
- 若本机未运行 solver，会临时启动并在检查后自动停止

## 输出示例

```
============================================================
Grok 注册机
============================================================
[*] 正在初始化...
[+] Action ID: 7f67aa61adfb0655899002808e1d443935b057c25b
[*] 启动 8 个线程，目标 10 个
[*] 输出: keys/grok_20260204_190000_10.txt
[*] 开始注册: abc123@example.com
[+] 1/10 abc123@example.com | 5.2s/个
[+] 2/10 def456@example.com | 4.8s/个
...
[*] 开始二次验证 NSFW...
[*] 二次验证完成: 10/10
```

## 注意事项

- 需要配置可用的 moemail API Key
- 手动运行 `grok.py` 前需要先启动 Turnstile Solver；使用 `StartAll.bat` 会自动拉起 Solver
- 仅供学习研究使用
