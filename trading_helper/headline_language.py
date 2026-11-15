"""Chinese labels and optional translation of public headlines only."""
import html
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen


EVENT_LABELS = {
    'Non-Farm Employment Change': '非農就業人數變化',
    'Unemployment Rate': '失業率', 'Unemployment Claims': '初領失業救濟金人數',
    'Federal Funds Rate': '美國聯邦基金利率', 'FOMC Statement': '聯準會利率聲明',
    'FOMC Press Conference': '聯準會記者會', 'FOMC Meeting Minutes': '聯準會會議紀錄',
    'Fed Chair Powell Speaks': '聯準會主席鮑威爾講話',
    'CPI': '消費者物價指數（CPI）', 'Core CPI': '核心消費者物價指數（CPI）',
    'PPI': '生產者物價指數（PPI）', 'Core PPI': '核心生產者物價指數（PPI）',
    'Core PCE Price Index': '核心個人消費支出物價指數（PCE）',
    'Retail Sales': '零售銷售', 'Core Retail Sales': '核心零售銷售',
    'Average Hourly Earnings': '平均時薪', 'ADP Non-Farm Employment Change': 'ADP 非農就業人數變化',
    'ISM Manufacturing PMI': 'ISM 製造業採購經理人指數',
    'ISM Services PMI': 'ISM 服務業採購經理人指數',
    'Flash Manufacturing PMI': '製造業採購經理人指數初值',
    'Flash Services PMI': '服務業採購經理人指數初值',
    'Prelim UoM Consumer Sentiment': '密西根大學消費者信心初值',
    'GDP': '國內生產毛額（GDP）', 'Advance GDP': 'GDP 初值', 'Prelim GDP': 'GDP 修正值',
    'JOLTS Job Openings': 'JOLTS 職位空缺', 'Cash Rate': '央行現金利率',
    'Interest Rate Decision': '央行利率決議', 'Monetary Policy Statement': '央行貨幣政策聲明',
}


def local_title(title):
    if title in EVENT_LABELS:
        return EVENT_LABELS[title]
    for suffix, translated in ((' m/m', '月增率'), (' y/y', '年增率'), (' q/q', '季增率')):
        if title.endswith(suffix) and title[:-len(suffix)] in EVENT_LABELS:
            return EVENT_LABELS[title[:-len(suffix)]] + '・' + translated
    return title


def valid_translation(original, translated):
    return (isinstance(translated, str) and 0 < len(translated) <= 600
            and re.search(r'[\u3400-\u9fff]', translated) is not None
            and sorted(re.findall(r'\d+(?:[.,]\d+)*', original)) ==
                sorted(re.findall(r'\d+(?:[.,]\d+)*', translated)))


def translate_title(title):
    # The documented anonymous GET endpoint, never TM contribution/set APIs.
    if len(title.encode('utf-8')) > 500:
        return None
    url = 'https://api.mymemory.translated.net/get?' + urlencode({'q': title, 'langpair': 'en|zh-TW'})
    try:
        with urlopen(Request(url, headers={'User-Agent': 'TradingWorkflowHelper/0.1'}), timeout=4) as response:
            raw = response.read(32_001)
        if len(raw) > 32_000:
            return None
        payload = json.loads(raw)
        translated = html.unescape(payload.get('responseData', {}).get('translatedText', '')).strip()
        if payload.get('responseStatus') == 200 and valid_translation(title, translated):
            return translated
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None
