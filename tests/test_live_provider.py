import copy
import os
import threading
import pytest
from desktop_ai_assistant.config import DEFAULT
from desktop_ai_assistant.providers import transform

pytestmark = pytest.mark.skipif(os.environ.get("DESKTOP_AI_LIVE_TESTS") != "1", reason="Explicit live subscription check")


@pytest.mark.parametrize("action,text,expected", [
    ("english_formal", "Dobrý den, zítra máme schůzku.", "tomorrow"),
    ("english_social", "Ahoj, koukni na https://Example.test/SomeID a dej mi vědět.", "https://Example.test/SomeID"),
    ("czech", "Vcera jsme byly v praze.", "Praze"),
])
def test_live_subscription_profiles(action, text, expected):
    config = copy.deepcopy(DEFAULT)
    result = transform(config, action, text, threading.Event())
    assert expected in result
