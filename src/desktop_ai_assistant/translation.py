import copy
import threading
from PySide6.QtCore import QMimeData, QObject, Qt, QUrl, Signal, Slot, Property
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication, QTextDocument
from . import providers
from .clipboard import source_from_mime
from .text import EXPLAIN, LANGUAGES, READER_ACTIONS, SOURCES, clean_markdown

FORMS = {"plain": "plain", "markdown": "markdown", "image": "markdown"}
IMAGES = {"selection": "Image from the selection", "region": "Image from the screen region", "clipboard": "Image from the clipboard"}


def render_html(text, form):
    document = QTextDocument()
    if form == "markdown":
        features = QTextDocument.MarkdownFeature
        document.setMarkdown(clean_markdown(text), features.MarkdownDialectGitHub | features.MarkdownNoHTML)
    elif form == "plain":
        document.setPlainText(text)
    else:
        raise ValueError("Unknown display format")
    # Qt writes the default palette blue into every link; it is unreadable on the dark theme.
    return document.toHtml().replace("color:#0000ff;", "color:#4aa3ff;")


def reader_size(parts, note, area):
    documents, font = [QTextDocument() for _ in parts], QFont(QGuiApplication.font())
    font.setPixelSize(14)
    for document, html in zip(documents, parts):
        document.setDefaultFont(font)
        document.setHtml(html)
    # The window adds margins, padding and the scroll bar around the text, and the title, note, question and button rows.
    width = max(480, min(int(area.width() * 0.6), max(int(x.idealWidth()) for x in documents) + 72))
    for document in documents:
        document.setTextWidth(width - 72)
    text = sum(int(x.size().height()) + 16 for x in documents)
    return width, max(300, min(int(area.height() * 0.7), text + 264 + (40 if note else 0)))


