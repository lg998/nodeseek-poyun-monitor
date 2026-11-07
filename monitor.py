#!/usr/bin/env python3
"""NodeSeek 官方 RSS 关键词监控与邮件推送脚本。

数据源：https://rss.nodeseek.com/（NodeSeek 官方 RSS 源）
功能：
1. 拉取最新帖子 RSS XML（兼容 RSS 2.0 <item> 与 Atom <entry>）
2. 仅匹配标题（title）中包含指定关键词（默认：破云）的帖子
3. 基于本地 JSON 状态文件对已推送帖子去重
4. 命中新帖时通过 SMTP 发送邮件通知（支持 SSL 465 与 STARTTLS 587），同时支持可选测试邮件
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate
import html
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import sys
from typing import Any
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_RSS_URL = "https://rss.nodeseek.com/"
DEFAULT_KEYWORDS = "破云"
DEFAULT_STATE_FILE = "seen_ids.json"
MAX_SEEN_IDS = 2000


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


def parse_keywords(raw: str) -> list[str]:
    """解析逗号或竖线分隔的关键词列表。"""
    parts = [p.strip() for p in re.split(r"[,，|]", raw) if p.strip()]
    return parts


def strip_html_tags(text: str) -> str:
    """移除简单 HTML 标签并反转义实体，用于生成邮件纯文本摘要。"""
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def fetch_rss_xml(url: str, timeout: int = 20) -> bytes:
    """从官方 RSS 地址获取 XML 内容。"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "NodeSeek-RSS-Monitor/1.0 (+https://github.com)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", 200)
        if status != 200:
            raise RuntimeError(f"RSS 请求返回非 200 状态码: HTTP {status}")
        return resp.read()


def _local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _child_text(elem: ET.Element, names: set[str]) -> str:
    for child in elem:
        if _local_tag(child.tag) in names:
            if _local_tag(child.tag) == "link" and not (child.text and child.text.strip()):
                href = child.attrib.get("href", "").strip()
                if href:
                    return href
            if child.text:
                return child.text.strip()
    return ""


def parse_rss_items(xml_bytes: bytes) -> list[dict[str, str]]:
    """解析 RSS 2.0 或 Atom XML，返回标准化的帖子列表。"""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        preview = xml_bytes[:200].decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"无法解析 RSS XML（可能触发了站点速率限制或返回了非 XML 页面）: {exc}; 响应前 200 字符: {preview!r}"
        ) from exc

    items: list[dict[str, str]] = []
    root_name = _local_tag(root.tag).lower()

    if root_name == "rss":
        item_elems = root.findall(".//item")
    else:
        item_elems = [el for el in root.iter() if _local_tag(el.tag) in ("item", "entry")]

    for elem in item_elems:
        title = html.unescape(_child_text(elem, {"title"}))
        link = _child_text(elem, {"link"})
        guid = _child_text(elem, {"guid", "id"})
        pub_date = _child_text(elem, {"pubDate", "published", "updated"})
        category = _child_text(elem, {"category"})
        creator = _child_text(elem, {"creator", "author"})
        description = _child_text(elem, {"description", "summary", "content", "encoded"})

        post_id = extract_post_id(guid or link or title)
        if not title and not link:
            continue

        items.append(
            {
                "id": post_id,
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "category": category,
                "author": creator,
                "summary": strip_html_tags(description)[:300],
            }
        )

    return items


def extract_post_id(identifier: str) -> str:
    """从链接或 guid（如 https://www.nodeseek.com/post-1037819-1）提取稳定帖子 ID。"""
    match = re.search(r"post-(\d+)", identifier)
    if match:
        return f"post-{match.group(1)}"
    return identifier.strip()


def match_title_keywords(
    title: str,
    keywords: list[str],
    exclude_keywords: list[str] | None = None,
) -> list[str]:
    """检测标题是否包含目标关键词（不区分大小写），并返回命中的关键词列表。"""
    title_lower = title.lower()
    if exclude_keywords:
        for ex in exclude_keywords:
            if ex.lower() in title_lower:
                return []
    return [kw for kw in keywords if kw.lower() in title_lower]


