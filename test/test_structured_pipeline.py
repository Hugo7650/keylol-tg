from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest

from domain.value_objects import FetchedThreadPage
from infrastructure.services import KeylolForumContentParser
from infrastructure.services import KeylolThreadPageExtractor
from infrastructure.services import TelegramFormatter


class StructuredPipelineTests(unittest.TestCase):
    def setUp(self):
        self.extractor = KeylolThreadPageExtractor()
        self.parser = KeylolForumContentParser()
        self.formatter = TelegramFormatter()

    def test_real_fixture_flows_through_structured_pipeline(self):
        fixture_path = Path(__file__).parent / "case" / "t1009483-1-1.htm"
        html = fixture_path.read_text(encoding="utf-8")
        page = FetchedThreadPage(
            thread_id=1009483,
            url="https://keylol.com/t1009483-1-1",
            html=html,
            fetched_at=datetime.now(),
        )

        raw = self.extractor.extract(page)
        result = self.parser.parse(raw)
        payload = self.formatter.format(result)

        self.assertEqual(raw.metadata.thread_id, 1009483)
        self.assertGreater(raw.metadata.root_post_id, 0)
        self.assertNotEqual(raw.metadata.title, "未知标题")
        self.assertTrue(result.fallback_text)
        self.assertIn(raw.metadata.title, payload.text)
        self.assertIn("[查看原帖](https://keylol.com/t1009483-1-1)", payload.text)

    def test_parser_normalizes_relative_media_urls(self):
        html = """
        <html><body>
        <a id="thread_subject">测试标题</a>
        <div id="postlist">
          <div id="post_123">
            <table>
              <tr>
                <td class="pls"><a class="xw1">测试作者</a></td>
                <td id="postmessage_123">
                  <p>正文<img src="/img/example.png" alt="示例图" /></p>
                </td>
              </tr>
            </table>
            <em id="authorposton123"><span title="2026-05-30 12:34:56"></span></em>
          </div>
        </div>
        </body></html>
        """
        page = FetchedThreadPage(
            thread_id=123,
            url="https://example.com/t123-1-1",
            html=html,
            fetched_at=datetime.now(),
        )

        raw = self.extractor.extract(page)
        result = self.parser.parse(raw)

        self.assertEqual(result.content.media_urls(), ("https://example.com/img/example.png",))
        self.assertIn("正文", result.fallback_text)


if __name__ == "__main__":
    unittest.main()
