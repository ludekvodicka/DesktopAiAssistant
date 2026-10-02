import html
import re

from .const import UpdateConst


class UpdateReleaseNotes:
    """GitHub release bodies are Markdown; the update UI shows them as plain text, never rich."""

    @staticmethod
    def to_text(body: str | None) -> str | None:
        if not body:
            return None
        text = body.replace("\r\n", "\n").split(UpdateConst.notes_end_marker, 1)[0]
        text = re.sub(r"```[^\n]*\n(.*?)```[ \t]*(?:\n|$)", r"\1", text, flags=re.S)
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        text = re.sub(r"<\s*br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"^ {0,3}#{1,6}(?:[ \t]+|$)", "", text, flags=re.M)
        text = re.sub(r"^([ \t]*)[*+-][ \t]+", r"\1- ", text, flags=re.M)
        text = re.sub(r"(?<!\w)(\*\*|__|\*|_|`)(\S(?:.*?\S)?)\1(?!\w)", r"\2", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"[ \t]+\n", "\n", html.unescape(text))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text or None
