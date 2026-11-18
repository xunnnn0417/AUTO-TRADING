"""Fresh native UIA queries filtered before Python wrappers are constructed."""
from __future__ import annotations


FORM_TYPES = ('Edit', 'Spinner', 'RadioButton', 'CheckBox', 'Text', 'Button')
INPUT_TYPES = ('Edit', 'Spinner', 'RadioButton', 'CheckBox')
ACCOUNT_ID = 'CTraderAccountNumberTextBlock_AId'
PLACE_ORDER_ID = 'Orders_Create_MarketOrderPlaceButtonControl__Button_NewOrdersWindowPlaceOrder_AId'


def fresh_controls(root, control_types=FORM_TYPES, *, text_ids=(), text_names=None, button_ids=None):
    """Keep all matching descendants/duplicates, without reading unrelated UI.

    The query and Value/Toggle/Selection patterns remain fresh on every call.
    No wrapper, value, visibility or geometry is cached between checks.
    """
    from pywinauto.application import WindowSpecification
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import elements_from_uia_array

    if isinstance(root, WindowSpecification):
        root = root.wrapper_object()
    if not isinstance(root, UIAWrapper):
        # Existing offline adapters implement descendants rather than COM.
        return root.descendants()
    if not control_types:
        raise ValueError('UIA query requires control types')
    client = IUIA()
    conditions = []
    for kind in control_types:
        condition = client.build_condition(control_type=kind)
        identities = None
        if kind == 'Text' and text_names is not None:
            identities = [client.iuia.CreatePropertyCondition(
                client.UIA_dll.UIA_AutomationIdPropertyId, value) for value in text_ids]
            identities += [client.build_condition(title=value) for value in text_names if value]
        elif kind == 'Button' and button_ids is not None:
            identities = [client.iuia.CreatePropertyCondition(
                client.UIA_dll.UIA_AutomationIdPropertyId, value) for value in button_ids]
        if identities is not None:
            if not identities:
                continue
            identity = (identities[0] if len(identities) == 1
                        else client.iuia.CreateOrConditionFromArray(identities))
            condition = client.iuia.CreateAndCondition(condition, identity)
        conditions.append(condition)
    if not conditions:
        raise ValueError('UIA query has no target identities')
    condition = (conditions[0] if len(conditions) == 1
                 else client.iuia.CreateOrConditionFromArray(conditions))
    pointers = root.element_info.element.FindAll(client.tree_scope['descendants'], condition)
    return [UIAWrapper(info) for info in elements_from_uia_array(pointers)]