def load_seen_ids(state_path: Path) -> list[str]:
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("seen_ids"), list):
            return [str(x) for x in data["seen_ids"]]
        if isinstance(data, list):
            return [str(x) for x in data]
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[WARN] 读取状态文件 {state_path} 失败，将重新初始化: {exc}", file=sys.stderr)
    return []


def save_seen_ids(state_path: Path, seen_ids: list[str]) -> None:
    trimmed = seen_ids[-MAX_SEEN_IDS:]
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(trimmed),
        "seen_ids": trimmed,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_email_message(
    matched_posts: list[dict[str, Any]],
    from_email: str,
    to_email: str,
    is_test: bool = False,
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr(("NodeSeek 监控提醒", from_email))
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)

    if is_test:
        subject = "[测试成功] NodeSeek「破云」关键词监控邮件通知已打通"
    elif len(matched_posts) == 1:
        subject = f"[NodeSeek 破云提醒] {matched_posts[0]['title']}"
    else:
        subject = f"[NodeSeek 破云提醒] 发现 {len(matched_posts)} 条标题含关键词的新帖"

    msg["Subject"] = str(Header(subject, "utf-8"))

    text_lines: list[str] = []
    html_items: list[str] = []

    for idx, post in enumerate(matched_posts, start=1):
        title = post.get("title", "(无标题)")
        link = post.get("link", "https://www.nodeseek.com")
        pub_date = post.get("pub_date", "未知时间")
        category = post.get("category", "")
        summary = post.get("summary", "")
        matched_kws = ", ".join(post.get("matched_keywords", []))

        text_lines.append(f"{idx}. {title}")
        text_lines.append(f"   链接: {link}")
        if category:
            text_lines.append(f"   板块: {category}")
        text_lines.append(f"   发布时间: {pub_date}")
        if matched_kws:
            text_lines.append(f"   命中关键词: {matched_kws}")
        if summary:
            text_lines.append(f"   摘要: {summary}")
        text_lines.append("")

        meta_parts = [f"时间：{html.escape(pub_date)}"]
        if category:
            meta_parts.append(f"板块：{html.escape(category)}")
        if matched_kws:
            meta_parts.append(f"命中：{html.escape(matched_kws)}")

        summary_html = (
            f'<p style="margin:8px 0 0;color:#4b5563;font-size:14px;line-height:1.5;">'
            f"{html.escape(summary)}</p>"
            if summary
            else ""
        )

        html_items.append(
            f"""
            <div style="padding:14px 16px;margin-bottom:12px;border:1px solid #e5e7eb;border-radius:8px;background:#ffffff;">
              <a href="{html.escape(link)}" style="font-size:16px;font-weight:600;color:#2563eb;text-decoration:none;">
                {html.escape(title)}
              </a>
              <div style="margin-top:6px;color:#6b7280;font-size:12px;">
                {" &nbsp;|&nbsp; ".join(meta_parts)}
              </div>
              {summary_html}
            </div>
            """
        )

    plain_body = "\n".join(text_lines).strip()
    html_body = f"""<!DOCTYPE html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f9fafb;padding:20px;margin:0;">
  <div style="max-width:640px;margin:0 auto;">
    <h2 style="margin:0 0 16px;font-size:18px;color:#111827;">
      {"NodeSeek 监控连通性测试" if is_test else f"发现 {len(matched_posts)} 条匹配新帖"}
    </h2>
    {"".join(html_items)}
    <p style="margin-top:16px;color:#9ca3af;font-size:12px;">
      数据源：<a href="https://rss.nodeseek.com/" style="color:#6b7280;">NodeSeek 官方 RSS</a>
    </p>
  </div>
</body>
</html>"""

    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


