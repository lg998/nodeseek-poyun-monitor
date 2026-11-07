# NodeSeek「破云」关键词自动监控（GitHub Actions 邮件推送）

基于 [NodeSeek 官方 RSS](https://rss.nodeseek.com/) 的零依赖 Python 监控脚本，通过 **GitHub Actions** 每 5 分钟自动检查最新帖子，**仅当帖子标题包含 `破云`** 时发送邮件通知，并自动记录已通知帖子 ID 防止重复推送。

## 功能特点

- **纯标准库零依赖**：仅使用 Python 3 内置标准库，启动耗时仅约 2~3 秒。
- **仅匹配标题**：严格匹配帖子 `<title>`，正文误提不触发打扰。
- **精准去重且零垃圾提交**：仅在命中新帖并成功发信后才由 `github-actions[bot]` 更新 [`seen_ids.json`](seen_ids.json)；无新帖时不产生任何 Git 提交。
- **一键测试发信**：支持在 GitHub Actions 页面手动勾选 `send_test_email` 立即发送测试邮件验证配置。

---

## 快速配置（只需 2 步）

### 第 1 步：生成 Gmail 应用专用密码（App Password）

如果你使用自己的 Gmail 发信给自己（推荐，最简单稳定）：

1. 确保你的 Google 账号已开启**两步验证（2-Step Verification）**。
2. 打开 Google 账号的 [应用专用密码页面](https://myaccount.google.com/apppasswords)。
3. 创建一个新应用名称（如 `NodeSeek Monitor`），复制生成的 **16 位应用专用密码**（形如 `abcd efgh ijkl mnop`，去掉空格或保留均可，建议去掉空格）。

> 如需使用 QQ 邮箱 / 163 邮箱发信给 Gmail，也可以在对应邮箱设置中开启 `SMTP` 服务获取授权码，并额外设置下方的 `SMTP_HOST`（如 `smtp.qq.com`）和 `SMTP_PORT`（`465`）。

### 第 2 步：在仓库中添加 Secrets

进入本仓库页面 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，添加以下密钥：

| Secret 名称 | 是否必填 | 说明 |
| :--- | :--- | :--- |
| `SMTP_USER` | **必填** | 发件邮箱账号（若用 Gmail 自发自收，直接填你的 Gmail 地址） |
| `SMTP_PASS` | **必填** | 第 1 步获取的 16 位 Gmail 应用专用密码（或其它邮箱的 SMTP 授权码） |
| `TO_EMAIL` | 可选（已预设则无需改） | 收件邮箱地址；未设置时默认发给 `SMTP_USER` |
| `SMTP_HOST` | 可选 | 默认 `smtp.gmail.com`（QQ 邮箱填 `smtp.qq.com`，163 填 `smtp.163.com`） |
| `SMTP_PORT` | 可选 | 默认 `465`（SSL）；如使用 STARTTLS 可填 `587` |

---

## 验证与运行

1. 打开仓库顶部的 **Actions** 标签页。
2. 在左侧选择 **NodeSeek 破云关键词监控**（如果提示启用 Workflows，点击启用即可）。
3. 点击右侧 **Run workflow** 按钮：
   - 勾选 **`发送测试邮件`** → 点击绿色的 **Run workflow**。
   - 等待约 10 秒运行变绿，检查收件箱是否收到测试邮件。
4. 测试通过后无需任何额外操作，GitHub Actions 将自动按 `*/5 * * * *` 定时巡检。

---

## 进阶自定义（可选）

如果想修改监控关键词或添加排除词（例如排除“收”、“求购”），无需改代码，直接在仓库 **Settings → Secrets and variables → Actions → Variables** 标签页添加 Repository variables：

- `KEYWORDS`：例如 `破云`（多个词用逗号分隔，如 `破云,PoYun`，任一命中即推送）
- `EXCLUDE_KEYWORDS`：例如 `收,求`（标题含任一排除词则忽略）

## 本地或自有 VPS 运行

如果你希望实现 30 秒级更实时监控，也可以在任意装有 Python 3.9+ 的服务器上直接运行：

```bash
export SMTP_USER="你的发件邮箱"
export SMTP_PASS="你的应用专用密码"
export TO_EMAIL="你的收件邮箱"
python3 monitor.py
```
