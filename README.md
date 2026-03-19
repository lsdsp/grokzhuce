# Grok 批量注册工具

批量注册 Grok 账号并自动开启 NSFW 功能。

## 功能

- 自动创建临时邮箱
- 自动获取验证码
- 自动完成注册流程
- 可配置是否开启 NSFW/Unhinged 模式
- NSFW 后置流程：`TOS -> Set Birth Date -> NSFW -> Unhinged(可降级)`
- 注册完成后自动清理临时邮箱（可通过 `KEEP_SUCCESS_EMAIL=true` 保留成功邮箱）
- 支持多线程并发注册
- 弱网保护：支持尝试上限与失败摘要输出
- 结构化运行指标日志（JSONL）

## 文件说明

| 文件 | 说明 |
|------|------|
| `grok.py` | 主程序，批量注册入口 |
| `StartAll.bat` | 一键启动（自动设代理、拉起 Solver、执行 grok） |
| `start_all.ps1` | 一键启动脚本主体（支持传参） |
| `start_all.sh` | Linux/macOS 一键启动脚本（参数与 `start_all.ps1` 对齐） |
| `TurnstileSolver.bat` | Turnstile Solver 启动脚本 |
| `api_solver.py` | Turnstile Solver CLI 入口 |
| `browser_configs.py` | 浏览器指纹配置 |
| `db_results.py` | Solver 结果存储兼容层 |
| `grok_config.py` | Grok 主流程配置构建与环境默认值 |
| `grok_runtime.py` | Grok 运行时模型、停止策略与 JSONL 日志 |
| `grok_protocol.py` | Grok bootstrap / 发码 / 验码等协议辅助逻辑 |
| `grok_registration.py` | Grok 注册主流程编排器 |
| `solver_browser_pool.py` | Solver 浏览器池生命周期管理 |
| `solver_logging.py` | Solver 日志样式与 logger 工厂 |
| `solver_page_actions.py` | Solver 页面交互/点击/注入策略 |
| `solver_result_repository.py` | Solver 结果仓储语义适配 |
| `solver_result_store.py` | Solver 结果存储后端（内存 / SQLite） |
| `solver_server.py` | Solver HTTP 服务与路由 |
| `solver_task_service.py` | Solver 单任务求解与结果调度 |
| `g/email_service.py` | 临时邮箱服务（moemail API） |
| `g/turnstile_service.py` | Turnstile 验证服务 |
| `g/user_agreement_service.py` | 用户协议同意服务 |
| `g/nsfw_service.py` | NSFW 设置服务 |
| `.env.example` | 环境变量模板 |
| `requirements.txt` | Python 依赖列表 |
| `pyproject.toml` | 项目元数据与 Python 版本约束 |

## 依赖

