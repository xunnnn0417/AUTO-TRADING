"""Native query contract; no live broker windows or input actions."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from trading_helper.uia_inventory import fresh_controls, INPUT_TYPES, FORM_TYPES


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
