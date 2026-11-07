import tempfile
import unittest
from pathlib import Path

from monitor import (
    build_email_message,
    extract_post_id,
    load_seen_ids,
    match_title_keywords,
    parse_keywords,
    parse_rss_items,
    save_seen_ids,
)

SAMPLE_RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>NodeSeek</title>
    <link>https://www.nodeseek.com</link>
    <item>
      <title><![CDATA[【出】破云美西小鸡一台 剩余价值出]]></title>
      <link>https://www.nodeseek.com/post-1039001-1</link>
      <guid>https://www.nodeseek.com/post-1039001-1</guid>
      <pubDate>Sat, 07 Nov 2026 13:20:00 GMT</pubDate>
      <category>trade</category>
      <description><![CDATA[<p>配置 1C1G，流量充足，带原油出。</p>]]></description>
    </item>
    <item>
      <title>正文里提到破云但标题没有关键词</title>
      <link>https://www.nodeseek.com/post-1039002-1</link>
      <guid>https://www.nodeseek.com/post-1039002-1</guid>
      <pubDate>Sat, 07 Nov 2026 13:21:00 GMT</pubDate>
      <category>daily</category>
      <description><![CDATA[<p>这篇正文有破云两个字，但标题不含该词。</p>]]></description>
    </item>
  </channel>
</rss>
""".encode("utf-8")

# 修正第二条样例标题确保不含“破云”，只测试标题匹配而忽略正文
SAMPLE_RSS_STRICT_XML = SAMPLE_RSS_XML.replace(
    "正文里提到破云但标题没有关键词".encode("utf-8"),
    "普通VPS讨论帖（标题无目标词）".encode("utf-8"),
)


class MonitorUnitTests(unittest.TestCase):
    def test_parse_rss_and_match_title_only(self) -> None:
        items = parse_rss_items(SAMPLE_RSS_STRICT_XML)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["id"], "post-1039001")
        self.assertEqual(items[1]["id"], "post-1039002")

        kws = parse_keywords("破云")
        # 第一条标题含“破云” -> 命中
        self.assertEqual(match_title_keywords(items[0]["title"], kws), ["破云"])
        # 第二条仅正文含“破云”，标题不含 -> 不命中
        self.assertIn("破云", items[1]["summary"])
        self.assertEqual(match_title_keywords(items[1]["title"], kws), [])

    def test_extract_post_id_ignores_page_number(self) -> None:
        self.assertEqual(
            extract_post_id("https://www.nodeseek.com/post-1039001-1"),
            "post-1039001",
        )
        self.assertEqual(
            extract_post_id("https://www.nodeseek.com/post-1039001-3"),
            "post-1039001",
        )

    def test_state_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = Path(tmpdir) / "seen_ids.json"
            self.assertEqual(load_seen_ids(state_file), [])
            save_seen_ids(state_file, ["post-1", "post-2"])
            self.assertEqual(load_seen_ids(state_file), ["post-1", "post-2"])

    def test_build_email_message(self) -> None:
        items = parse_rss_items(SAMPLE_RSS_STRICT_XML)
        matched = [dict(items[0], matched_keywords=["破云"])]
        msg = build_email_message(
            matched,
            from_email="sender@gmail.com",
            to_email="receiver@gmail.com",
        )
        self.assertEqual(msg["To"], "receiver@gmail.com")
        plain_part = msg.get_payload()[0].get_payload(decode=True).decode("utf-8")
        html_part = msg.get_payload()[1].get_payload(decode=True).decode("utf-8")
        self.assertIn("post-1039001-1", plain_part)
        self.assertIn("破云", html_part)


if __name__ == "__main__":
    unittest.main()