def build_telegram_text(matched_posts: list[dict[str, Any]], is_test: bool = False) -> str:
    header = (
        "<b>✅ [测试成功] NodeSeek「破云」监控通知已打通</b>"
        if is_test
        else f"<b>🔔 NodeSeek 发现 {len(matched_posts)} 条匹配新帖</b>"
    )
    blocks: list[str] = [header]
    for post in matched_posts:
        title = html.escape(post.get("title", "(无标题)"))
        link = html.escape(post.get("link", "https://www.nodeseek.com"))
        category = html.escape(post.get("category", ""))
        pub_date = html.escape(post.get("pub_date", ""))
        matched_kws = html.escape(", ".join(post.get("matched_keywords", [])))
        summary = html.escape(post.get("summary", "")[:160])

        lines = [f'• <a href="{link}"><b>{title}</b></a>']
        meta = [
            x
            for x in (
                f"板块: {category}" if category else "",
                f"命中: {matched_kws}" if matched_kws else "",
                pub_date,
            )
            if x
        ]
        if meta:
            lines.append(f"  <i>{' | '.join(meta)}</i>")
        if summary:
            lines.append(f"  {summary}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def send_telegram_message(bot_token: str, chat_id: str, text: str, timeout: int = 20) -> None:
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="replace"))
        if not body.get("ok"):
            raise RuntimeError(f"Telegram API 返回错误: {body}")


def send_smtp_email(
    msg: MIMEMultipart,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    from_email: str,
    to_email: str,
) -> None:
    context = ssl.create_default_context()
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=25, context=context) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, [to_email], msg.as_string())
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=25) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, [to_email], msg.as_string())


def dispatch_notifications(
    posts: list[dict[str, Any]],
    *,
    is_test: bool,
    tg_bot_token: str,
    tg_chat_id: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_pass: str,
    from_email: str,
    to_email: str,
) -> bool:
    has_telegram = bool(tg_bot_token and tg_chat_id)
    has_email = bool(smtp_host and smtp_user and smtp_pass and to_email)

    if not has_telegram and not has_email:
        print(
            "[ERROR] 未配置任何推送通道！请在 Secrets 中配置 Telegram（TG_BOT_TOKEN + TG_CHAT_ID）或邮箱（SMTP_USER + SMTP_PASS）。",
            file=sys.stderr,
        )
        return False

    any_sent = False

    if has_telegram:
        try:
            tg_text = build_telegram_text(posts, is_test=is_test)
            send_telegram_message(tg_bot_token, tg_chat_id, tg_text)
            print("[INFO] Telegram 消息推送成功。")
            any_sent = True
        except Exception as exc:
            print(f"[ERROR] Telegram 推送失败: {exc}", file=sys.stderr)

    if has_email:
        try:
            msg = build_email_message(posts, from_email=from_email, to_email=to_email, is_test=is_test)
            send_smtp_email(msg, smtp_host, smtp_port, smtp_user, smtp_pass, from_email, to_email)
            print(f"[INFO] 邮件已成功推送至 {to_email}")
            any_sent = True
        except Exception as exc:
            print(f"[ERROR] 邮件推送失败: {exc}", file=sys.stderr)

    return any_sent


