"""Fresh native UIA queries filtered before Python wrappers are constructed."""
from __future__ import annotations


FORM_TYPES = ('Edit', 'Spinner', 'RadioButton', 'CheckBox', 'Text', 'Button')
INPUT_TYPES = ('Edit', 'Spinner', 'RadioButton', 'CheckBox')


def fresh_controls(root, control_types=FORM_TYPES):
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
    conditions = [client.build_condition(control_type=kind) for kind in control_types]
    condition = (conditions[0] if len(conditions) == 1
                 else client.iuia.CreateOrConditionFromArray(conditions))
    pointers = root.element_info.element.FindAll(client.tree_scope['descendants'], condition)
    return [UIAWrapper(info) for info in elements_from_uia_array(pointers)]