class Translator(QObject):
    changed = Signal()
    opened = Signal()
    ended = Signal()
    notice = Signal(str)
    regionRequested = Signal()
    stopped = Signal()
    answered = Signal()
    _read = Signal(int, object)
    _done = Signal(int, str, object)
    _answer = Signal(int, str, str, bool)
    config: object
    history: object
    read_selection: object
    _thread: threading.Thread | None
    _cancel: threading.Event
    _generation: int
    _settings: dict | None
    _region_settings: dict | None
    _operation: str
    _region_operation: str
    _kind: str
    _source: dict | None
    _state: str
    _error: str
    _note: str
    _result_text: str
    _result_html: str
    _source_html: str
    _job: str
    _original: str
    _conversation: list
    _pending: str
    _ask_error: str
    _ask_thread: threading.Thread | None
    _ask_cancel: threading.Event

    def __init__(self, config, history, read_selection):
        super().__init__()
        self.config, self.history, self.read_selection = config, history, read_selection
        self._thread, self._cancel, self._generation = None, threading.Event(), 0
        self._settings, self._region_settings, self._kind, self._source = None, None, "", None
        self._operation, self._region_operation = "translate", "translate"
        self._state, self._error, self._note = "idle", "", ""
        self._result_text, self._result_html, self._source_html = "", "", ""
        self._job, self._original, self._conversation, self._pending, self._ask_error = "", "", [], "", ""
        self._ask_thread, self._ask_cancel = None, threading.Event()
        self._read.connect(self._on_read, Qt.QueuedConnection)
        self._done.connect(self._on_done, Qt.QueuedConnection)
        self._answer.connect(self._on_answer, Qt.QueuedConnection)

    @property
    def active(self):
        return any(x is not None and x.is_alive() for x in (self._thread, self._ask_thread))

    @Property(str, notify=changed)
    def state(self):
        return self._state

    @Property(bool, notify=changed)
    def running(self):
        return self._state in ("reading", "translating", "explaining")

    @Property(str, notify=changed)
    def progressText(self):
        return READER_ACTIONS[self._operation]["progress"]

    @Property(str, notify=changed)
    def copyText(self):
        return READER_ACTIONS[self._operation]["copy"]

    @Property(str, notify=changed)
    def stopText(self):
        return READER_ACTIONS[self._operation]["stop"]

    @Property(str, notify=changed)
    def title(self):
        if self._settings is None:
            return ""
        title = f"{READER_ACTIONS[self._operation]['title']} {LANGUAGES[self._settings['nativeLanguage']][0]} · {SOURCES[self._kind]}"
        return title + " · " + self._source["origin"] if self._kind == "selection" and self._source else title

    @Property(str, notify=changed)
    def preview(self):
        if self._source is None:
            return ""
        return IMAGES[self._kind] if self._source["format"] == "image" else self._source["text"][:2000]

    @Property(str, notify=changed)
    def resultHtml(self):
        return self._result_html

    @Property(str, notify=changed)
    def sourceHtml(self):
        return self._source_html

    @Property(str, notify=changed)
    def note(self):
        return self._note

    @Property(str, notify=changed)
    def error(self):
        return self._error

    @Property(bool, notify=changed)
    def canRetry(self):
        return self._source is not None and self._state in ("done", "failed", "cancelled")

    @Property(bool, notify=changed)
    def asking(self):
        return bool(self._pending)

    @Property(bool, notify=changed)
    def canAsk(self):
        return self._state == "done" and not self._pending

    @Property(str, notify=changed)
    def askError(self):
        return self._ask_error

    @Property(str, notify=changed)
    def conversationHtml(self):
        label = {EXPLAIN: "Explain"}
        entries = [f"**Q:** {label.get(x['question'], x['question'])}\n\n{x['answer']}" for x in self._conversation]
        if self._pending:
            entries.append(f"**Q:** {label.get(self._pending, self._pending)}\n\n_…_")
        return render_html("\n\n---\n\n".join(entries), "markdown") if entries else ""

    def start(self, kind, target, operation="translate"):
        if operation not in READER_ACTIONS:
            raise ValueError("Unknown reader action")
        settings = copy.deepcopy(self.config.value)
        if kind == "selection":
            self._begin(settings, kind, target, None, operation)
        elif kind == "clipboard":
            try:
                source = source_from_mime(QGuiApplication.clipboard().mimeData(), kind, "Clipboard", "The clipboard has no text")
            except RuntimeError as error:
                self.notice.emit(str(error))
                return
            self._begin(settings, kind, target, source, operation)
        elif kind == "region":
            self._region_settings = settings
            self._region_operation = operation
            self.regionRequested.emit()
        else:
            raise ValueError("Unknown translation source")

    def region_picked(self, png):
        self._begin(self._region_settings, "region", None,
                    {"kind": "region", "format": "image", "text": "", "image": png, "origin": "Screen region"}, self._region_operation)

    def _begin(self, settings, kind, target, source, operation):
        self._cancel.set()
        previous, self._cancel = self._thread, threading.Event()
        self._generation += 1
        self._settings, self._kind, self._source, self._note = settings, kind, source, ""
        self._operation = operation
        self._ask_cancel.set()
        self._job, self._original, self._conversation, self._pending, self._ask_error = "", "", [], "", ""
        self._set("reading" if source is None else READER_ACTIONS[operation]["state"])
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        args=(self._generation, settings, target, source, self._cancel, previous, operation))
        self._thread.start()

    def _run(self, generation, settings, target, source, cancel, previous, operation):
        job = None
        try:
            if source is None:
                source = self.read_selection(target)
                if cancel.is_set():
                    raise providers.Cancelled("Cancelled")
                self._read.emit(generation, source)
            if previous:
                # One CLI per lane: the cancelled run ends within about 3 s, and the GUI thread never waits for it.
                previous.join()
            if cancel.is_set():
                raise providers.Cancelled("Cancelled")
            job = self.history.create({"action": operation + "_" + source["kind"], "source": source["origin"], "original": source["text"],
                                       "format": source["format"], "language": settings["nativeLanguage"], "provider": settings["provider"],
                                       "model": settings["models"][settings["provider"]], "rules": settings["rules"][operation]})
            if operation == "translate":
                result = providers.translate(settings, source, cancel)
            elif operation == "explain":
                result = providers.explain(settings, source, cancel)
            else:
                raise ValueError("Unknown reader action")
            self.history.update(job, READER_ACTIONS[operation]["status"], original=result["source"], result=result["text"])
            self._done.emit(generation, "done", {**result, "job": job})
        except providers.Cancelled:
            if job:
                self.history.update(job, "cancelled")
            self._done.emit(generation, "cancelled", None)
        except Exception as error:
            message = str(error) or type(error).__name__
            if job:
                self.history.update(job, "failed", error=message)
            self._done.emit(generation, "failed", message)

    @Slot(int, object)
    def _on_read(self, generation, source):
        if generation == self._generation:
            self._source = source
            self._set(READER_ACTIONS[self._operation]["state"])

    @Slot(int, str, object)
    def _on_done(self, generation, outcome, payload):
        if generation != self._generation:
            return
        if outcome == "done":
            source_form = FORMS[self._source["format"]]
            form = "markdown" if self._operation == "explain" else source_form
            self._result_text, self._job, self._original = payload["text"], payload["job"], payload["source"]
            self._result_html, self._source_html = render_html(payload["text"], form), render_html(payload["source"], source_form)
            same = self._operation == "translate" and payload["text"].strip() == payload["source"].strip()
            self._note = payload["warning"] or (f"The text is already in {LANGUAGES[self._settings['nativeLanguage']][1]}" if same else "")
            self._set("done")
            self.opened.emit()
        elif outcome == "failed":
            self.notice.emit(payload)
            self._set("failed", payload)
        elif outcome == "cancelled":
            self._set("cancelled")
        else:
            raise ValueError("Unknown translation outcome")
        self.ended.emit()

    def _set(self, state, error=""):
        self._state, self._error = state, error
        self.changed.emit()

    @Slot()
    def stop(self):
        self._cancel.set()
        self._ask_cancel.set()
        self.stopped.emit()

    @Slot(str)
    def ask(self, question):
        if not self.canAsk or not question.strip():
            return
        self._ask_cancel = threading.Event()
        self._pending, self._ask_error = question.strip(), ""
        self.changed.emit()
        self._ask_thread = threading.Thread(target=self._ask_run, daemon=True, args=(
            self._generation, copy.deepcopy(self._settings), self._original, self._result_text,
            copy.deepcopy(self._conversation), self._pending, self._ask_cancel))
        self._ask_thread.start()

    @Slot()
    def explain(self):
        self.ask(EXPLAIN)

    def _ask_run(self, generation, settings, original, translation, conversation, question, cancel):
        try:
            self._answer.emit(generation, question, providers.answer(settings, original, translation, conversation, question, cancel), True)
        except providers.Cancelled:
            self._answer.emit(generation, question, "", False)
        except Exception as error:
            self._answer.emit(generation, question, str(error) or type(error).__name__, False)

    @Slot(int, str, str, bool)
    def _on_answer(self, generation, question, text, ok):
        if generation != self._generation or question != self._pending:
            return
        self._pending = ""
        if ok:
            self._conversation.append({"question": question, "answer": text})
            try:
                self.history.update(self._job, READER_ACTIONS[self._operation]["status"], conversation=self._conversation)
            except ValueError:
                pass  # The entry expired or History was cleared; the answer still shows.
        else:
            self._ask_error = text
        self.changed.emit()
        self.answered.emit()

    @Slot()
    def retry(self):
        if self.canRetry:
            self._begin(copy.deepcopy(self.config.value), self._kind, None, self._source, self._operation)

    @Slot()
    def closed(self):
        if self.running or self._pending:
            self.stop()

    @Slot()
    def copy(self):
        mime = QMimeData()
        mime.setHtml(self._result_html)
        # Markdown or plain text stays readable in editors without HTML paste.
        mime.setText(self._result_text)
        QGuiApplication.clipboard().setMimeData(mime)

    @Slot(str)
    def openLink(self, link):
        url = QUrl(link)
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)

    def close(self):
        self._cancel.set()
        self._ask_cancel.set()
        for thread in (self._thread, self._ask_thread):
            if thread:
                thread.join(8)
