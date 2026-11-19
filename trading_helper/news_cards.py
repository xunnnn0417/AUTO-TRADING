"""Shared category stripe, time column and headline-first event list."""
from html import escape

from PySide6.QtCore import Qt, QUrl, QPointF
from PySide6.QtWidgets import QApplication, QFrame, QTextBrowser

from .calendar_events import TAIPEI, publication_values
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
        self._press_position = None
        self.anchorClicked.connect(self._toggle_details)

    def mousePressEvent(self, event):
        self._press_position = (event.position().toPoint(), bool(self.anchorAt(event.position().toPoint())))
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        press, self._press_position = self._press_position, None
        super().mouseReleaseEvent(event)
        if (event.button() != Qt.LeftButton or press is None or press[1]
                or self.textCursor().hasSelection()
                or (event.position().toPoint()-press[0]).manhattanLength() >= QApplication.startDragDistance()):
            return
        point = QPointF(event.position())
        point += QPointF(self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        for index, frame in enumerate(self.document().rootFrame().childFrames()):
            if self.document().documentLayout().frameBoundingRect(frame).contains(point):
                self._toggle_details(QUrl(f'detail:{index}'))
                return

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
        time_width = 64 if self.compact else 70
        gutter = 8 if self.compact else 10
        headline_size = 12 if self.compact else 13
        title_margin = 3 if self.compact else 5
        time_style = 'font-size:11px;' if self.compact else ''
        spacer = ('<p style="margin:0;font-size:4px"><br></p>' if self.compact
                  else '<p style="margin:0;font-size:7px"><br></p>')
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
            values = publication_values(content) if scheduled else {}
            cells = [f'<td><span style="color:#aaa5b7;font-size:11px">{label}</span><br>'
                     f'<span style="color:#eeedf3;font-size:12px">{escape(values[key])}</span></td>'
                     for key,label in (('actual','公布值'),('forecast','預期'),('previous','前值'))
                     if key in values]
            result = ('<table width="100%" cellpadding="3" cellspacing="0"><tr>'
                      + ''.join(cells)+'</tr></table>') if cells else (
                      f'<p style="margin:4px 0;color:#edc779;font-size:11px">{escape(content)}</p>'
                      if content and scheduled and state == '已公布' else '')
            # Full source title is retained; no invented AI summary or direction.
            cards.append(
                f'<table width="100%" cellspacing="0" cellpadding="0"><tr>'
                f'<td width="3" bgcolor="{color}"></td><td width="{gutter}"></td>'
                f'<td width="{time_width}" valign="top" style="white-space:nowrap"><span style="color:#eeedf3;{time_style}">{when.astimezone(TAIPEI):%m/%d}</span>'
                f'<br><span style="color:#aaa5b7;{time_style}">{when.astimezone(TAIPEI):%H:%M}<br>{escape(state)}</span></td>'
                f'<td valign="top"><p style="margin:0;color:{color};font-size:11px">{escape(assessment.category)}</p>'
                f'<p style="margin:{title_margin}px 0;font-size:{headline_size}px">{highlight_title(shown, color)}</p>{result}'
                f'<span style="color:#aaa5b7;font-size:11px">{escape(source)}</span>　'
                f'<a href="detail:{index}" style="color:#aaa5b7;text-decoration:none;font-size:11px">'
                f'{"收起原文" if opened else "查看原文"}</a>{details}</td></tr></table>{spacer}')
        self.setHtml(''.join(cards) if cards else f'<p style="color:#aaa5b7">{escape(self._empty)}</p>')
        self.verticalScrollBar().setValue(old_scroll)
