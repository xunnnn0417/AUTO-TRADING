"""Important people are listed (not pushed); published news is kept a week."""
import unittest
from datetime import datetime, timedelta, timezone

from trading_helper.calendar_events import Announcement, keep_recent_news
from trading_helper.news_relevance import assess_headline


class ImportantPeopleTests(unittest.TestCase):
    def test_people_news_is_listed_but_not_pushed(self):
        for title in ('深圳APEC｜特朗普：期待與習近平和普京會晤',
                      '黃仁勳：AI 需求仍然非常強勁',
                      'Jensen Huang says demand for chips remains strong'):
            result = assess_headline(title)
            self.assertTrue(result.notify, title)
            self.assertFalse(result.push, title)
            self.assertEqual(result.category, '重要人物')

    def test_policy_and_conflict_news_still_push(self):
        self.assertTrue(assess_headline('特朗普宣布加徵關稅').push)
        self.assertTrue(assess_headline('伊朗導彈襲擊美軍基地').push)

    def test_unrelated_news_stays_hidden(self):
        self.assertFalse(assess_headline('本港今日天氣晴朗').notify)


class RetentionTests(unittest.TestCase):
    def test_headlines_dropped_by_the_feed_are_kept_for_a_week(self):
        now = datetime(2026, 11, 24, tzinfo=timezone.utc)
        old = Announcement(now - timedelta(days=3), 'RTHK', '三天前')
        expired = Announcement(now - timedelta(days=8), 'RTHK', '八天前')
        fresh = [Announcement(now - timedelta(hours=1), 'RTHK', '一小時前')]
        kept = keep_recent_news([old, expired], fresh, now)
        self.assertEqual([item.title for item in kept], ['一小時前', '三天前'])


if __name__ == '__main__':
    unittest.main()
