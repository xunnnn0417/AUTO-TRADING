"""The same rich list renders source-safe cards in both message surfaces."""
import unittest
from datetime import datetime
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from trading_helper.calendar_events import UTC, parse_market_news
from trading_helper.news_cards import NewsCards


class NewsCardTests(unittest.TestCase):
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
