"""Shared category stripe, time column and headline-first event list."""
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QTextBrowser

from .calendar_events import TAIPEI
from .news_relevance import assess_headline, highlight_title


class NewsCards(QTextBrowser):
    def __init__(self, *, compact=False):
        super().__init__()
        self.compact = compact
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().setDocumentMargin(2 if compact else 4)
        self.setStyleSheet('QTextBrowser { border:0; background:transparent; color:#eeedf3; }')
        self._rows = []
        self._open_details = set()
        self.anchorClicked.connect(self._toggle_details)

    def loadResource(self, resource_type, url):
        return None  # Feed titles cannot load files, images or remote resources.

    def text(self):
        return self.toPlainText()

    def set_entries(self, rows, empty):
        # Stable identity keeps expansion across refresh; titles are never HTML.
        self._rows = rows
        self._empty = empty
        self._render()

    def _toggle_details(self, url):
        if url.scheme() != 'detail' or not url.path().isdigit():
            return
        index = int(url.path())
        if index >= len(self._rows):
            return
        identity = self._rows[index][:3]
        self._open_details.symmetric_difference_update({identity})
        self._render()

    def _render(self):
        old_scroll = self.verticalScrollBar().value()
        valid = {row[:3] for row in self._rows}
        self._open_details.intersection_update(valid)
        cards = []
        time_width = 54 if self.compact else 70
        gutter = 8 if self.compact else 10
        headline_size = 12 if self.compact else 14
        title_margin = 3 if self.compact else 5
        time_style = 'font-size:11px;' if self.compact else ''
        spacer = ('<p style="margin:0;font-size:6px"><br></p>' if self.compact
                  else '<p style="margin:0;height:14px"><br></p>')
        for index, row in enumerate(self._rows):
            when, source, original, shown, scheduled, state = row[:6]
            content = row[6] if len(row) > 6 else ''
            assessment = assess_headline(original, scheduled=scheduled)
            color = assessment.color
            identity = (when, source, original)
            opened = identity in self._open_details
            details = (f'<p style="margin:6px 0 0;color:#aaa5b7">原文：{escape(original)}'
                       + (f'<br>內容：{escape(content)}' if content else
                          '<br>來源尚未提供公布結果。' if scheduled and state == '已公布' else '')
                       + '</p>') if opened else ''
            result = (f'<p style="margin:4px 0;color:#edc779;font-size:11px">{escape(content)}</p>'
                      if content and scheduled and state == '已公布' else '')
            # Full source title is retained; no invented AI summary or direction.
            cards.append(
                f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                f'<td width="3" bgcolor="{color}"></td><td width="{gutter}"></td>'
                f'<td width="{time_width}" valign="top"><span style="color:#eeedf3;{time_style}">{when.astimezone(TAIPEI):%m/%d}</span>'
                f'<br><span style="color:#aaa5b7;{time_style}">{when.astimezone(TAIPEI):%H:%M}<br>{escape(state)}</span></td>'
                f'<td valign="top"><p style="margin:0;color:{color};font-size:11px">{escape(assessment.category)}</p>'
                f'<p style="margin:{title_margin}px 0;font-size:{headline_size}px">{highlight_title(shown, color)}</p>{result}'
                f'<span style="color:#aaa5b7;font-size:11px">{escape(source)}</span>　'
                f'<a href="detail:{index}" style="color:#aaa5b7;text-decoration:none;font-size:11px">'
                f'{"收起原文" if opened else "查看原文"}</a>{details}</td></tr></table>{spacer}')
        self.setHtml(''.join(cards) if cards else f'<p style="color:#aaa5b7">{escape(self._empty)}</p>')
        self.verticalScrollBar().setValue(old_scroll)
