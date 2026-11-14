"""The four user-editable settings belong to the selected sheet, not profiles."""
from dataclasses import dataclass
import re

from .models import ValidationError


# Labels are concise; confirmation text retains the effect of enabling each rule.
TRADE_RULES = {
    "C2": ("來回打", "請先確認目前階段允許來回打。", "將以不來回打的方式計算。"),
    "B6": ("最小交易日目標", "獲利目標改成最小交易日限額，請先確認考試商規則。", "獲利目標恢復表格原本的計算方式。"),
    "E14": ("固定場內止盈", "場內止盈不隨虧損放大。", "場內止盈可隨虧損放大。"),
}
SETTINGS_CELLS = ("A4", *TRADE_RULES)


@dataclass(frozen=True)
class TradeSheetSettings:
    stage: str
    stage_options: tuple[str, ...]
    rules: dict[str, bool]


def _range_size(reference: str) -> int:
    """Only resolve a bounded ordinary range from this workbook's validation."""
    match = re.fullmatch(
        r"(?:(?:'(?:[^']|'')+'|[^'!=]+)!)?\$?([A-Z]{1,3})\$?([1-9][0-9]*)"
        r"(?::\$?([A-Z]{1,3})\$?([1-9][0-9]*))?", reference,
    )
    if not match:
        raise ValidationError("階段下拉來源無法辨識，請在試算表確認。")
    def column(text):
        value = 0
        for letter in text:
            value = value * 26 + ord(letter) - ord("A") + 1
        return value
    first, row, last, end = match.groups()
    width = column(last or first) - column(first) + 1
    height = int(end or row) - int(row) + 1
    if width < 1 or height < 1 or width * height > 200:
        raise ValidationError("階段下拉來源超出可讀範圍，請在試算表確認。")
    return width * height


def read_trade_settings(reader, config: dict) -> TradeSheetSettings:
    if config.get("mode") != "service_account" or config.get("data_layout") != "cells":
        raise ValidationError("階段與交易規則需要可寫入的儲存格模式。")
    worksheet = reader._open_gspread_worksheet(config)
    quoted = "'" + worksheet.title.replace("'", "''") + "'"
    metadata = reader._run_gspread(lambda: worksheet.spreadsheet.fetch_sheet_metadata(params={
        "ranges": [f"{quoted}!{cell}" for cell in SETTINGS_CELLS],
        "includeGridData": "true",
        "fields": "sheets(properties(sheetId),data(startRow,startColumn,rowData(values(formattedValue,userEnteredValue,dataValidation))))",
    }))
    cells = {}
    for sheet in metadata.get("sheets", []):
        if sheet.get("properties", {}).get("sheetId") != worksheet.id:
            continue
        for block in sheet.get("data", []):
            for row_index, row in enumerate(block.get("rowData", []), block.get("startRow", 0)):
                for col_index, value in enumerate(row.get("values", []), block.get("startColumn", 0)):
                    cells[(row_index, col_index)] = value
    references = {"A4": (3, 0), "C2": (1, 2), "B6": (5, 1), "E14": (13, 4)}
    values = {}
    for ref, position in references.items():
        cell = cells.get(position, {})
        if "formulaValue" in cell.get("userEnteredValue", {}):
            raise ValidationError(f"{ref} 是公式，不會覆寫；請確認試算表設定。")
        values[ref] = str(cell.get("formattedValue", "")).strip()
    stage_rule = cells.get((3, 0), {}).get("dataValidation", {}).get("condition", {})
    listed = [str(v.get("userEnteredValue", "")) for v in stage_rule.get("values", [])]
    if stage_rule.get("type") == "ONE_OF_LIST":
        options = listed
    elif stage_rule.get("type") == "ONE_OF_RANGE" and len(listed) == 1:
        reference = listed[0].removeprefix("=")
        _range_size(reference)
        if "!" not in reference:
            reference = quoted + "!" + reference
        rows = reader._run_gspread(lambda: worksheet.spreadsheet.values_get(reference)).get("values", [])
        options = [str(value) for row in rows for value in row]
    else:
        raise ValidationError("A4 尚未設定可辨識的階段下拉選項。")
    stages = tuple(dict.fromkeys(value.strip() for value in options if value.strip()))
    if not stages or (values["A4"] and values["A4"] not in stages):
        raise ValidationError("目前階段與下拉選項不符，請重新讀取試算表。")
    rules = {}
    for ref in TRADE_RULES:
        condition = cells.get(references[ref], {}).get("dataValidation", {}).get("condition", {})
        allowed = {v.get("userEnteredValue") for v in condition.get("values", [])}
        if condition.get("type") != "ONE_OF_LIST" or allowed != {"是", "否"} or values[ref] not in allowed:
            raise ValidationError(f"{ref} 不是「是／否」選項，請確認試算表。")
        rules[ref] = values[ref] == "是"
    return TradeSheetSettings(values["A4"], stages, rules)


def write_trade_setting(reader, config: dict, expected: TradeSheetSettings,
                        cell: str, value: str | bool) -> TradeSheetSettings:
    """One explicit UI approval writes one cell; never blindly retry/restore."""
    if cell not in SETTINGS_CELLS:
        raise ValidationError("不支援的交易設定。")
    current = read_trade_settings(reader, config)
    if current != expected:
        raise ValidationError("表格設定已改變，請重新讀取後再調整。")
    if cell == "A4":
        if not isinstance(value, str) or value not in current.stage_options:
            raise ValidationError("請選擇表格提供的階段。")
        written = value
        original = current.stage
    else:
        if not isinstance(value, bool):
            raise ValidationError("交易規則必須選擇啟用或關閉。")
        written = "是" if value else "否"
        original = "是" if current.rules[cell] else "否"
    if written == original:
        return current
    reader.write_a1_values(config, {cell: written})
    fresh = read_trade_settings(reader, config)
    observed = fresh.stage if cell == "A4" else ("是" if fresh.rules[cell] else "否")
    if observed != written:
        raise ValidationError("設定已送出但讀回不符，請重新讀取確認；不會再次寫入。")
    return fresh