- [moemail](https://docs.moemail.app/api.html#openapi) - 临时邮箱服务（基于官方 API）
- Turnstile Solver - 内置验证码解决方案
- Quart / Patchright / Rich（本地 Turnstile Solver 运行依赖）

## 安装

```bash
pip install -r requirements.txt
```

## 已验证环境

| 维度 | 建议/已验证 |
|------|-------------|
| Python | `3.10` ~ `3.12` |
| Windows | Windows 10/11（`StartAll.bat` / `start_all.ps1`） |
| Linux/macOS | `bash` + Python（`start_all.sh`） |

安装后建议先做一次基础检查：

```bash
python -m pip check
python -c "import grok, api_solver, requests, curl_cffi, bs4; print('sanity ok')"
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
| MOEMAIL_VERIFY_SSL | moemail HTTPS 证书校验（可选，`true/false`，空字符串视为未设置） |
| YESCAPTCHA_KEY | YesCaptcha API Key（可选，不填使用本地 Solver） |
| SOLVER_RESULT_STORE | Solver 结果存储后端（可选，`memory/sqlite`，默认 `memory`） |
| SOLVER_RESULT_DB_PATH | SQLite 后端数据库路径（可选，默认 `logs/solver/solver-results.sqlite3`） |
| GROK_PROXY_URL | Grok 主流程代理（可选） |
| KEEP_SUCCESS_EMAIL | 注册成功后是否保留邮箱（可选，`true/false`，默认 `false`） |
| SSO_OUTPUT_MODE | 成功 token 输出策略（可选，`plain/masked/disabled/encrypted`，默认 `plain`） |
| SSO_ENCRYPTION_PASSPHRASE | 当 `SSO_OUTPUT_MODE=encrypted` 时使用的加密口令 |
| ENABLE_NSFW | 是否开启 NSFW/Unhinged（可选，`true/false`，默认 `true`） |
| NSFW_TIMEOUT | NSFW 后置请求超时秒数（可选，默认 `20`） |
| NSFW_RETRY_ATTEMPTS | NSFW 后置请求重试次数（可选，默认 `2`） |
| NSFW_CONCURRENT | NSFW 后置请求并发闸门（可选，默认 `3`） |
| UNHINGED_FEATURE_KEY | 自定义 Unhinged feature key（可选） |

## 使用

### 1. 启动 Turnstile Solver

双击运行 `TurnstileSolver.bat` 或执行：

```bash
python api_solver.py --browser_type camoufox --thread 5 --debug
```

等待 Solver 启动完成（默认监听 `http://127.0.0.1:5072`）

如需让 solver 结果跨重启保留，可在 `.env` 中启用 SQLite 后端：

```bash
SOLVER_RESULT_STORE=sqlite
SOLVER_RESULT_DB_PATH=logs/solver/solver-results.sqlite3
```

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
可选追加 `--metrics-file` 指定结构化日志输出路径（默认 `logs/grok/metrics.<timestamp>.jsonl`）。

注册成功的 SSO Token 输出受 `SSO_OUTPUT_MODE` 控制：

- `plain`：原样写入 `keys/grok_时间戳_数量.txt`
- `masked`：按脱敏形式写入文件，便于对账但不暴露完整 token
- `disabled`：不写入 token 文件内容（文件仍会创建，内容为空）
- `encrypted`：使用 `SSO_ENCRYPTION_PASSPHRASE` 加密后写入文件，文件中每行是单独的加密载荷

### 一键启动（推荐）

双击 `StartAll.bat`，默认会：

- 设置本地代理 `127.0.0.1:10808`
- 启动 Solver（`--thread 5`）
- Solver 初始化完成后提示输入 `threads` 和 `count`（回车使用默认 `3/5`）
- 运行日志分别写入 `logs/oneclick/`、`logs/solver/`、`logs/grok/`
- 注册流程结束后自动停止 Solver（无论是否达到目标，最长等待 3 分钟；若启动前已有 Solver 也会关闭）

也可以命令行传参：

```bash
StartAll.bat -Threads 3 -Count 30 -SolverThread 5 -MaxAttempts 120
```

如需在一键启动时直接指定 solver 结果存储后端，可追加：

```bash
StartAll.bat -Threads 3 -Count 30 -SolverResultStore sqlite -SolverResultDbPath logs/solver/solver-results.sqlite3
```

参数优先级：

- 传了 `-Threads/-Count`：直接使用，不再询问
- 未传 `-Threads/-Count`：在初始化后交互输入（支持回车使用默认值）
- 可传 `-MaxAttempts`：限制最大尝试次数（不传则由 `grok.py` 自动计算）
- 可传 `-SolverResultStore/-SolverResultDbPath`：仅在脚本自行拉起 solver 时覆盖结果存储后端
- 可传 `-ProxyHttp/-ProxySocks`：覆盖默认本地代理地址

禁用代理：

```bash
StartAll.bat -NoProxy
```

Linux / macOS 一键启动示例：

```bash
bash ./start_all.sh --threads 3 --count 30 --solver-thread 5 --max-attempts 120
```

启用 SQLite 后端：

```bash
bash ./start_all.sh --threads 3 --count 30 --solver-thread 5 --solver-result-store sqlite --solver-result-db-path logs/solver/solver-results.sqlite3
```

禁用代理：

```bash
bash ./start_all.sh --no-proxy
```

### 日志目录

- 新日志统一写入 `logs/`
- `logs/solver/`：solver 相关日志（`solver*`、`camoufox.fetch*`）
- `logs/grok/`：grok 相关日志（`grok*`）
- `logs/oneclick/`：一键流程日志（`start_all.*.log`、`release_smoke.*.log`）
- `logs/others/`：无法归类的日志
- `logs/grok/metrics.*.jsonl`：结构化运行指标
- 一键流程失败时会自动输出失败摘要（网络超时、TLS 错误、初始化失败等）

迁移历史日志（仅迁移已停止写入文件）：

```bash
powershell -ExecutionPolicy Bypass -File .\organize_logs.ps1
```

### JSONL 指标字段

`grok.py` 运行时会写入 JSONL 事件（每行一个 JSON 对象），包含：

- `ts`: UTC 时间戳
- `level`: 日志级别
- `stage`: 流程阶段（如 `scan_bootstrap`、`signup`、`record_success`）
- `message`: 事件摘要
- `thread_id` / `attempt_no`: 并发线程与全局尝试序号
- `email`: 脱敏邮箱
- `error_type`: 结构化错误类型
- `latency_ms`: 阶段耗时（毫秒）

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
