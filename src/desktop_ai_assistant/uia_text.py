import comtypes
import win32gui
from .text import TextAccessDenied


MAX_TEXT = 200000


class UiaText:
    automation: object
    module: object

    def __init__(self, automation, module):
        self.automation = automation
        self.module = module

    def ancestors(self, element, target):
        elements = []
        for _ in range(64):
            if not element:
                break
            if element.CurrentIsPassword:
                raise TextAccessDenied("Password fields cannot be read")
            if not element.CurrentIsEnabled:
                raise TextAccessDenied("The focused control is disabled")
            elements.append(element)
            hwnd = element.CurrentNativeWindowHandle
            if hwnd == target["hwnd"]:
                return elements
            if hwnd and win32gui.GetAncestor(hwnd, 2) != target["hwnd"]:
                break
            element = self.automation.RawViewWalker.GetParentElement(element)
        raise TextAccessDenied("The text control does not belong to the original window")

    def pattern(self, element, identifier, interface):
        try:
            pattern = element.GetCurrentPattern(identifier)
            return pattern.QueryInterface(interface) if pattern else None
        except (comtypes.COMError, ValueError):
            return None

    def resolve(self, element, target):
        elements = self.ancestors(element, target)
        for candidate in elements:
            if self.pattern(candidate, 10014, self.module.IUIAutomationTextPattern) or self.pattern(candidate, 10002, self.module.IUIAutomationValuePattern):
                return candidate
        raise RuntimeError("This control does not expose text through Windows UI Automation")

    @staticmethod
    def text(text_range):
        text = text_range.GetText(MAX_TEXT + 1)
        if len(text) > MAX_TEXT:
            raise TextAccessDenied("This text is too large")
        return text

    def read(self, element, target, read_only=False, verify_only=False):
        self.ancestors(element, target)
        value = self.pattern(element, 10002, self.module.IUIAutomationValuePattern)
        pattern = self.pattern(element, 10014, self.module.IUIAutomationTextPattern)
        if not pattern:
            if not read_only or value is None:
                raise RuntimeError("This control does not expose a text selection; use Current app for plain text editing")
            full = value.CurrentValue
            if len(full) > MAX_TEXT:
                raise TextAccessDenied("This text is too large")
            return {"text": full}, None
        document = pattern.DocumentRange
        writable = value is not None and not value.CurrentIsReadOnly
        if value is None:
            try:
                readonly = document.GetAttributeValue(40015)
            except comtypes.COMError:
                readonly = None
            writable = isinstance(readonly, (bool, int)) and readonly == 0
        if not read_only and not writable:
            raise RuntimeError("Editability cannot be verified for this field")
        if verify_only:
            return {"kind": "windows", "target": target, "element": list(element.GetRuntimeId()), "full": self.text(document)}, None
        selection = pattern.GetSelection()
        if not selection or selection.Length == 0:
            raise RuntimeError("Select text first; this control exposes no text selection")
        if selection.Length != 1:
            raise TextAccessDenied("Multiple text selections are not supported")
        selected = selection.GetElement(0)
        if selected.CompareEndpoints(0, document, 0) < 0 or selected.CompareEndpoints(1, document, 1) > 0:
            raise TextAccessDenied("The selection is outside the original text control")
        whole = selected.CompareEndpoints(0, selected, 1) == 0
        if read_only:
            if whole and not writable and element.CurrentControlType != 50004:
                raise RuntimeError("Select the text to translate or explain first")
            return {"text": self.text(document if whole else selected)}, None
        full = self.text(document)
        prefix = document.Clone()
        prefix.MoveEndpointByRange(1, selected, 0)
        start = len(self.text(prefix))
        part = self.text(selected)
        end = start + len(part)
        if full[start:end] != part:
            raise TextAccessDenied("The text selection could not be verified")
        return {"kind": "windows", "target": target, "element": list(element.GetRuntimeId()),
                "full": full, "text": full if whole else part, "start": 0 if whole else start,
                "end": len(full) if whole else end, "selectionStart": start, "selectionEnd": end}, document if whole else selected

    def focused(self, element, target):
        focused = self.automation.GetFocusedElement()
        return any(self.automation.CompareElements(element, candidate) for candidate in self.ancestors(focused, target))
