# NodeSeek「破云」关键词自动监控（Telegram / 邮件双通道推送）

基于 [NodeSeek 官方 RSS](https://rss.nodeseek.com/) 的零依赖 Python 监控脚本，通过 **GitHub Actions** 每 5 分钟自动检查最新帖子，**仅当帖子标题包含 `破云`** 时推送通知，并自动记录已通知帖子 ID 防止重复推送。

支持 **Telegram Bot** 与 **SMTP 邮件** 两种推送方式（任选其一即可，都填则双端同时推送）。

---

## 方式 A：推送到 Telegram（推荐，配置最快）

1. **创建专属机器人拿 Token**：
   - 在 Telegram 搜索官方 `@BotFather`，发送 `/newbot`，按提示起个名字即可获得一串 `TG_BOT_TOKEN`（形如 `123456789:AAH...`）。
   - **重要**：点进你刚创建的机器人对话框，点击底部的 **Start（开始）** 激活对话。
2. **获取你的 Chat ID**：
   - 在 Telegram 搜索 `@userinfobot`，随便发一句话，它会回复你的纯数字 `Id`（即 `TG_CHAT_ID`）。
3. **写入仓库 Secrets**：
   - 打开本仓库 **Settings → Secrets and variables → Actions → New repository secret**，添加：
     - `TG_BOT_TOKEN`：填你的机器人 Token
     - `TG_CHAT_ID`：填你的数字 ID

---

## 方式 B：推送到邮箱（可选）

如果你想发到邮箱，在同一 **Actions Secrets** 页面添加：

| Secret 名称 | 是否必填 | 说明 |
| :--- | :--- | :--- |
| `SMTP_USER` | **必填** | 发件邮箱账号（Gmail 自发自收填你的 Gmail） |
| `SMTP_PASS` | **必填** | [Google 16 位应用专用密码](https://myaccount.google.com/apppasswords) 或其它邮箱 SMTP 授权码 |
| `TO_EMAIL` | 可选 | 收件邮箱地址；未设置时默认发给 `SMTP_USER` |
| `SMTP_HOST` | 可选 | 默认 `smtp.gmail.com`（QQ 填 `smtp.qq.com`，163 填 `smtp.163.com`） |
| `SMTP_PORT` | 可选 | 默认 `465`（SSL）；STARTTLS 可填 `587` |

---

## 一键测试推送

1. 打开仓库顶部 **Actions** → 左侧选择 **NodeSeek 破云关键词监控**。
2. 点击右侧 **Run workflow** → 勾选 **`发送测试通知`** → 点击 **Run workflow**。
3. 约 10 秒后即可在 Telegram 或邮箱收到测试消息，之后系统会自动每 5 分钟巡检。
