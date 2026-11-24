"""Event-vs-price recap decisions; examples are synthetic, not trading signals."""
import unittest
from trading_helper.news_relevance import assess_headline, highlight_title


class NewsRelevanceTests(unittest.TestCase):
    def test_actual_price_recaps_do_not_generate_alerts(self):
        for title in ('金價曾跌逾1%　創逾1年新低', '金價升0.04%',
                      '美元指數創逾1年半新高　美債孳息率向下',
                      '油價急挫逾3%　憂慮重新出現供應過剩',
                      'Gold rises 1% as dollar weakens'):
            with self.subTest(title=title):
                item = assess_headline(title)
                self.assertFalse(item.notify)
                self.assertEqual(item.category, '行情回顧')

    def test_specific_potential_catalysts_and_context_are_kept(self):
        for title in ('特朗普宣布對進口商品加徵關稅', '川普稱將提高關稅',
                      '美國財長突然辭職', '英國首相宣布辭職',
                      '美國CPI高於預期', '日本首相呼籲央行不要快速升息',
                      '加拿大央行總裁突然宣布辭職　明年6月生效',
                      '以色列宣布對伊朗發動空襲', '中東停火協議正式生效',
                      '美軍襲擊武裝組織基地', '伊朗稱運油輪遇襲',
                      '美國大型銀行倒閉　央行緊急介入',
                      'Trump announces new tariffs', 'Fed chair resigns unexpectedly',
                      'FOMC statement', 'Interest rate decision',
                      '金價升1%　特朗普宣布加徵關稅'):
            with self.subTest(title=title):
                self.assertTrue(assess_headline(title).notify)

    def test_low_context_important_statement_is_explicitly_unconfirmed(self):
        item = assess_headline('特朗普突然發表重大聲明')
        self.assertTrue(item.notify)
        self.assertEqual(item.category, '待確認')
        self.assertFalse(assess_headline('足球隊教練宣布辭職').notify)
        self.assertFalse(assess_headline('特朗普稱喜歡高爾夫球').notify)
        self.assertFalse(assess_headline('加拿大央行總裁明年6月卸任').notify)
        self.assertEqual(assess_headline('消息指美國財長可能辭職').category, '待確認')
        self.assertFalse(assess_headline('分析師料特朗普將加徵關稅').notify)

    def test_scheduled_titles_are_labeled_and_highlighting_escapes_html(self):
        self.assertEqual(assess_headline('Core CPI m/m', scheduled=True).category, '通膨數據')
        self.assertEqual(assess_headline('Non-Farm Employment Change', scheduled=True).category, '就業數據')
        self.assertFalse(assess_headline('CPI', scheduled=True).notify)
        result = highlight_title('<img src=x> 美國CPI & 利率', '#edc779')
        self.assertNotIn('<img', result)
        self.assertIn('&lt;img', result)
        self.assertIn('CPI</span>', result)
