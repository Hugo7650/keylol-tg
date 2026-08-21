from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest
from typing import Any
from typing import cast
from unittest.mock import patch

from domain.value_objects import CodeBlockNode
from domain.value_objects import EmbedNode
from domain.value_objects import ImageElement
from domain.value_objects import HiddenBlockNode
from domain.value_objects import LineBreakElement
from domain.value_objects import LinkElement
from domain.value_objects import PageBreakNode
from domain.value_objects import ParseResult
from domain.value_objects import PostContent
from domain.value_objects import QuoteElement
from domain.value_objects import RawThreadData
from domain.value_objects import RootPostFragment
from domain.value_objects import RootPostMetadata
from domain.value_objects import TextElement
from domain.value_objects import FetchedThreadPage
from domain.value_objects import UnknownElement
from infrastructure.services import KeylolForumContentParser
from infrastructure.services import KeylolThreadPageExtractor
from infrastructure.services import TelegramFormatter
from models.post import ForumPost


class StructuredPipelineTests(unittest.TestCase):
    def setUp(self):
        self.extractor = KeylolThreadPageExtractor()
        self.parser = KeylolForumContentParser()
        self.formatter = TelegramFormatter()

    def _make_metadata(self, **kwargs) -> RootPostMetadata:
        return cast(Any, RootPostMetadata)(**kwargs)

    def _make_raw(self, **kwargs) -> RawThreadData:
        return cast(Any, RawThreadData)(**kwargs)

    def _make_embed(self, **kwargs) -> EmbedNode:
        return cast(Any, EmbedNode)(**kwargs)

    def _parse_container_fixture(self, fixture_name: str) -> ParseResult:
        fixture_path = Path(__file__).parent / "case" / "keylol_guide_pages" / fixture_name
        metadata = self._make_metadata(
            thread_id=307370,
            root_post_id=4796006,
            title=fixture_name,
            author="guide",
            publish_time=datetime(2026, 5, 30, 12, 34, 56),
            url=f"https://keylol.com/{fixture_name}",
        )
        raw = self._make_raw(
            metadata=metadata,
            root_post_html=fixture_path.read_text(encoding="utf-8"),
            container_kind="postmessage",
        )
        return self.parser.parse(raw)

    def test_parser_emits_mvp_nodes_for_supported_structures(self):
        metadata = self._make_metadata(
            thread_id=321,
            root_post_id=654,
            title="语义测试",
            author="测试作者",
            publish_time=datetime(2026, 5, 30, 12, 34, 56),
            url="https://example.com/t321-1-1",
        )
        raw = self._make_raw(
            metadata=metadata,
            root_post_html="""
            <div>
              <div class="blockcode"><div><ol><li>print('hello')</li></ol></div><em>复制代码</em></div>
              <div class="showhide"><h4>本帖隐藏的内容</h4>隐藏正文</div>
              <div class="sff_collapse sff_collapsed"><div class="sff_collapse_b"><span class="sff_collapse_t">&gt;</span> 注释标题</div><div class="sff_collapse_d">折叠正文<div><a href="javascript:;">点击隐藏</a></div></div></div>
              <span class="bbcode_spoiler"><span class="bbcode_spoiler_content">剧透正文</span></span>
              <blockquote>引用内容</blockquote>
              <a href="https://example.com/path">查看详情</a>
              <img file="https://example.com/image.png" alt="示例图" />
              <iframe class="html5video" src="https://example.com/video"></iframe>
            </div>
            """,
            container_kind="postmessage",
        )

        result = self.parser.parse(raw)

        self.assertTrue(result.is_successful)
        self.assertTrue(any(isinstance(node, CodeBlockNode) for node in result.content.elements))
        hidden_blocks = [node for node in result.content.elements if isinstance(node, HiddenBlockNode)]
        self.assertEqual([node.hidden_kind for node in hidden_blocks[:3]], ["hide", "collapse", "spoiler"])
        self.assertIn("查看详情", result.fallback_text)
        self.assertIn("示例图", result.fallback_text)
        self.assertTrue(any(isinstance(node, EmbedNode) for node in result.content.elements))

    def test_parser_inserts_page_breaks_between_fragments(self):
        metadata = self._make_metadata(
            thread_id=123,
            root_post_id=123,
            title="分页帖",
            author="测试作者",
            publish_time=datetime(2026, 5, 30, 12, 34, 56),
            url="https://example.com/t123-1-1",
        )
        raw = self._make_raw(
            metadata=metadata,
            root_post_html="<p>第一页</p>",
            container_kind="postmessage",
            fragments=(
                RootPostFragment(page_number=1, container_kind="postmessage", html="<p>第一页</p>"),
                RootPostFragment(page_number=2, container_kind="postmessage", html="<p>第二页</p>"),
            ),
        )

        result = self.parser.parse(raw)

        self.assertTrue(any(isinstance(node, PageBreakNode) for node in result.content.elements))
        self.assertIn("第 2 页", result.fallback_text)

    def test_formatter_outputs_html_payload(self):
        metadata = self._make_metadata(
            thread_id=999,
            root_post_id=999,
            title="格式化测试",
            author="测试作者",
            publish_time=datetime(2026, 5, 30, 12, 34, 56),
            url="https://example.com/t999-1-1",
            tags=("标签A", "标签B"),
        )
        content = PostContent(
            metadata=metadata,
            elements=(
                TextElement(text="加粗正文", bold=True),
                LinkElement(url="https://example.com/link", text="查看详情"),
                CodeBlockNode(code="print('hi')"),
                ImageElement(url="https://example.com/example.png", alt_text="示例图"),
                self._make_embed(
                    provider="steam",
                    url="https://store.steampowered.com/app/123/",
                    label="游戏名",
                ),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertEqual(payload.parse_mode, "html")
        self.assertIn("<b>格式化测试</b>", payload.text)
        self.assertIn('<a href="https://example.com/link">查看详情</a>', payload.text)
        self.assertIn("<pre>print(&#x27;hi&#x27;)</pre>", payload.text)
        self.assertIn('<a href="https://example.com/example.png">示例图</a>', payload.text)
        self.assertIn('<a href="https://store.steampowered.com/app/123/">游戏名</a>', payload.text)
        self.assertIn('<a href="https://example.com/t999-1-1">查看原帖</a>', payload.text)
        self.assertEqual(
            payload.media_urls,
            (
                "https://example.com/example.png",
                "https://store.steampowered.com/app/123/",
            ),
        )

    def test_formatter_resolves_steam_embed_name(self):
        metadata = self._make_metadata(
            thread_id=998,
            root_post_id=998,
            title="Steam 名称测试",
            author="测试作者",
            publish_time=datetime(2026, 5, 30, 12, 34, 56),
            url="https://example.com/t998-1-1",
        )
        content = PostContent(
            metadata=metadata,
            elements=(
                self._make_embed(
                    provider="steam",
                    url="https://store.steampowered.com/app/1681430/",
                    label="Steam",
                ),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        with (
            patch.object(self.formatter, "_fetch_steam_store_api_label", return_value=None),
            patch.object(
                self.formatter,
                "_fetch_steam_title",
                return_value="Steam 上的 RoboCop: Rogue City",
            ),
        ):
            payload = self.formatter.format(result)

        self.assertIn(
            '<a href="https://store.steampowered.com/app/1681430/">RoboCop: Rogue City</a>',
            payload.text,
        )

    def test_formatter_resolves_steam_embed_name_from_store_api(self):
        metadata = self._make_metadata(
            thread_id=987,
            root_post_id=987,
            title="Steam API 名称测试",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 16, 30, 0),
            url="https://example.com/t987-1-1",
        )
        content = PostContent(
            metadata=metadata,
            elements=(
                self._make_embed(
                    provider="steam",
                    url="https://store.steampowered.com/app/4532590/",
                    label="Steam",
                ),
            ),
        )

        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        with patch.object(
            self.formatter,
            "_fetch_steam_store_api_label",
            return_value="BSide: Olivia Lin",
        ) as fetch_api:
            payload = self.formatter.format(result)

        fetch_api.assert_called_once_with("https://store.steampowered.com/app/4532590/")
        self.assertIn(
            '<a href="https://store.steampowered.com/app/4532590/">BSide: Olivia Lin</a>',
            payload.text,
        )

    def test_formatter_builds_escaped_unavailable_post_payload(self):
        post = ForumPost(
            id=123,
            title="标题 <测试> & 状态",
            author="作者 <甲>",
            url='https://example.com/t123-1-1?from="guide"&page=1',
        )

        payload = self.formatter.format_unavailable_post(
            post,
            "抱歉，您没有 <权限> & 请稍后重试",
        )

        self.assertEqual(payload.parse_mode, "html")
        self.assertEqual(payload.media_urls, ())
        self.assertEqual(
            payload.text,
            "<b>标题 &lt;测试&gt; &amp; 状态</b>\n"
            "作者 &lt;甲&gt;\n"
            "论坛提示：抱歉，您没有 &lt;权限&gt; &amp; 请稍后重试\n"
            '<a href="https://example.com/t123-1-1?from=&quot;guide&quot;&amp;page=1">查看原帖</a>',
        )

    def test_formatter_uses_thread_title_when_steam_title_is_error_page(self):
        metadata = self._make_metadata(
            thread_id=990,
            root_post_id=990,
            title="米哈游《BSide: Olivia Lin》Steam页面开放，发行日期待定",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 16, 30, 0),
            url="https://example.com/t990-1-1",
        )
        content = PostContent(
            metadata=metadata,
            elements=(
                self._make_embed(
                    provider="steam",
                    url="https://store.steampowered.com/app/4532590/",
                    label="Steam",
                ),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        with (
            patch.object(self.formatter, "_fetch_steam_store_api_label", return_value=None),
            patch.object(self.formatter, "_fetch_steam_title", return_value="站点错误"),
        ):
            payload = self.formatter.format(result)

        self.assertIn(
            '<a href="https://store.steampowered.com/app/4532590/">BSide: Olivia Lin</a>',
            payload.text,
        )
        self.assertNotIn("站点错误", payload.text)

    def test_formatter_truncates_overlong_message_to_telegram_limit(self):
        metadata = self._make_metadata(
            thread_id=997,
            root_post_id=997,
            title="超长帖子测试",
            author="测试作者",
            publish_time=datetime(2026, 5, 30, 12, 34, 56),
            url="https://example.com/t997-1-1",
        )
        long_text = "很长的正文" * 1200
        content = PostContent(
            metadata=metadata,
            elements=(TextElement(text=long_text),),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertLessEqual(len(payload.text), 4096)
        self.assertIn("…", payload.text)
        self.assertIn('<a href="https://example.com/t997-1-1">查看原帖</a>', payload.text)

    def test_formatter_preserves_links_when_truncating_overlong_html(self):
        metadata = self._make_metadata(
            thread_id=993,
            root_post_id=993,
            title="超长链接帖子测试",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 16, 30, 0),
            url="https://keylol.com/t1041338-1-1",
        )
        image_url = "https://shared.st.dl.eccdnx.com/store_item_assets/steam/apps/4532590/extras_big/example.webp"
        steam_url = "https://store.steampowered.com/app/4532590/"
        content = PostContent(
            metadata=metadata,
            elements=(
                self._make_embed(
                    provider="steam",
                    url=steam_url,
                    label="BSide: Olivia Lin",
                ),
                LineBreakElement(),
                ImageElement(url=image_url, alt_text=None),
                LineBreakElement(),
                TextElement(text="很长的正文" * 1200),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertLessEqual(len(payload.text), 4096)
        self.assertIn("…", payload.text)
        self.assertIn(
            '<a href="https://store.steampowered.com/app/4532590/">BSide: Olivia Lin</a>',
            payload.text,
        )
        self.assertIn(f'<a href="{image_url}">图片</a>', payload.text)
        self.assertNotIn("[图片]", payload.text)

    def test_formatter_wraps_long_segment_in_expandable_blockquote(self):
        metadata = self._make_metadata(
            thread_id=996,
            root_post_id=996,
            title="长段落测试",
            author="测试作者",
            publish_time=datetime(2026, 5, 30, 12, 34, 56),
            url="https://example.com/t996-1-1",
        )
        long_text = "长段落正文" * 70
        content = PostContent(
            metadata=metadata,
            elements=(TextElement(text=long_text),),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn("<blockquote expandable>", payload.text)
        self.assertIn(long_text[:40], payload.text)
        self.assertIn('<a href="https://example.com/t996-1-1">查看原帖</a>', payload.text)

    def test_formatter_wraps_long_quote_in_expandable_blockquote(self):
        metadata = self._make_metadata(
            thread_id=992,
            root_post_id=992,
            title="长引用测试",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 16, 30, 0),
            url="https://example.com/t992-1-1",
        )
        quote_text = "引用正文" * 80
        content = PostContent(
            metadata=metadata,
            elements=(QuoteElement(children=(TextElement(text=quote_text),)),),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn("<blockquote expandable>", payload.text)
        self.assertIn(quote_text[:40], payload.text)
        self.assertNotIn("<blockquote><blockquote expandable>", payload.text)

    def test_formatter_wraps_quote_by_plain_text_length(self):
        metadata = self._make_metadata(
            thread_id=989,
            root_post_id=989,
            title="图片引用长度测试",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 16, 30, 0),
            url="https://example.com/t989-1-1",
        )
        quote_text = "引用正文" * 80
        content = PostContent(
            metadata=metadata,
            elements=(QuoteElement(children=(TextElement(text=quote_text),)),),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn("<blockquote expandable>", payload.text)

    def test_formatter_wraps_long_multi_paragraph_body_in_expandable_blockquote(self):
        metadata = self._make_metadata(
            thread_id=991,
            root_post_id=991,
            title="多段长正文测试",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 16, 30, 0),
            url="https://example.com/t991-1-1",
        )
        first = "第一段正文" * 35
        second = "第二段正文" * 35
        content = PostContent(
            metadata=metadata,
            elements=(
                TextElement(text=first),
                LineBreakElement(),
                TextElement(text=second),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn("<blockquote expandable>", payload.text)
        self.assertIn(first[:40], payload.text)
        self.assertIn(second[:40], payload.text)
        self.assertIn(f"{first}\n{second}", payload.text)

    def test_formatter_does_not_add_blank_line_for_single_break_around_block(self):
        metadata = self._make_metadata(
            thread_id=995,
            root_post_id=995,
            title="单换行测试",
            author="测试作者",
            publish_time=datetime(2026, 5, 30, 12, 34, 56),
            url="https://example.com/t995-1-1",
        )
        content = PostContent(
            metadata=metadata,
            elements=(
                TextElement(text="第一行"),
                LineBreakElement(),
                CodeBlockNode(code="print('x')"),
                LineBreakElement(),
                TextElement(text="第二行"),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn("第一行\n<pre>print(&#x27;x&#x27;)</pre>\n第二行", payload.text)
        self.assertNotIn("第一行\n\n<pre>", payload.text)
        self.assertNotIn("</pre>\n\n第二行", payload.text)

    def test_formatter_removes_extra_blank_line_after_heading(self):
        metadata = self._make_metadata(
            thread_id=988,
            root_post_id=988,
            title="标题空行测试",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 16, 30, 0),
            url="https://example.com/t988-1-1",
        )
        content = PostContent(
            metadata=metadata,
            elements=(
                TextElement(text="关于此软件", bold=True),
                LineBreakElement(),
                LineBreakElement(),
                QuoteElement(children=(TextElement(text="正文"),)),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn("<b>关于此软件</b>\n<blockquote>正文</blockquote>", payload.text)
        self.assertNotIn("<b>关于此软件</b>\n\n<blockquote>", payload.text)

    def test_formatter_removes_extra_blank_line_before_heading(self):
        metadata = self._make_metadata(
            thread_id=986,
            root_post_id=986,
            title="标题前空行测试",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 16, 30, 0),
            url="https://example.com/t986-1-1",
        )
        content = PostContent(
            metadata=metadata,
            elements=(
                LinkElement(url="https://example.com/app", text="应用名"),
                LineBreakElement(),
                LineBreakElement(),
                TextElement(text="游戏简介", bold=True),
                LineBreakElement(),
                LineBreakElement(),
                QuoteElement(children=(TextElement(text="简介正文"),)),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn('<a href="https://example.com/app">应用名</a>\n<b>游戏简介</b>', payload.text)
        self.assertNotIn('<a href="https://example.com/app">应用名</a>\n\n<b>游戏简介</b>', payload.text)
        self.assertIn("<b>游戏简介</b>\n<blockquote>简介正文</blockquote>", payload.text)

    def test_formatter_removes_extra_blank_lines_between_components(self):
        metadata = self._make_metadata(
            thread_id=985,
            root_post_id=985,
            title="组件空行测试",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 16, 30, 0),
            url="https://example.com/t985-1-1",
        )
        content = PostContent(
            metadata=metadata,
            elements=(
                LinkElement(url="https://example.com/demo", text="Demo"),
                LineBreakElement(),
                LineBreakElement(),
                LinkElement(url="https://example.com/base", text="Base Game"),
                LineBreakElement(),
                LineBreakElement(),
                QuoteElement(children=(TextElement(text="引用正文"),)),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn(
            '<a href="https://example.com/demo">Demo</a>\n'
            '<a href="https://example.com/base">Base Game</a>\n'
            "<blockquote>引用正文</blockquote>",
            payload.text,
        )
        self.assertNotIn('Demo</a>\n\n<a href="https://example.com/base"', payload.text)
        self.assertNotIn('Base Game</a>\n\n<blockquote>', payload.text)

    def test_formatter_preserves_blank_line_for_double_break(self):
        metadata = self._make_metadata(
            thread_id=994,
            root_post_id=994,
            title="双换行测试",
            author="测试作者",
            publish_time=datetime(2026, 5, 30, 12, 34, 56),
            url="https://example.com/t994-1-1",
        )
        content = PostContent(
            metadata=metadata,
            elements=(
                TextElement(text="第一行"),
                LineBreakElement(),
                LineBreakElement(),
                TextElement(text="第二行"),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn("第一行\n\n第二行", payload.text)

    def test_formatter_renders_table_rows_as_compact_records(self):
        metadata = self._make_metadata(
            thread_id=984,
            root_post_id=984,
            title="表格排版测试",
            author="测试作者",
            publish_time=datetime(2026, 6, 18, 8, 54, 0),
            url="https://example.com/t984-1-1",
        )
        table_html = """
        <table class="t_table">
          <tr>
            <td>游戏名称</td>
            <td><strong>商店价格</strong></td>
            <td><strong>进包</strong></td>
            <td><strong>游戏评价</strong></td>
            <td><strong>语言支持</strong></td>
          </tr>
          <tr>
            <td><a href="https://store.steampowered.com/app/1817230/">Hi-Fi RUSH</a></td>
            <td><strong>新史低 ¥62.50（-50%）</strong></td>
            <td><a href="https://barter.vg/steam/app/1817230/">1次</a></td>
            <td><strong>好评如潮 （26994篇× 97% ）</strong></td>
            <td><strong>支持简中繁中</strong></td>
          </tr>
          <tr>
            <td><a href="https://store.steampowered.com/app/2183900/">Warhammer 40,000: Space Marine 2</a></td>
            <td><strong>平史低 ¥149.00（-50%）</strong></td>
            <td>0次</td>
            <td><strong>特别好评 （12500篇× 84% ）</strong></td>
            <td><strong>支持简中</strong></td>
          </tr>
        </table>
        """
        content = PostContent(
            metadata=metadata,
            elements=(
                UnknownElement(
                    raw_html=table_html,
                    text_fallback=(
                        "游戏名称 商店价格 进包 游戏评价 语言支持 "
                        "Hi-Fi RUSH 新史低 ¥62.50（-50%）"
                    ),
                    label="table",
                ),
            ),
        )
        result = ParseResult(content=content, fallback_text=content.to_plain_text())

        payload = self.formatter.format(result)

        self.assertIn(
            "表格: 游戏名称 / 商店价格 / 进包 / 游戏评价 / 语言支持",
            payload.text,
        )
        self.assertIn(
            '• <a href="https://store.steampowered.com/app/1817230/">Hi-Fi RUSH</a>',
            payload.text,
        )
        self.assertIn(
            "商店价格: 新史低 ¥62.50（-50%） ｜ 进包: "
            '<a href="https://barter.vg/steam/app/1817230/">1次</a>',
            payload.text,
        )
        self.assertNotIn(
            "游戏名称 商店价格 进包 游戏评价 语言支持 Hi-Fi RUSH 新史低",
            payload.text,
        )

    def test_parser_handles_mvp_guide_fixtures(self):
        code_result = self._parse_container_fixture("cp-03-postmessage.html")
        self.assertTrue(
            any(isinstance(node, CodeBlockNode) for node in code_result.content.elements)
        )

        hidden_result = self._parse_container_fixture("cp-04-postmessage.html")
        hidden_kinds = {
            node.hidden_kind
            for node in hidden_result.content.elements
            if isinstance(node, HiddenBlockNode)
        }
        self.assertTrue({"hide", "collapse", "spoiler"}.issubset(hidden_kinds))

        link_result = self._parse_container_fixture("cp-05-postmessage.html")
        self.assertTrue(
            any(
                isinstance(node, LinkElement) and "store.steampowered.com" in node.url
                for node in link_result.content.elements
            )
        )

        embed_result = self._parse_container_fixture("cp-06-postmessage.html")
        self.assertTrue(
            any(
                isinstance(node, EmbedNode) and node.provider == "steam"
                for node in embed_result.content.elements
            )
        )

        video_result = self._parse_container_fixture("cp-08-postmessage.html")
        self.assertTrue(
            any(
                isinstance(node, EmbedNode) and node.provider in {"bilibili", "video"}
                for node in video_result.content.elements
            )
        )

        style_result = self._parse_container_fixture("cp-10-postmessage.html")
        self.assertTrue(
            any(isinstance(node, TextElement) and node.bold for node in style_result.content.elements)
        )
        self.assertTrue(
            any(
                isinstance(node, TextElement) and node.underline
                for node in style_result.content.elements
            )
        )
        self.assertTrue(
            any(isinstance(node, QuoteElement) for node in style_result.content.elements)
        )

        image_result = self._parse_container_fixture("cp-13-postmessage.html")
        self.assertEqual(
            image_result.content.media_urls(),
            ("https://blob.keylol.com/forum/201709/09/021527ox3x4x35zb3d3x35.jpg",),
        )

    def test_parser_collapses_steam_widget_auxiliary_links(self):
        result = self._parse_container_fixture("cp-06-postmessage.html")

        steam_embeds = [
            node
            for node in result.content.elements
            if isinstance(node, EmbedNode) and node.provider == "steam"
        ]
        noisy_texts = {
            "Steam商店",
            "Steam评测区",
            "其乐相关帖",
            "SteamDB",
            "AStats",
            "SCE",
            "Barter",
            "Steam客户端中查看",
            "入库或安装",
            "复制ASF代码",
            "蒸汽平台商店",
            "蒸汽平台评测区",
        }

        self.assertEqual(len(steam_embeds), 3)
        self.assertFalse(
            any(
                isinstance(node, LinkElement) and node.text in noisy_texts
                for node in result.content.elements
            )
        )

    def test_extractor_preserves_paginated_fragments_and_container_kind(self):
        html = """
        <html><body>
        <a id="thread_subject">分页测试</a>
        <div id="postlist">
          <div id="post_123">
            <table>
              <tr>
                <td class="pls"><a class="xw1">测试作者</a></td>
                <td id="postmessage_123">
                  第 1 页正文
                  <div class="keylol-page-break" data-keylol-cp="2"><br/><br/></div>
                  <div class="keylol-page-fragment" data-keylol-cp="2" data-keylol-container-kind="postmessage">
                    <p>第 2 页正文</p>
                  </div>
                  <div class="keylol-page-break" data-keylol-cp="3"><br/><br/></div>
                  <div class="keylol-page-fragment" data-keylol-cp="3" data-keylol-container-kind="postpw">
                    <p>第 3 页密码内容</p>
                  </div>
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

        self.assertEqual(raw.container_kind, "postmessage")
        self.assertEqual([fragment.page_number for fragment in raw.fragments], [1, 2, 3])
        self.assertEqual(raw.fragments[0].container_kind, "postmessage")
        self.assertEqual(raw.fragments[2].container_kind, "postpw")
        self.assertIn("第 1 页正文", raw.fragments[0].html)
        self.assertIn("第 2 页正文", raw.fragments[1].html)
        self.assertIn("第 3 页密码内容", raw.fragments[2].html)

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
        self.assertEqual(payload.parse_mode, "html")
        self.assertIn('<a href="https://keylol.com/t1009483-1-1">查看原帖</a>', payload.text)

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
