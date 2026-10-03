import copy
import json
import os
from pathlib import Path
from .text import LANGUAGES, RULES


def data_dir():
    path = Path(os.environ.get("DESKTOP_AI_DATA", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DesktopAiAssistant"))
    path.mkdir(parents=True, exist_ok=True)
    return path


EDITS = tuple(RULES)
TRANSLATIONS = ("translate_selection", "translate_region", "translate_clipboard")
EXPLANATIONS = ("explain_selection", "explain_region", "explain_clipboard")
GROUPS = ("english", "reader", "translate", "explain", "macros", "application", "system")
BUILT_IN = {"", "history", "settings", "restart", "jamat_new", "jamat_remarkable", *EDITS, *TRANSLATIONS, *EXPLANATIONS, *GROUPS}

DEFAULT = {
    "version": 6, "hotkey": "Ctrl+Alt+Space", "stopHotkey": "Ctrl+Alt+Escape",
    "provider": "claude", "models": {"claude": "", "codex": ""},
    "theme": "dark", "size": 1.0, "reducedMotion": False, "historyDays": 30,
    "socialLowercase": True, "autostart": False, "nativeLanguage": "cs",
    "rules": {"english_formal": "", "english_social": "", "native": "", "translate": "", "explain": ""},
    "slots": ["macros", "english", "reader", "native", "system", "", "application", ""],
    "bindings": [],
    "appearance": {},
    "slotAppearance": [{} for _ in range(8)],
    "folders": [],
    "profiles": [],
    "macros": [{"id": "english", "name": "Fix English", "steps": [{"type": "ai", "value": "english_formal"}]},
               {"id": "snippet", "name": "Quick reply", "steps": [{"type": "text", "value": "Thanks, I will take a look."}]}],
    "jamat": {"cli": "", "directory": "", "controller": "", "channel": "development"},
}


def native_id(action):
    return "native" if action == "czech" else action


def validate(value):
    if not isinstance(value, dict) or value.get("version") not in (1, 2, 3, 4, 5, 6):
        raise ValueError("Unsupported settings version")
    if set(value) - set(DEFAULT):
        raise ValueError("Unknown settings fields")
    result = copy.deepcopy(DEFAULT)
    result.update(copy.deepcopy(value))
    if result["version"] == 1:
        result["version"] = 2
        result["slots"] = list(result["slots"])
        if not any(action in result["slots"] for action in ("restart", "system")) and "" in result["slots"]:
            position = 4 if len(result["slots"]) > 4 and result["slots"][4] == "" else result["slots"].index("")
            result["slots"][position] = "restart"
    if result["version"] < 4:
        result["slots"] = ["system" if action == "restart" else action for action in result["slots"]]
    if result["version"] < 5:
        result["slots"] = [native_id(x) for x in result["slots"]]
        for owner in result["folders"] + result["profiles"]:
            if isinstance(owner.get("actions"), list):
                owner["actions"] = [native_id(x) for x in owner["actions"]]
        for binding in result["bindings"]:
            binding["action"] = native_id(binding.get("action", ""))
        for step in (s for m in result["macros"] for s in m.get("steps", []) if s.get("type") == "ai"):
            step["value"] = native_id(step.get("value"))
        for key in ("appearance", "rules"):
            if isinstance(result[key], dict):
                result[key] = {native_id(k): v for k, v in result[key].items()}
        # Schema 4 tolerated extra rule keys; schema 5 rejects them, which would stop the app at start.
        if isinstance(result["rules"], dict):
            result["rules"] = {k: v for k, v in result["rules"].items() if k in DEFAULT["rules"]}
        if not any(action in result["slots"] for action in ("translate", "reader")) and "" in result["slots"]:
            result["slots"][result["slots"].index("")] = "translate"
    if result["version"] < 6:
        result["slots"] = ["reader" if x == "translate" else x for x in result["slots"]]
        for owner in result["folders"] + result["profiles"]:
            if isinstance(owner.get("actions"), list):
                owner["actions"] = ["reader" if x == "translate" else x for x in owner["actions"]]
        if isinstance(result["appearance"], dict) and "translate" in result["appearance"]:
            result["appearance"]["reader"] = result["appearance"].pop("translate")
    result["version"] = 6
    if result["provider"] not in ("codex", "claude") or result["theme"] not in ("dark", "light", "contrast"):
        raise ValueError("Invalid provider or theme")
    if result["size"] not in (0.85, 1.0, 1.2) or not isinstance(result["historyDays"], int) or not 1 <= result["historyDays"] <= 365:
        raise ValueError("Invalid size or retention")
    if not isinstance(result["models"], dict) or any(not isinstance(result["models"].get(p), str) for p in ("codex", "claude")):
        raise ValueError("Invalid models")
    if not isinstance(result["nativeLanguage"], str) or result["nativeLanguage"] not in LANGUAGES:
        raise ValueError("Unknown native language")
    if isinstance(result["rules"], dict):
        result["rules"] = {**DEFAULT["rules"], **result["rules"]}
    if not isinstance(result["rules"], dict) or set(result["rules"]) != set(DEFAULT["rules"]) or any(not isinstance(x, str) for x in result["rules"].values()):
        raise ValueError("Invalid language rules")
    ids = set()
    for macro in result["macros"]:
        if not isinstance(macro.get("id"), str) or not macro["id"] or macro["id"] in ids or not macro.get("name"):
            raise ValueError("Macro IDs must be unique and names must be filled")
        ids.add(macro["id"])
        if not 1 <= len(macro["steps"]) <= 50:
            raise ValueError("A macro needs 1 to 50 steps")
        for step in macro["steps"]:
            kind = step.get("type")
            if kind == "delay":
                if not isinstance(step.get("value"), (int, float)) or not 0 <= step["value"] <= 60:
                    raise ValueError("Delay must be 0 to 60 seconds")
            elif kind == "ai":
                if step.get("value") not in EDITS:
                    raise ValueError("Unknown language action")
            elif kind in ("keys", "text", "open", "activate", "app"):
                if not isinstance(step.get("value"), str) or not step["value"]:
                    raise ValueError("Step value is required")
                if kind == "app" and step["value"] not in ("jamat_new", "jamat_remarkable"):
                    raise ValueError("Unknown application command")
            else:
                raise ValueError("Unknown macro step")
    actions = BUILT_IN | {"macro:" + x for x in ids}
    folders = {}
    for folder in result["folders"]:
        identifier = folder.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in folders:
            raise ValueError("Folder IDs must be unique")
        if not isinstance(folder.get("name"), str) or not folder["name"].strip() or len(folder["name"]) > 80:
            raise ValueError("A submenu needs a name (up to 80 characters)")
        if not isinstance(folder.get("icon", ""), str) or len(folder.get("icon", "")) > 80:
            raise ValueError("Invalid submenu icon")
        if not isinstance(folder.get("actions"), list) or len(folder["actions"]) > 6:
            raise ValueError("A submenu supports up to six items")
        folders["folder:" + identifier] = folder
    actions |= set(folders)
    for folder in folders.values():
        if any(action not in actions - {"", "application"} for action in folder["actions"]):
            raise ValueError("Unknown submenu action")

    def check_folder(action, path):
        if action in path:
            raise ValueError("A submenu cannot contain itself, even through another submenu")
        if len(path) >= 8:
            raise ValueError("Submenus support up to eight levels")
        for child in folders[action]["actions"]:
            if child in folders:
                check_folder(child, path + [action])
    for action in folders:
        check_folder(action, [])
    if not isinstance(result["slotAppearance"], list) or len(result["slotAppearance"]) != 8:
        raise ValueError("Eight segment appearances are required")
    for style in result["slotAppearance"]:
        if not isinstance(style, dict) or any(k not in ("name", "icon") or not isinstance(v, str) or len(v) > 80 for k, v in style.items()):
            raise ValueError("Invalid segment label or icon")
    if not isinstance(result["appearance"], dict):
        raise ValueError("Invalid action appearance")
    for action, style in result["appearance"].items():
        if action not in actions or not isinstance(style, dict) or any(k not in ("name", "icon") or not isinstance(v, str) or len(v) > 80 for k, v in style.items()):
            raise ValueError("Invalid action label or icon")
    if len(result["slots"]) != 8 or any(x not in actions for x in result["slots"]):
        raise ValueError("The ring needs eight valid slots")
    profile_ids = set()
    for profile in result["profiles"]:
        if not profile.get("id") or profile["id"] in profile_ids or not profile.get("process") or not profile.get("name"):
            raise ValueError("Invalid application profile")
        profile_ids.add(profile["id"])
        if any(x not in actions - {"application", "macros", ""} for x in profile.get("actions", [])):
            raise ValueError("Unknown profile action")
        if len(profile.get("actions", [])) > 6:
            raise ValueError("At most six actions in a submenu")
    seen = set()
    for binding in result["bindings"]:
        key = (binding.get("profile", ""), binding.get("key", "").lower())
        if key in seen or not key[1] or binding.get("action") not in actions - {""} - set(GROUPS) - set(folders):
            raise ValueError("Invalid or duplicate shortcut")
        if key[0] and key[0] not in profile_ids:
            raise ValueError("Unknown shortcut profile")
        seen.add(key)
    return result


class Config:
    path: Path
    value: dict

    def __init__(self):
        self.path = data_dir() / "settings.json"
        stored = json.loads(self.path.read_text("utf-8")) if self.path.exists() else copy.deepcopy(DEFAULT)
        self.value = validate(stored)
        if stored["version"] != self.value["version"]:
            self.save(self.value)

    def save(self, value):
        value = validate(value)
        temporary = self.path.with_suffix(".new")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")
        os.replace(temporary, self.path)
        self.value = value
