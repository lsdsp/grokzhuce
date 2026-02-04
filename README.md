# Grok 批量注册工具

批量注册 Grok 账号并自动开启 NSFW 功能。

## 功能

- 自动创建临时邮箱
- 自动获取验证码
- 自动完成注册流程
- 自动开启 NSFW/Unhinged 模式
- 注册完成后自动清理临时邮箱
- 支持多线程并发注册

## 依赖

- [freemail](https://github.com/user/freemail) - 临时邮箱服务（需自行部署）
- Turnstile Solver - 验证码解决方案

## 安装

```bash
pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env` 并填写配置：

```bash
cp .env.example .env
```

配置项说明：

| 配置项 | 说明 |
|--------|------|
| WORKER_DOMAIN | freemail 服务域名 |
| FREEMAIL_TOKEN | freemail JWT Token |
| YESCAPTCHA_KEY | YesCaptcha API Key（可选，不填使用本地 Solver） |

## 使用

```bash
python grok.py
```

按提示输入：
- 并发数（默认 8）
- 注册数量（默认 100）

注册成功的 SSO Token 保存在 `keys/grok_时间戳_数量.txt`

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

- 需要自行部署 freemail 临时邮箱服务
- 需要 Turnstile Solver（本地或 YesCaptcha）
- 仅供学习研究使用
