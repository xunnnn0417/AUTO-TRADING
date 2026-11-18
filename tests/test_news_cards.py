"""The same rich list renders source-safe cards in both message surfaces."""
import unittest
from datetime import datetime
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from trading_helper.calendar_events import UTC, parse_market_news
from trading_helper.news_cards import NewsCards


class NewsCardTests(unittest.TestCase):
    def test_published_result_and_per_event_details_are_source_text_only(self):
        view = NewsCards()
        self.addCleanup(view.close)
        now = datetime.now(UTC)
        view.set_entries([(now, '來源', 'CPI', 'CPI', True, '已公布', '公布值：2.4%　預期：2.5%'),
                          (now, '來源', 'GDP', 'GDP', True, '已公布', '')], '')
        self.assertIn('公布值：2.4%', view.text())
        view.anchorClicked.emit(QUrl('detail:1'))
        self.assertIn('來源尚未提供公布結果', view.text())
        self.assertEqual(view.toolTip(), '')
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_stripe_headline_and_original_detail_keep_source_text_safe(self):
        view = NewsCards()
        self.addCleanup(view.close)
        now = datetime.now(UTC)
        original = '<img src="file:///secret"> Trump announces tariffs'
        view.set_entries([(now, '來源 <b>X</b>', original, '特朗普宣布加徵關稅', False, '已公布')], '')
        self.assertIn('政策事件', view.text())
        self.assertIn('特朗普宣布加徵關稅', view.text())
        self.assertIn('查看原文', view.text())
        self.assertNotIn('file:///secret', view.toHtml())
        view.anchorClicked.emit(QUrl('detail:0'))
        self.assertIn(original, view.text())
        self.assertNotIn('<img src=', view.toHtml())
        self.assertIsNone(view.loadResource(2, QUrl('file:///secret')))
        view.anchorClicked.emit(QUrl('https://example.org'))
        self.assertIn('收起原文', view.text())
        view.anchorClicked.emit(QUrl('detail:0'))
        self.assertNotIn(original, view.text())

    def test_personnel_event_is_retained_even_without_old_market_keywords(self):
        raw = '<rss><channel><item><title>美國財長突然辭職</title><pubDate>Tue, 17 Nov 2026 00:00:00 GMT</pubDate></item></channel></rss>'.encode()
        self.assertEqual(len(parse_market_news(raw, '香港電台國際')), 1)

    def test_compact_sidebar_uses_smaller_type_and_less_height_without_losing_text(self):
        regular, compact = NewsCards(), NewsCards(compact=True)
        self.addCleanup(regular.close)
        self.addCleanup(compact.close)
        title = '特朗普宣布對進口商品加徵關稅'
        rows = [(datetime.now(UTC), '香港電台國際', title, title, False, '已公布')]*3
        for view in (regular, compact):
            view.resize(370, 450)
            view.show()
            view.set_entries(rows, '')
        self.app.processEvents()
        regular_size = regular.document().find(title).charFormat().font().pixelSize()
        compact_size = compact.document().find(title).charFormat().font().pixelSize()
        self.assertGreater(compact_size, 0)
        self.assertLess(compact_size, regular_size)
        self.assertLess(compact.document().size().height(), regular.document().size().height())
        self.assertEqual(compact.text(), regular.text())
