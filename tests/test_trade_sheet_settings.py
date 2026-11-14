"""Sheet settings are exercised against bounded, isolated fake workbooks."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from trading_helper.models import ValidationError
from trading_helper.sheet_preferences import read_trade_settings, write_trade_setting


class FakePreferencesReader:
    def __init__(self):
        self.values={"A4":"階段甲","C2":"否","B6":"否","E14":"是"}
        self.stages=["階段甲","", "真金階段"]
        self.writes=[]
        self.formula_cell=None
        self.bad_readback=False
        self.ws=SimpleNamespace(id=42,title="計算區",spreadsheet=SimpleNamespace(
            fetch_sheet_metadata=self.metadata,values_get=self.options))
    def _open_gspread_worksheet(self,config):return self.ws
    def _run_gspread(self,operation):return operation()
    def metadata(self,params):
        assert params['ranges']==["'計算區'!"+c for c in ("A4","C2","B6","E14")]
        blocks=[]
        for ref,(row,col) in {"A4":(3,0),"C2":(1,2),"B6":(5,1),"E14":(13,4)}.items():
            rule=({"type":"ONE_OF_RANGE","values":[{"userEnteredValue":"='階段來源'!$E$1:$E$3"}]}
                  if ref=="A4" else {"type":"ONE_OF_LIST","values":[{"userEnteredValue":"是"},{"userEnteredValue":"否"}]})
            entered={"formulaValue":"=SOME_FORMULA()"} if self.formula_cell==ref else {"stringValue":self.values[ref]}
            blocks.append({"startRow":row,"startColumn":col,"rowData":[{"values":[{
                "formattedValue":self.values[ref],"userEnteredValue":entered,"dataValidation":{"condition":rule}}]}]})
        return {"sheets":[{"properties":{"sheetId":42},"data":blocks}]}
    def options(self,reference):
        assert reference=="'階段來源'!$E$1:$E$3"
        return {"values":[[v] for v in self.stages]}
    def write_a1_values(self,config,values):
        self.writes.append(deepcopy(values))
        if not self.bad_readback:self.values.update(values)


class TradeSheetSettingsTests(unittest.TestCase):
    def setUp(self):
        self.reader=FakePreferencesReader()
        self.config={"mode":"service_account","data_layout":"cells"}
    def read(self):return read_trade_settings(self.reader,self.config)
    def test_reads_actual_stages_and_yes_no_flags_without_writing(self):
        settings=self.read()
        self.assertEqual(settings.stage,"階段甲")
        self.assertEqual(settings.stage_options,("階段甲","真金階段"))
        self.assertEqual(settings.rules,{"C2":False,"B6":False,"E14":True})
        self.assertEqual(self.reader.writes,[])
    def test_each_rule_changes_only_its_cell_then_reads_back(self):
        for cell in ("C2","B6","E14"):
            with self.subTest(cell=cell):
                expected=self.read()
                target=not expected.rules[cell]
                fresh=write_trade_setting(self.reader,self.config,expected,cell,target)
                self.assertEqual(self.reader.writes[-1],{cell:"是" if target else "否"})
                self.assertEqual(fresh.rules[cell],target)
    def test_stage_uses_original_dropdown_and_only_writes_a4(self):
        fresh=write_trade_setting(self.reader,self.config,self.read(),"A4","真金階段")
        self.assertEqual(fresh.stage,"真金階段")
        self.assertEqual(self.reader.writes,[{"A4":"真金階段"}])
    def test_rejects_stale_snapshot_invalid_target_and_formula_cells(self):
        expected=self.read();self.reader.values["B6"]="是"
        with self.assertRaises(ValidationError):write_trade_setting(self.reader,self.config,expected,"C2",True)
        for cell,value in (("D6","4000"),("A4","不存在階段"),("C2","是")):
            with self.subTest(cell=cell),self.assertRaises(ValidationError):
                write_trade_setting(self.reader,self.config,self.read(),cell,value)
        self.reader.formula_cell="E14"
        with self.assertRaises(ValidationError):self.read()
        self.assertEqual(self.reader.writes,[])
    def test_failed_readback_is_not_reported_as_success_or_automatically_rewritten(self):
        self.reader.bad_readback=True
        with self.assertRaises(ValidationError):write_trade_setting(self.reader,self.config,self.read(),"C2",True)
        self.assertEqual(self.reader.writes,[{"C2":"是"}])
    def test_metadata_failure_and_wrong_mode_never_write(self):
        self.reader.ws.spreadsheet.fetch_sheet_metadata=MagicMock(side_effect=OSError("offline"))
        with self.assertRaises(OSError):self.read()
        for mode in ("csv",):
            with self.assertRaises(ValidationError):read_trade_settings(self.reader,{"mode":mode,"data_layout":"cells"})
        self.assertEqual(self.reader.writes,[])

    def test_unsupported_or_unbounded_stage_sources_are_rejected_before_range_fetch(self):
        for reference in ("='來源'!E:E","=INDIRECT(A1)","='來源'!A1:Z1000"):
            with self.subTest(reference=reference):
                reader=FakePreferencesReader();original=reader.metadata
                def metadata(params):
                    result=original(params)
                    result['sheets'][0]['data'][0]['rowData'][0]['values'][0]['dataValidation']['condition']['values']=[{'userEnteredValue':reference}]
                    return result
                reader.ws.spreadsheet.fetch_sheet_metadata=metadata
                reader.ws.spreadsheet.values_get=MagicMock()
                with self.assertRaises(ValidationError):read_trade_settings(reader,self.config)
                reader.ws.spreadsheet.values_get.assert_not_called()
                self.assertEqual(reader.writes,[])
