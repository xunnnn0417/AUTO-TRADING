"""Conservative headline evidence, not a prediction of gold price direction."""
from dataclasses import dataclass
from html import escape
import re


@dataclass(frozen=True)
class NewsAssessment:
    category: str
    color: str
    notify: bool = False   # shown in the news lists
    alert: bool | None = None  # pop-up / phone push; defaults to `notify`

    @property
    def push(self) -> bool:
        return self.notify if self.alert is None else self.alert


def matches(pattern, title):
    return bool(re.search(pattern, title, re.I))


# People whose words alone move gold / the dollar / risk mood. Their news is
# always listed; it only pops up / pushes when it is also a policy, conflict
# or personnel event (handled by the rules above this one).
IMPORTANT_PEOPLE = (
    r'特朗普|川普|Trump|萬斯|范斯|Vance|貝森特|Bessent|盧特尼克|Lutnick|'
    r'鮑威爾|Powell|沃什|Warsh|哈塞特|Hassett|拉加德|Lagarde|植田和男|Ueda|'
    r'習近平|Xi Jinping|普京|普丁|Putin|澤連斯基|Zelensky|內塔尼亞胡|Netanyahu|哈梅內伊|Khamenei|'
    r'黃仁勳|Jensen Huang|馬斯克|Musk|巴菲特|Buffett')
# Market-relevant substance; keeps e.g. a leader's golf remarks out.
_SUBSTANCE = (r'經濟|市場|美元|黃金|金價|油價|貿易|關稅|利率|通脹|通膨|股|債|晶片|芯片|AI|人工智能|需求|'
              r'會晤|會談|峰會|協議|談判|制裁|戰|軍|伊朗|俄|烏克蘭|中東|'
              r'econom|market|dollar|gold|oil|trade|tariff|rate|inflation|stock|chip|demand|deal|talks|summit|war')
_ACTOR = r'特朗普|川普|聯儲|聯準|鮑威爾|央行|總統|首相|總理|財長|財政部長|財務大臣|白宮|Trump|Powell|Fed\b|central bank|president|prime minister|treasury secretary'
_POLICY = r'關稅|制裁|利率|減息|加息|降息|升息|貨幣政策|資本管制|量化寬鬆|tariff|sanction|interest rate|rate cut|rate hike|monetary policy'
_ACTION = r'宣布|決定|實施|生效|加徵|提高|上調|下調|取消|暫停|撤銷|announc|impos|rais|cut|hike|approv|suspend|enact'
_PERSONNEL = r'辭職|請辭|卸任|撤職|解職|遭免職|病逝|身亡|遇刺|resign|step down|dismiss|fired|dies|assassinat'
_GEO = r'中東|伊朗|以色列|烏克蘭|俄羅斯|北韓|台海|海峽|軍事|軍隊|美軍|戰爭|國|首都|Iran|Israel|Ukraine|Russia|military|US forces|war\b|strait'
_CONFLICT = r'空襲|襲擊|遇襲|導彈|飛彈|停火|開戰|宣戰|政變|封鎖|核試|入侵|攻擊|戒嚴|緊急狀態|airstrike|missile|ceasefire|invad|invasion|attack|coup|blockade'
_PRICE = r'金價|黃金|期金|油價|美元指數|美匯|股市|美債|孳息|收益率|gold|oil price|dollar|stock|yield'
_MOVE = r'升|跌|漲|挫|走強|走弱|新高|新低|靠穩|收市|收盤|%|％|rise|rises|fall|falls|gain|drop|high|low|weaken|strengthen'
KEYWORDS = re.compile(
    r'核心\s*CPI|核心\s*PPI|非農就業|消費者物價指數|生產者物價指數|失業率|通脹|通膨|'
    r'關稅|制裁|利率決議|利率|減息|降息|加息|升息|貨幣政策|聯準會|聯儲局|鮑威爾|特朗普|川普|'
    r'辭職|請辭|政變|空襲|導彈|飛彈|停火|封鎖|破產|倒閉|擠提|'
    r'core\s+CPI|CPI|PPI|GDP|PCE|FOMC|non.?farm|employment|interest rate|tariffs?|sanctions?|'
    r'resign\w*|ceasefire|airstrike|Trump|Powell', re.I)


