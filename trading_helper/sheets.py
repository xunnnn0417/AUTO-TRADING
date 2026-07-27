from __future__ import annotations

import csv
import io
import re
import time
import urllib.parse
import urllib.request
from typing import Any

from .models import TradeInstruction, ValidationError


def _column_index(reference: object, headers: list[str]) -> int:
    text = str(reference).strip()
    if not text:
        raise ValidationError("試算表欄位對應不可空白。")
    for index, header in enumerate(headers):
        if header.strip().casefold() == text.casefold():
            return index
    if text.isdigit():
        return int(text) - 1
    if re.fullmatch(r"[A-Za-z]+", text):
        result = 0
        for char in text.upper():
            result = result * 26 + ord(char) - 64
        return result - 1
    raise ValidationError(f"標題列找不到欄位「{text}」。")


def _cell_position(reference: object) -> tuple[int, int]:
    text = str(reference).strip().upper()
    match = re.fullmatch(r"([A-Z]+)([1-9][0-9]*)", text)
    if not match:
        raise ValidationError(f"儲存格位置「{text}」無效，請使用例如 B5 的格式。")
    column = 0
    for char in match.group(1):
        column = column * 26 + ord(char) - 64
    return int(match.group(2)) - 1, column - 1


def _a1_notation(row_index: int, column_index: int) -> str:
    column = column_index + 1
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row_index + 1}"


def _cell_or_literal(
    rows: list[list[str]], reference: object, *, allow_literal: bool
) -> tuple[object, int | None]:
    text = str(reference).strip()
    try:
        row_index, column_index = _cell_position(text)
    except ValidationError:
        if allow_literal:
            return text, None
        raise
    value = (
        rows[row_index][column_index]
        if row_index < len(rows) and column_index < len(rows[row_index])
        else ""
    )
    return value, row_index + 1


def _csv_export_url(url: str, gid: str) -> str:
    match = re.search(r"/spreadsheets/d/([^/]+)", url)
    if not match:
        raise ValidationError("試算表網址不是有效的 Google 試算表網址。")
    return (
        f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export"
        f"?format=csv&gid={urllib.parse.quote(str(gid))}"
    )


