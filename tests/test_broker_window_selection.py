"""Read-only synthetic broker identities; no real windows or trading input."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

from trading_helper.windows import WindowController, WindowInfo, AutomationError
from trading_helper.automation import PlatformAutomation
from trading_helper.demo_broker_port import DemoUiBrokerPort


def window(handle, title='cTrader 5.10.22', width=800, height=600):
    return WindowInfo(handle, title, 0, 0, width, height)


class BrokerWindowSelectionTests(unittest.TestCase):
    def setUp(self):
        self.ctrl = WindowController(NS(guard=MagicMock()))
        self.first, self.second = window(11), window(22)
        self.ctrl.list_windows = MagicMock(return_value=[self.first, self.second])
        self.ctrl.read_ctrader_account = MagicMock(side_effect=lambda w: {11:'111111',22:'222222'}[w.handle])
        self.ctrl._window_pid = MagicMock(side_effect=lambda h: h + 100)

    def test_ctrader_chooses_bound_account_instead_of_first_same_title(self):
        chosen = self.ctrl.find_broker_main('cTrader', platform='cTrader', expected_account='222222')
        self.assertEqual(chosen, self.second)
        self.assertEqual(self.ctrl.read_ctrader_account.call_count, 2)

    def test_account_selection_does_not_depend_on_z_order(self):
        for windows in ([self.first,self.second], [self.second,self.first]):
            self.ctrl.list_windows.return_value = windows
            self.assertEqual(self.ctrl.find_broker_main('cTrader', platform='cTrader',
                expected_account='222222'), self.second)

    def test_duplicate_accounts_stop_without_choosing_first(self):
        self.ctrl.read_ctrader_account.return_value = '222222'
        self.ctrl.read_ctrader_account.side_effect = None
        with self.assertRaisesRegex(AutomationError, '2|多個'):
            self.ctrl.find_broker_main('cTrader', platform='cTrader', expected_account='222222')

    def test_unreadable_candidate_cannot_be_assumed_to_be_another_account(self):
        self.ctrl.read_ctrader_account.side_effect = [AutomationError('unreadable'), '222222']
        with self.assertRaisesRegex(AutomationError, '帳號.*辨識|帳號.*讀取'):
            self.ctrl.find_broker_main('cTrader', platform='cTrader', expected_account='222222')

    def test_missing_bound_account_keeps_ambiguous_windows_blocked(self):
        with self.assertRaisesRegex(AutomationError, '主交易視窗有 2'):
            self.ctrl.find_broker_main('cTrader', platform='cTrader')
        self.ctrl.read_ctrader_account.assert_not_called()

    def test_unique_window_does_not_add_an_account_scan(self):
        self.ctrl.list_windows.return_value = [self.second]
        self.assertEqual(self.ctrl.find_broker_main('cTrader', platform='cTrader',
            expected_account='222222'), self.second)
        self.ctrl.read_ctrader_account.assert_not_called()

    def test_unrelated_modal_is_excluded_before_account_scan(self):
        modal = window(99,'Modify order or position - cTrader')
        self.ctrl.list_windows.return_value = [modal,self.second,self.first]
        self.assertEqual(self.ctrl.find_broker_main('cTrader', platform='cTrader',
            expected_account='222222'), self.second)
        self.assertNotIn(modal, [call.args[0] for call in self.ctrl.read_ctrader_account.call_args_list])

    def test_mt5_matches_bound_account_and_server_without_reading_ctrader(self):
        a=window(31,'111111 - Broker-A - Hedge - [XAUUSD,H1]')
        b=window(32,'222222 - Broker-B - Hedge - [XAUUSD,H1]')
        modal=window(33,'Order: XAUUSD')
        self.ctrl.list_windows.return_value=[modal,a,b]
        for platform in ('MT5','BYBIT MT5','原版MT5'):
            self.assertEqual(self.ctrl.find_broker_main(r'222222.*Broker-B',platform=platform),b)
        self.ctrl.read_ctrader_account.assert_not_called()

    def test_legacy_gooeytrade_multi_account_selection_uses_its_native_title(self):
        first,second=window(11,'GooeyTrade'),window(22,'GooeyTrade cTrader 5.7.14')
        self.ctrl.list_windows.return_value=[first,second]
        self.assertEqual(self.ctrl.find_broker_main('GooeyTrade',platform='GooeyTrade',
            expected_account='222222'),second)

    def test_foreground_fast_path_rejects_a_changed_bound_process(self):
        with self.ctrl.broker_window_session():
            self.ctrl.find_broker_main('cTrader',platform='cTrader',expected_account='222222')
            self.ctrl._window_pid.side_effect=None
            self.ctrl._window_pid.return_value=999
            with patch('trading_helper.windows.user32') as api:
                api.IsIconic.return_value=0
                api.GetForegroundWindow.return_value=self.second.handle
                with self.assertRaisesRegex(AutomationError,'程序已改變'):
                    self.ctrl.focus(self.second)
                api.SetForegroundWindow.assert_not_called()

    def test_saved_mt5_order_point_is_filtered_to_bound_terminal_process(self):
        from trading_helper import gui
        first=window(31,'111111 - Broker-A - Hedge')
        second=window(32,'222222 - Broker-B - Hedge')
        wrong=window(33,'Order: XAUUSD')
        correct=window(34,'Order: XAUUSD')
        self.ctrl.list_windows.return_value=[wrong,correct,first,second]
        profile={'window_title':{'external':r'222222.*Broker-B'},'points':{}}
        dialog=NS(platform='MT5',app=NS(windows=self.ctrl,
                  store=NS(data={'platforms':{'MT5':profile}})),_display_role=lambda key:'external')
        with patch.object(gui,'process_id_for_window',side_effect=lambda h:{31:101,32:102,33:101,34:102}[h]):
            selected=gui.CalibrationDialog._display_window_for_saved_point(dialog,'lot_input',
                {'window_title':'Order: XAUUSD','window_width':800,'window_height':600})
        self.assertEqual(selected,correct)

    def test_mt5_account_filter_does_not_override_bound_server_pattern(self):
        a=window(31,'222222 - Broker-A - Hedge')
        b=window(32,'222222 - Broker-B - Hedge')
        self.ctrl.list_windows.return_value=[a,b]
        self.assertEqual(self.ctrl.find_broker_main(r'222222.*Broker-B',platform='MT5',
            expected_account='222222'),b)

    def test_session_pins_identity_without_rescanning_account_each_field(self):
        with self.ctrl.broker_window_session():
            self.assertEqual(self.ctrl.find_broker_main('cTrader',platform='cTrader',
                expected_account='222222'),self.second)
            self.ctrl.list_windows.return_value=[self.second,self.first]
            self.assertEqual(self.ctrl.find_broker_main('cTrader',platform='cTrader',
                expected_account='222222'),self.second)
        self.assertEqual(self.ctrl.read_ctrader_account.call_count,2)

    def test_closed_bound_window_stops_instead_of_switching_to_replacement(self):
        with self.ctrl.broker_window_session():
            self.ctrl.find_broker_main('cTrader',platform='cTrader',expected_account='222222')
            self.ctrl.list_windows.return_value=[window(44)]
            with self.assertRaisesRegex(AutomationError,'關閉|改變'):
                self.ctrl.find_broker_main('cTrader',platform='cTrader',expected_account='222222')

    def test_reused_handle_with_different_process_is_rejected(self):
        with self.ctrl.broker_window_session():
            self.ctrl.find_broker_main('cTrader',platform='cTrader',expected_account='222222')
            self.ctrl._window_pid.return_value=999
            self.ctrl._window_pid.side_effect=None
            with self.assertRaisesRegex(AutomationError,'程序|改變'):
                self.ctrl.find_broker_main('cTrader',platform='cTrader',expected_account='222222')

    def test_next_operation_resolves_restarted_platform_again(self):
        with self.ctrl.broker_window_session():
            self.ctrl.find_broker_main('cTrader',platform='cTrader',expected_account='222222')
        replacement=window(44)
        self.ctrl.list_windows.return_value=[replacement]
        with self.ctrl.broker_window_session():
            self.assertEqual(self.ctrl.find_broker_main('cTrader',platform='cTrader',
                expected_account='222222'),replacement)

    def test_account_roles_have_independent_window_pins(self):
        with self.ctrl.broker_window_session():
            self.assertEqual(self.ctrl.find_broker_main('cTrader',platform='cTrader',expected_account='111111'),self.first)
            self.assertEqual(self.ctrl.find_broker_main('cTrader',platform='cTrader',expected_account='222222'),self.second)

    def test_failed_operation_releases_its_window_pin(self):
        with self.assertRaisesRegex(RuntimeError,'injected'):
            with self.ctrl.broker_window_session():
                self.ctrl.find_broker_main('cTrader',platform='cTrader',expected_account='222222')
                raise RuntimeError('injected')
        self.assertIsNone(self.ctrl._broker_session.get())

    def test_filled_form_cannot_be_reused_in_a_different_window_after_a_pause(self):
        profile={'window_title':{'internal':'cTrader'},
                 'points':{'lot_input':{'window_width':800,'window_height':600}}}
        flow=NS(config={'platforms':{'cTrader':profile}},windows=self.ctrl,
                _last_verified_fills={('cTrader','internal'):{'main_window':(11,111)}})
        port=DemoUiBrokerPort(flow,lambda _:None)
        self.ctrl.list_windows.return_value=[self.second]
        with patch('trading_helper.windows.user32') as api:
            api.IsIconic.return_value=0
            with self.assertRaisesRegex(AutomationError,'填入後平台視窗已更換'):
                port._form_window('cTrader','internal')

    def test_fill_and_broker_ports_use_existing_role_accounts_for_both_sides(self):
        profile={'window_title':{'internal':'cTrader','external':'cTrader'},
                 'account_number':{'internal':'111111','external':'222222'},
                 'points':{'lot_input':{'window_width':800,'window_height':600}}}
        flow=PlatformAutomation({'platforms':{'cTrader':profile}},self.ctrl,self.ctrl.emergency,lambda _:None)
        port=DemoUiBrokerPort(flow,lambda _:None)
        with self.ctrl.broker_window_session(), patch('trading_helper.windows.user32') as api:
            api.IsIconic.return_value=0
            for role, expected in [('internal',self.first),('external',self.second)]:
                self.assertEqual(flow._window_for_point(profile,role,profile['points']['lot_input']),expected)
                self.assertEqual(port._bound('cTrader',role)[1],expected)
        self.assertEqual(self.ctrl.read_ctrader_account.call_count,4)

    def test_native_account_query_rejects_duplicate_and_invalid_labels(self):
        ctrl=WindowController(NS(guard=lambda:None))
        node=NS(window_text=lambda:'222222',element_info=NS(automation_id='CTraderAccountNumberTextBlock_AId'))
        root=NS(descendants=MagicMock(return_value=[node]))
        with patch('pywinauto.Desktop',return_value=NS(window=lambda **_:root)):
            self.assertEqual(ctrl.read_ctrader_account(self.second),'222222')
            root.descendants.return_value=[node,node]
            with self.assertRaises(AutomationError):ctrl.read_ctrader_account(self.second)
            root.descendants.return_value=[]
            with self.assertRaises(AutomationError):ctrl.read_ctrader_account(self.second)

    def test_calibrated_resize_rechecks_selected_window_among_multiple_mains(self):
        small=window(22,width=600,height=400)
        self.ctrl.list_windows.return_value=[self.first,small]
        def maximize(handle):
            self.assertEqual(handle,22)
            self.ctrl.list_windows.return_value=[self.second,self.first]
        with patch.object(self.ctrl,'_is_maximized',return_value=False), \
             patch.object(self.ctrl,'_maximize_window',side_effect=maximize), \
             patch('trading_helper.windows.user32') as api:
            api.IsIconic.return_value=0
            selected=self.ctrl.find_calibrated_main('cTrader',
                {'window_width':800,'window_height':600},expected_account='222222')
        self.assertEqual(selected,self.second)

    def test_minimized_selected_window_is_restored_before_size_check(self):
        self.ctrl.list_windows.return_value=[window(22,width=160,height=30)]
        with patch('trading_helper.windows.user32') as api:
            api.IsIconic.side_effect=[1,0]
            api.ShowWindow.side_effect=lambda *_: setattr(self.ctrl.list_windows,'return_value',[self.second])
            selected=self.ctrl.find_calibrated_main('cTrader',
                {'window_width':800,'window_height':600},expected_account='222222')
        self.assertEqual(selected,self.second)
        api.ShowWindow.assert_called_once_with(22,9)

    def test_modify_dialog_selection_ignores_other_processes_and_foreground(self):
        for platform,title in [('cTrader','Modify order or position - cTrader'),
                               ('MT5','持倉: #123456 buy 0.01 XAUUSD'),
                               ('BYBIT MT5','持倉: #123456 buy 0.01 XAUUSD'),
                               ('原版MT5','Position: #123456 buy 0.01 XAUUSD')]:
            correct=window(44,title)
            wrong=window(33,title)
            main=window(11,'111111 - Broker-A - Hedge') if 'MT5' in platform else self.first
            self.ctrl.list_windows.return_value=[wrong,correct,main]
            self.ctrl._window_pid.side_effect=lambda h:2 if h==33 else 1
            self.ctrl.active_window=MagicMock(side_effect=AssertionError('foreground must not select a dialog'))
            with patch.object(self.ctrl,'_window_owned_by',return_value=None):
                selected=self.ctrl.wait_for_broker_modify(main,platform,
                    {'x_px':100,'y_px':100,'window_width':800,'window_height':600},timeout=1)
            self.assertEqual(selected,correct)
            self.ctrl.active_window.assert_not_called()

    def test_ambiguous_modify_dialogs_cannot_choose_first_by_size(self):
        a=window(33,'Modify order or position - cTrader')
        b=window(44,'Modify order or position - cTrader')
        self.ctrl.list_windows.return_value=[a,b,self.first]
        self.ctrl._window_pid.side_effect=None
        self.ctrl._window_pid.return_value=1
        with patch('trading_helper.windows.time.monotonic',side_effect=[0,0,2]), \
             patch('trading_helper.windows.time.sleep'), \
             patch.object(self.ctrl,'_window_owned_by',return_value=None):
            with self.assertRaisesRegex(AutomationError,'唯一修改視窗'):
                self.ctrl.wait_for_broker_modify(self.first,'cTrader',
                    {'window_width':800,'window_height':600},timeout=1)

    def test_same_process_multi_account_dialogs_use_owner_chain(self):
        a=window(33,'Modify order or position - cTrader')
        b=window(44,'Modify order or position - cTrader')
        self.ctrl.list_windows.return_value=[a,b,self.first,self.second]
        self.ctrl._window_pid.side_effect=None
        self.ctrl._window_pid.return_value=1
        with patch('win32gui.GetWindow',side_effect=lambda h,flag:{33:11,44:22}.get(h,0)):
            selected=self.ctrl.wait_for_broker_modify(self.second,'cTrader',
                {'x_px':100,'y_px':100,'window_width':800,'window_height':600},timeout=1)
        self.assertEqual(selected,b)

    def test_missing_owner_is_unknown_when_same_process_has_multiple_mains(self):
        dialog=window(33,'Modify order or position - cTrader')
        self.ctrl.list_windows.return_value=[dialog,self.first,self.second]
        self.ctrl._window_pid.side_effect=None
        self.ctrl._window_pid.return_value=1
        with patch('win32gui.GetWindow',return_value=0), \
             patch('trading_helper.windows.time.monotonic',side_effect=[0,0,2]), \
             patch('trading_helper.windows.time.sleep'):
            with self.assertRaisesRegex(AutomationError,'唯一修改視窗'):
                self.ctrl.wait_for_broker_modify(self.second,'cTrader',
                    {'x_px':100,'y_px':100,'window_width':800,'window_height':600},timeout=1)

    def test_disappearing_native_dialog_cannot_authorize_owner_fallback(self):
        import pywintypes
        with patch('win32gui.GetWindow',side_effect=pywintypes.error(1400,'GetWindow','invalid handle')):
            self.assertFalse(self.ctrl._window_owned_by(33,11))


if __name__=='__main__':
    unittest.main()
