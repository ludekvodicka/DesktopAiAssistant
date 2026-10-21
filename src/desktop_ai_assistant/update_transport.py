import ssl

import certifi

from . import __version__
from .shared.desktop.autoupdate.transport import UpdateTransport


def create_update_transport() -> UpdateTransport:
    # Supplying cafile avoids adding OS roots, which can retain distrusted cross-signs.
    context = ssl.create_default_context(cafile=certifi.where())
    return UpdateTransport(f"DesktopAiAssistant/{__version__}", context=context)