class SheetReader:
    def __init__(self) -> None:
        self._worksheet_cache: dict[tuple[str, str, str], Any] = {}

    def read(self, config: dict[str, Any]) -> TradeInstruction:
        rows = self._fetch_rows(config)
        if not rows:
            raise ValidationError("工作表沒有資料。")
        if config.get("data_layout", "row") == "cells":
            return self._read_cells(rows, config)
        if len(rows) < 2:
            raise ValidationError("工作表沒有資料列。")
        headers = rows[0]
        row_number, row = self._select_row(rows, headers, config)
        columns = config["columns"]
        defaults = config.get("defaults", {})
        mapped: dict[str, object] = {}
        for field, reference in columns.items():
            try:
                index = _column_index(reference, headers)
                mapped[field] = row[index] if index < len(row) else ""
            except ValidationError:
                if field in {"point_size", "price_digits"}:
                    mapped[field] = defaults.get(field, "")
                elif field in {
                    "estimated_price",
                    "internal_entry_price",
                    "final_external_sl_price",
                    "final_external_tp_price",
                    "daily_pnl",
                    "internal_balance",
                    "original_sl_points",
                    "expected_sl_points",
                    "expected_sl_percent",
                }:
                    mapped[field] = ""
                else:
                    raise
        if not mapped.get("point_size"):
            mapped["point_size"] = defaults.get("point_size", "0.0001")
        if not mapped.get("price_digits"):
            mapped["price_digits"] = defaults.get("price_digits", "5")
        return TradeInstruction.from_mapping(row_number, mapped)

    def _read_cells(
        self, rows: list[list[str]], config: dict[str, Any]
    ) -> TradeInstruction:
        defaults = config.get("defaults", {})
        optional = {
            "status",
            "estimated_price",
            "internal_entry_price",
            "final_external_sl_price",
            "final_external_tp_price",
            "daily_pnl",
            "internal_balance",
            "original_sl_points",
            "expected_sl_points",
            "expected_sl_percent",
        }
        mapped: dict[str, object] = {}
        source_rows: list[int] = []
        literal_allowed = {
            "status",
            "symbol",
            "direction",
            "estimated_price",
            "point_size",
            "price_digits",
        }
        for field, reference in config["columns"].items():
            if not str(reference).strip():
                if field in {"point_size", "price_digits"}:
                    mapped[field] = defaults.get(field, "")
                    continue
                if field in optional:
                    mapped[field] = ""
                    continue
                raise ValidationError(f"{field} 尚未設定儲存格位置。")
            try:
                value, source_row = _cell_or_literal(
                    rows,
                    reference,
                    allow_literal=field in literal_allowed,
                )
            except ValidationError:
                if field in {"point_size", "price_digits"}:
                    mapped[field] = defaults.get(field, "")
                    continue
                if field in optional:
                    mapped[field] = ""
                    continue
                raise
            if source_row is not None:
                source_rows.append(source_row)
            elif field == "estimated_price":
                try:
                    float(str(value).replace(",", ""))
                except ValueError:
                    value = ""
            elif field == "point_size":
                try:
                    float(str(value).replace(",", ""))
                except ValueError:
                    value = defaults.get("point_size", "0.0001")
            elif field == "price_digits":
                if not str(value).isdigit():
                    value = defaults.get("price_digits", "5")
            mapped[field] = value
        if not mapped.get("point_size"):
            mapped["point_size"] = defaults.get("point_size", "0.0001")
        if not mapped.get("price_digits"):
            mapped["price_digits"] = defaults.get("price_digits", "5")
        return TradeInstruction.from_mapping(min(source_rows, default=1), mapped)

    def _fetch_rows(self, config: dict[str, Any]) -> list[list[str]]:
        mode = config.get("mode", "csv")
        if mode == "service_account":
            return self._fetch_gspread(config)
        url = config.get("spreadsheet_url", "").strip()
        if not url:
            raise ValidationError("請先在試算表設定中填入 Google 試算表網址。")
        request = urllib.request.Request(
            _csv_export_url(url, config.get("gid", "0")),
            headers={"User-Agent": "TradingWorkflowHelper/0.1"},
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                text = response.read().decode("utf-8-sig")
        except Exception as exc:
            raise ValidationError(
                "無法以 CSV 讀取試算表。請開啟連結存取權限，或改用服務帳戶模式。"
            ) from exc
        return list(csv.reader(io.StringIO(text)))

    def _fetch_gspread(self, config: dict[str, Any]) -> list[list[str]]:
        worksheet = self._open_gspread_worksheet(config)
        return self._run_gspread(lambda: worksheet.get_all_values())

    def _open_gspread_worksheet(self, config: dict[str, Any]):
        try:
            import gspread
        except ImportError as exc:
            raise ValidationError("請先安裝必要套件，才能使用服務帳戶模式。") from exc
        credential_file = config.get("service_account_file", "").strip()
        if not credential_file:
            raise ValidationError("必須提供服務帳戶 JSON 檔案路徑。")
        cache_key = (
            credential_file,
            str(config.get("spreadsheet_url", "")),
            str(config.get("worksheet", "Sheet1")),
        )
        cached = self._worksheet_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            worksheet = self._run_gspread(
                lambda: gspread.service_account(filename=credential_file)
                .open_by_url(config["spreadsheet_url"])
                .worksheet(config.get("worksheet", "Sheet1"))
            )
            self._worksheet_cache[cache_key] = worksheet
            return worksheet
        except Exception as exc:
            raise ValidationError(f"Google 試算表 API 錯誤：{exc}") from exc

    def _run_gspread(self, operation, *, attempts: int = 3):
        last_exc: Exception | None = None
        transient_markers = (
            "RemoteDisconnected",
            "Connection aborted",
            "Connection reset",
            "closed connection",
            "timed out",
            "timeout",
            "temporarily unavailable",
            "429",
            "500",
            "502",
            "503",
            "504",
        )
        for attempt in range(attempts):
            try:
                return operation()
            except Exception as exc:  # pragma: no cover - network dependent
                last_exc = exc
                message = repr(exc)
                if attempt >= attempts - 1 or not any(
                    marker in message for marker in transient_markers
                ):
                    raise
                time.sleep(0.35 * (attempt + 1))
        if last_exc is not None:
            raise last_exc

    def resolve_field_targets(
        self,
        config: dict[str, Any],
        fields: list[str],
        *,
        source_row: int | None = None,
    ) -> dict[str, str]:
        if config.get("mode") != "service_account":
            raise ValidationError("此功能需要 service_account 讀取模式。")
        worksheet = self._open_gspread_worksheet(config)
        rows: list[list[str]] | None = None
        if config.get("data_layout", "row") != "cells":
            rows = self._run_gspread(lambda: worksheet.get_all_values())
            if not rows:
                raise ValidationError("試算表沒有可讀取的資料。")
        targets: dict[str, str] = {}
        for field in fields:
            reference = str(config["columns"].get(field, "")).strip()
            if not reference:
                raise ValidationError(f"{field} 尚未設定寫回欄位。")
            targets[field] = self._target_for_reference_from_rows(
                config,
                reference,
                rows,
                source_row=source_row,
            )
        return targets

    def _batch_get_values(self, worksheet, references: list[str]) -> dict[str, str]:
        if not references:
            return {}
        if not hasattr(worksheet, "batch_get"):
            return {
                reference: self._run_gspread(
                    lambda reference=reference: worksheet.acell(reference).value or ""
                )
                for reference in references
            }
        batches = self._run_gspread(lambda: worksheet.batch_get(references))
        values: dict[str, str] = {}
        for reference, matrix in zip(references, batches):
            value = ""
            if matrix and len(matrix) and matrix[0]:
                value = str(matrix[0][0])
            values[reference] = value
        return values

    def _batch_update_values(self, worksheet, values: dict[str, object]) -> None:
        if not values:
            return
        if not hasattr(worksheet, "batch_update"):
            for target, value in values.items():
                self._run_gspread(
                    lambda target=target, value=value: worksheet.update_acell(
                        target, str(value)
                    )
                )
            return
        data = [
            {"range": target, "values": [[str(value)]]}
            for target, value in values.items()
        ]
        self._run_gspread(
            lambda: worksheet.batch_update(data, value_input_option="USER_ENTERED")
        )

    def write_field_values(
        self,
        config: dict[str, Any],
        values: dict[str, object],
        *,
        source_row: int | None = None,
    ) -> dict[str, str]:
        if config.get("mode") != "service_account":
            raise ValidationError("寫回試算表需要 service_account 讀取模式。")
        worksheet = self._open_gspread_worksheet(config)
        targets = self.resolve_field_targets(
            config,
            list(values),
            source_row=source_row,
        )
        self._batch_update_values(
            worksheet,
            {target: values[field] for field, target in targets.items()},
        )
        return targets

    def write_value(
        self,
        config: dict[str, Any],
        field: str,
        value: object,
        *,
        source_row: int | None = None,
    ) -> str:
        if config.get("mode") != "service_account":
            raise ValidationError("寫回試算表需要使用 service_account 讀取模式。")
        reference = str(config["columns"].get(field, "")).strip()
        if not reference:
            raise ValidationError(f"{field} 尚未設定寫回位置。")
        worksheet = self._open_gspread_worksheet(config)
        target = self._target_for_reference(
            worksheet,
            config,
            reference,
            source_row=source_row,
        )
        self._batch_update_values(worksheet, {target: value})
        return target

    def read_field_values(
        self,
        config: dict[str, Any],
        fields: list[str],
        *,
        source_row: int | None = None,
    ) -> dict[str, str]:
        if config.get("mode") != "service_account":
            raise ValidationError("讀取原值需要 service_account 讀取模式。")
        worksheet = self._open_gspread_worksheet(config)
        targets = self.resolve_field_targets(config, fields, source_row=source_row)
        return self._batch_get_values(worksheet, list(targets.values()))

    def read_a1_values(
        self, config: dict[str, Any], references: list[str]
    ) -> dict[str, str]:
        if config.get("mode") != "service_account":
            rows = self._fetch_rows(config)
            values: dict[str, str] = {}
            for reference in references:
                row_index, column_index = _cell_position(reference)
                values[reference] = (
                    rows[row_index][column_index]
                    if row_index < len(rows)
                    and column_index < len(rows[row_index])
                    else ""
                )
            return values
        worksheet = self._open_gspread_worksheet(config)
        return self._batch_get_values(worksheet, references)

    def write_a1_values(
        self, config: dict[str, Any], values: dict[str, str]
    ) -> None:
        if config.get("mode") != "service_account":
            raise ValidationError("寫回試算表需要 service_account 讀取模式。")
        worksheet = self._open_gspread_worksheet(config)
        self._batch_update_values(worksheet, values)

    def _target_for_reference(
        self,
        worksheet,
        config: dict[str, Any],
        reference: str,
        *,
        source_row: int | None = None,
    ) -> str:
        if config.get("data_layout", "row") == "cells":
            row_index, column_index = _cell_position(reference)
        else:
            if source_row is None:
                source_row = max(2, int(config.get("row_number", 2)))
            rows = self._run_gspread(lambda: worksheet.get_all_values())
            if not rows:
                raise ValidationError("工作表沒有標題列，無法寫回。")
            column_index = _column_index(reference, rows[0])
            row_index = source_row - 1
        target = _a1_notation(row_index, column_index)
        return target

    def _target_for_reference_from_rows(
        self,
        config: dict[str, Any],
        reference: str,
        rows: list[list[str]] | None,
        *,
        source_row: int | None = None,
    ) -> str:
        if config.get("data_layout", "row") == "cells":
            row_index, column_index = _cell_position(reference)
        else:
            if source_row is None:
                source_row = max(2, int(config.get("row_number", 2)))
            if not rows:
                raise ValidationError("試算表沒有可讀取的資料。")
            column_index = _column_index(reference, rows[0])
            row_index = source_row - 1
        return _a1_notation(row_index, column_index)

    def _select_row(
        self, rows: list[list[str]], headers: list[str], config: dict[str, Any]
    ) -> tuple[int, list[str]]:
        status_value = str(config.get("status_value", "")).strip()
        if status_value:
            status_ref = config["columns"].get("status", "Status")
            status_index = _column_index(status_ref, headers)
            for row_number, row in enumerate(rows[1:], start=2):
                value = row[status_index].strip() if status_index < len(row) else ""
                if value.casefold() == status_value.casefold():
                    return row_number, row
            raise ValidationError(f"找不到狀態為「{status_value}」的資料列。")
        row_number = max(2, int(config.get("row_number", 2)))
        if row_number > len(rows):
            raise ValidationError(f"第 {row_number} 列不存在。")
        return row_number, rows[row_number - 1]
