"""Native query contract; no live broker windows or input actions."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.uia_inventory import fresh_controls, INPUT_TYPES, FORM_TYPES, ACCOUNT_ID, PLACE_ORDER_ID


class FreshInventoryTests(unittest.TestCase):
    def test_native_query_filters_before_wrapping_and_keeps_duplicate_targets(self):
        import pywinauto.controls.uiawrapper as wrappers
        import pywinauto.uia_element_info as elements
        from pywinauto.uia_defines import IUIA
        root = MagicMock(spec=wrappers.UIAWrapper)
        client = MagicMock(spec=IUIA())
        client.tree_scope = {'descendants': 4}
        client.build_condition.side_effect = lambda **args: args['control_type']
        root.element_info.element.FindAll.return_value = 'native-array'
        a, b = object(), object()
        with patch('pywinauto.uia_defines.IUIA', return_value=client), \
             patch.object(elements, 'elements_from_uia_array', return_value=[a, b]) as unpack:
            # Preserve the actual wrapper type check; replace construction only.
            with patch.object(wrappers.UIAWrapper, '__new__', side_effect=lambda cls, info: info):
                result = fresh_controls(root, INPUT_TYPES)
        self.assertEqual(result, [a, b])
        client.iuia.CreateOrConditionFromArray.assert_called_once_with(list(INPUT_TYPES))
        root.element_info.element.FindAll.assert_called_once_with(
            4, client.iuia.CreateOrConditionFromArray.return_value)
        unpack.assert_called_once_with('native-array')
        root.descendants.assert_not_called()

    def test_each_round_issues_a_new_native_query_and_rejects_query_failure(self):
        from pywinauto.controls.uiawrapper import UIAWrapper
        root = MagicMock(spec=UIAWrapper)
        root.element_info.element.FindAll.side_effect = RuntimeError('provider unavailable')
        with self.assertRaisesRegex(RuntimeError, 'provider unavailable'):
            fresh_controls(root)
        root.descendants.assert_not_called()
        self.assertEqual(FORM_TYPES, ('Edit','Spinner','RadioButton','CheckBox','Text','Button'))

    def test_existing_isolated_adapter_keeps_its_interface(self):
        root = SimpleNamespace(descendants=MagicMock(return_value=['a','a']))
        self.assertEqual(fresh_controls(root), ['a','a'])
        root.descendants.assert_called_once_with()

    def test_form_query_restricts_text_and_buttons_without_dropping_input_types(self):
        from pywinauto.controls.uiawrapper import UIAWrapper
        from pywinauto.uia_defines import IUIA
        root = MagicMock(spec=UIAWrapper)
        client = MagicMock(spec=IUIA())
        client.tree_scope = {'descendants': 4}
        client.build_condition.side_effect = lambda **kw: tuple(kw.items())
        client.iuia.CreatePropertyCondition.side_effect = lambda prop, value: ('id', value)
        client.iuia.CreateOrConditionFromArray.side_effect = lambda items: ('or', tuple(items))
        client.iuia.CreateAndCondition.side_effect = lambda a, b: ('and', a, b)
        with patch('pywinauto.uia_defines.IUIA', return_value=client), \
             patch('pywinauto.uia_element_info.elements_from_uia_array', return_value=[]):
            fresh_controls(root, text_ids=(ACCOUNT_ID,), text_names=('Gold vs US Dollar',),
                           button_ids=(PLACE_ORDER_ID,))
        query = repr(root.element_info.element.FindAll.call_args)
        for value in (*INPUT_TYPES, ACCOUNT_ID, PLACE_ORDER_ID, 'Gold vs US Dollar'):
            self.assertIn(value, query)
        self.assertIn('and', query)
        root.descendants.assert_not_called()

    def test_account_query_cannot_fall_back_to_all_text(self):
        from pywinauto.controls.uiawrapper import UIAWrapper
        root = MagicMock(spec=UIAWrapper)
        with patch('pywinauto.uia_element_info.elements_from_uia_array', return_value=[]):
            fresh_controls(root, ('Text',), text_ids=(ACCOUNT_ID,), text_names=())
            self.assertEqual(root.element_info.element.FindAll.call_count, 1)
            with self.assertRaisesRegex(ValueError, 'no target'):
                fresh_controls(root, ('Text',), text_names=())
        self.assertEqual(root.element_info.element.FindAll.call_count, 1)