def assess_headline(title: str, *, scheduled=False) -> NewsAssessment:
    if '【測試】' in title:
        return NewsAssessment('測試消息', '#bc9aea', True)
    if scheduled:
        if matches(r'CPI|PPI|PCE|通脹|通膨|物價', title):
            return NewsAssessment('通膨數據', '#edc779')
        if matches(r'non.?farm|employment|job|payroll|就業|非農|失業', title):
            return NewsAssessment('就業數據', '#edc779')
        if matches(r'rate|FOMC|央行|聯準|聯儲|主席|speech|speaks|利率', title):
            return NewsAssessment('央行政策', '#bc9aea')
        return NewsAssessment('經濟排程', '#9ab6d8')
    if matches(r'tentative schedule|banking data|digital euro|supervis|regulat', title):
        return NewsAssessment('一般公告', '#aaa5b7')
    if matches(_ACTOR, title) and matches(_PERSONNEL, title):
        if matches(r'否認|傳聞|傳出|據報|消息指|rumou?r|reportedly|denies', title):
            return NewsAssessment('待確認', '#edc779', True)
        planned = (matches(r'明年|下年|下月|將於|next year|next month', title)
                   and not matches(r'突然|宣布辭職|請辭|unexpected', title))
        return NewsAssessment('人事動態', '#f38caa', not planned)
    if matches(_GEO, title) and matches(_CONFLICT, title):
        return NewsAssessment('地緣事件', '#f38caa', True)
    if matches(r'銀行|金融|bank|financial', title) and matches(r'倒閉|破產|擠提|緊急介入|bailout|collapse|bankrupt|bank run', title):
        return NewsAssessment('金融風險', '#f38caa', True)
    if matches(r'市場預期|市場料|分析師|專家預計|analysts? (expect|predict|forecast)', title):
        return NewsAssessment('分析觀點', '#aaa5b7')
    if ((matches(_POLICY, title) and matches(_ACTION, title))
            or matches(r'FOMC statement|interest rate decision|利率決議|央行會議紀錄|聯準會會議紀錄', title)):
        return NewsAssessment('政策事件', '#bc9aea', True)
    if (matches(_ACTOR, title) and matches(r'稱|表示|警告|呼籲|承諾|揚言|暗示|重申|強調|發言|講話|談話|記者會|says|warns|speech|testimony', title)
            and matches(_POLICY+r'|通脹|通膨|經濟|美元|黃金|貿易|inflation|economy|dollar|gold|trade', title)):
        return NewsAssessment('重要發言', '#bc9aea', True)
    if (matches(r'CPI|PPI|PCE|GDP|通脹|通膨|非農|失業率|就業數據', title)
            and matches(r'已公布|數據顯示|意外|高於預期|低於預期|超預期|升至|降至|unexpected|above forecast|below forecast', title)):
        return NewsAssessment('經濟數據', '#edc779', True)
    if matches(_PRICE, title) and matches(_MOVE, title):
        return NewsAssessment('行情回顧', '#aaa5b7')
    if (matches(IMPORTANT_PEOPLE, title) and matches(_SUBSTANCE, title)
            and not matches(r'突然|緊急|重大聲明|unexpected|breaking|emergency', title)):
        return NewsAssessment('重要人物', '#bc9aea', True, alert=False)
    if ((matches(_ACTOR, title) and matches(r'突然|緊急|重大聲明|unexpected|breaking|emergency', title))
            or matches(r'\b(inflation|employment)\b', title)):
        return NewsAssessment('待確認', '#edc779', True)
    return NewsAssessment('相關動態', '#aaa5b7')


def highlight_title(title: str, color: str) -> str:
    # Every source fragment is escaped before adding our own fixed markup.
    result, end = [], 0
    safe_color = color if re.fullmatch(r'#[0-9a-fA-F]{6}', color) else '#edc779'
    for match in KEYWORDS.finditer(title):
        result.extend((escape(title[end:match.start()]),
                       f'<span style="color:{safe_color};font-weight:500">{escape(match.group())}</span>'))
        end = match.end()
    return ''.join(result)+escape(title[end:])