def main() -> int:
    rss_url = os.getenv("RSS_URL", DEFAULT_RSS_URL).strip() or DEFAULT_RSS_URL
    keywords = parse_keywords(os.getenv("KEYWORDS", DEFAULT_KEYWORDS))
    exclude_keywords = parse_keywords(os.getenv("EXCLUDE_KEYWORDS", ""))

    tg_bot_token = os.getenv("TG_BOT_TOKEN", "").strip()
    tg_chat_id = os.getenv("TG_CHAT_ID", "").strip()

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "465").strip() or "465")
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASS", "").strip()
    if "gmail.com" in smtp_host.lower():
        smtp_pass = smtp_pass.replace(" ", "")
    from_email = os.getenv("FROM_EMAIL", "").strip() or smtp_user
    to_email = os.getenv("TO_EMAIL", "").strip() or smtp_user
    state_path = Path(os.getenv("STATE_FILE", DEFAULT_STATE_FILE))

    dry_run = env_bool("DRY_RUN", False)
    send_test = env_bool("SEND_TEST_NOTIFICATION", False) or env_bool("SEND_TEST_EMAIL", False)

    if not keywords:
        print("[ERROR] KEYWORDS 不能为空。", file=sys.stderr)
        return 1

    active_channels: list[str] = []
    if tg_bot_token and tg_chat_id:
        active_channels.append("Telegram")
    if smtp_host and smtp_user and smtp_pass and to_email:
        active_channels.append("Email")

    print(f"[INFO] 监控源: {rss_url}")
    print(f"[INFO] 监控标题关键词: {keywords} | 排除词: {exclude_keywords or '无'}")
    print(f"[INFO] 已启用推送通道: {', '.join(active_channels) if active_channels else '尚未配置凭证'}")

    if send_test:
        test_post = [
            {
                "id": "test-0",
                "title": "【测试通知】NodeSeek「破云」关键词监控工作正常",
                "link": "https://www.nodeseek.com",
                "pub_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "category": "测试",
                "matched_keywords": keywords,
                "summary": "这是一条由手动触发生成的测试消息，收到说明推送配置已生效。",
            }
        ]
        if dry_run:
            print("[DRY_RUN] 测试通知预览生成成功，跳过实际发送。")
            return 0
        ok = dispatch_notifications(
            test_post,
            is_test=True,
            tg_bot_token=tg_bot_token,
            tg_chat_id=tg_chat_id,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_pass=smtp_pass,
            from_email=from_email,
            to_email=to_email,
        )
        return 0 if ok else 1

    try:
        xml_bytes = fetch_rss_xml(rss_url)
        items = parse_rss_items(xml_bytes)
    except urllib.error.HTTPError as exc:
        print(
            f"[ERROR] 拉取 RSS 失败 (HTTP {exc.code}): {exc.reason}。若在公共 Runner 上偶发 403/429，通常为节点 IP 被限流，将在下次调度重试。",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"[ERROR] 拉取或解析 RSS 失败: {exc}", file=sys.stderr)
        return 1

    print(f"[INFO] 本次共获取 {len(items)} 条最新 RSS 帖子。")

    seen_list = load_seen_ids(state_path)
    seen_set = set(seen_list)

    matched_new_posts: list[dict[str, Any]] = []
    # 按从旧到新处理，确保记录和通知顺序自然
    for item in reversed(items):
        post_id = item["id"]
        if post_id in seen_set:
            continue
        hit_kws = match_title_keywords(item["title"], keywords, exclude_keywords)
        if hit_kws:
            item_copy = dict(item)
            item_copy["matched_keywords"] = hit_kws
            matched_new_posts.append(item_copy)

    if not matched_new_posts:
        print("[INFO] 本次未发现标题包含目标关键词的新帖。")
        return 0

    print(f"[INFO] 命中 {len(matched_new_posts)} 条新帖:")
    for post in matched_new_posts:
        print(f"  - [{post['id']}] {post['title']} ({post['link']})")

    if dry_run:
        print("[DRY_RUN] 已跳过消息推送与状态写入。")
        return 0

    ok = dispatch_notifications(
        matched_new_posts,
        is_test=False,
        tg_bot_token=tg_bot_token,
        tg_chat_id=tg_chat_id,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        from_email=from_email,
        to_email=to_email,
    )
    if not ok:
        return 1

    for post in matched_new_posts:
        if post["id"] not in seen_set:
            seen_list.append(post["id"])
            seen_set.add(post["id"])
    save_seen_ids(state_path, seen_list)
    print(f"[INFO] 已更新去重状态文件: {state_path}（累计记录 {len(seen_list)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
