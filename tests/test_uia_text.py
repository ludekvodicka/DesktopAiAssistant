from types import SimpleNamespace
import pytest
from desktop_ai_assistant.uia_text import UiaText, MAX_TEXT
from desktop_ai_assistant.text import TextAccessDenied


class Range:
    full: str
    start: int
    end: int
    readonly: bool

    def __init__(self, text, start=0, end=None, readonly=False):
        self.full = text
        self.start = start
        self.end = len(text) if end is None else end
        self.readonly = readonly

    def GetText(self, limit):
        return self.full[self.start:self.end][:limit]

    def Clone(self):
        return Range(self.full, self.start, self.end, self.readonly)

    def GetAttributeValue(self, identifier):
        assert identifier == 40015
        return self.readonly

    def CompareEndpoints(self, endpoint, other, other_endpoint):
        return (self.start, self.end)[endpoint] - (other.start, other.end)[other_endpoint]

    def MoveEndpointByRange(self, endpoint, other, other_endpoint):
        assert endpoint == 1 and other_endpoint == 0
        self.end = other.start


class Element:
    parent: object
    CurrentNativeWindowHandle: int
    CurrentIsPassword: bool
    CurrentIsEnabled: bool
    CurrentControlType: int
    patterns: dict
    document: Range
    selection: object

    def __init__(self, parent=None, text=None, start=0, end=0, readonly=False, control=50033, hwnd=0, value=None):
        self.parent = parent
        self.CurrentNativeWindowHandle = hwnd
        self.CurrentIsPassword = False
        self.CurrentIsEnabled = True
        self.CurrentControlType = control
        self.patterns = {}
        if text is not None:
            self.document = Range(text, readonly=readonly)
            self.selection = SimpleNamespace(Length=1, GetElement=lambda index: Range(text, start, end, readonly))
            self.patterns[10014] = SimpleNamespace(DocumentRange=self.document, GetSelection=lambda: self.selection)
        if value is not None:
            self.patterns[10002] = SimpleNamespace(CurrentValue=value, CurrentIsReadOnly=readonly)

    def GetCurrentPattern(self, identifier):
        if identifier not in self.patterns:
            raise ValueError("No such pattern")
        return SimpleNamespace(QueryInterface=lambda interface: self.patterns[identifier])

    def GetRuntimeId(self):
        return [42]


@pytest.fixture
def reader():
    root = Element(hwnd=123)
    automation = SimpleNamespace(RawViewWalker=SimpleNamespace(GetParentElement=lambda element: element.parent),
                                 CompareElements=lambda a, b: a is b)
    module = SimpleNamespace(IUIAutomationTextPattern=object(), IUIAutomationValuePattern=object())
    return UiaText(automation, module), root, {"hwnd": 123, "pid": 999, "process": "chrome.exe"}


def test_pane_with_text_pattern_exposes_unicode_selection_and_whole_field(reader):
    uia, root, target = reader
    text = "A🙂 žluťoučký text"
    element = Element(root, text, 3, 11)
    snapshot, selected = uia.read(element, target)
    assert snapshot["text"] == "žluťoučk"
    assert (snapshot["start"], snapshot["end"]) == (3, 11)
    assert selected.GetText(100) == snapshot["text"]
    element = Element(root, text, 3, 3)
    snapshot, selected = uia.read(element, target)
    assert snapshot["text"] == text and snapshot["selectionStart"] == 3
    assert selected is element.document


def test_focused_child_resolves_to_text_parent_without_process_id_equality(reader):
    uia, root, target = reader
    editor = Element(root, "Hello world", 6, 11)
    child = Element(editor)
    child.CurrentProcessId = 777
    uia.automation.GetFocusedElement = lambda: child
    assert uia.resolve(child, target) is editor
    assert uia.focused(editor, target)
    assert uia.read(editor, target, read_only=True)[0] == {"text": "world"}


def test_read_only_document_reads_selection_but_never_whole_page_or_edits(reader):
    uia, root, target = reader
    page = Element(root, "Hello world", 6, 11, readonly=True, control=50030)
    assert uia.read(page, target, read_only=True)[0] == {"text": "world"}
    with pytest.raises(RuntimeError, match="Editability"):
        uia.read(page, target)
    page.selection.GetElement = lambda index: Range("Hello world", 6, 6, True)
    with pytest.raises(RuntimeError, match="Select the text"):
        uia.read(page, target, read_only=True)


def test_value_only_control_is_readable_but_not_automatically_replaceable(reader):
    uia, root, target = reader
    element = Element(root, value="readable value", readonly=True)
    assert uia.read(element, target, read_only=True)[0] == {"text": "readable value"}
    with pytest.raises(RuntimeError, match="text selection"):
        uia.read(element, target)


@pytest.mark.parametrize("length", [0, 2])
def test_missing_or_multiple_selection_does_not_become_whole_field(reader, length):
    uia, root, target = reader
    element = Element(root, "Hello")
    element.selection.Length = length
    with pytest.raises(RuntimeError, match="selection"):
        uia.read(element, target, read_only=True)


@pytest.mark.parametrize("blocked", ["password", "disabled", "foreign", "ancestor_password"])
def test_protected_or_foreign_focus_is_refused_before_reading_any_text(reader, blocked):
    uia, root, target = reader
    editor = Element(root, "secret")
    child = Element(editor)
    if blocked == "password":
        child.CurrentIsPassword = True
    elif blocked == "disabled":
        child.CurrentIsEnabled = False
    elif blocked == "foreign":
        editor.parent = None
    elif blocked == "ancestor_password":
        editor.CurrentIsPassword = True
    else:
        raise ValueError(blocked)
    with pytest.raises(TextAccessDenied):
        uia.resolve(child, target)


def test_small_selection_on_large_page_does_not_read_the_whole_document(reader):
    uia, root, target = reader
    page = Element(root, "a" * (MAX_TEXT + 10), 4, 9, readonly=True)
    assert uia.read(page, target, read_only=True)[0] == {"text": "aaaaa"}
    page.selection.GetElement = lambda index: Range("a" * (MAX_TEXT + 10))
    with pytest.raises(TextAccessDenied, match="too large"):
        uia.read(page, target, read_only=True)


def test_out_of_bounds_selection_is_refused(reader):
    uia, root, target = reader
    page = Element(root, "hello", 0, 9)
    with pytest.raises(TextAccessDenied, match="outside"):
        uia.read(page, target)


def test_retained_editor_verification_does_not_require_the_active_selection(reader):
    uia, root, target = reader
    editor = Element(root, "Hello world", 6, 11)
    original, _ = uia.read(editor, target)
    editor.selection = None
    current, selected = uia.read(editor, target, verify_only=True)
    assert current["full"] == original["full"] and current["element"] == original["element"]
    assert selected is None
    with pytest.raises(RuntimeError, match="no text selection"):
        uia.read(editor, target)
