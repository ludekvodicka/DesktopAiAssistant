import sys
from desktop_ai_assistant.shared.desktop.autoupdate.helper import UpdateHelper

if __name__ == "__main__":
    # The one-file host is also the update helper: the app copies it out of the staged
    # folder and starts it with this flag. A browser passes an extension origin, never it.
    if UpdateHelper.requested(sys.argv):
        raise SystemExit(UpdateHelper.main(sys.argv[1:]))
    if sys.argv[1:] == ["--version"]:
        from desktop_ai_assistant import __version__
        print(__version__)
        raise SystemExit(0)
    from desktop_ai_assistant.bridge import native_host
    sys.argv.insert(1, "--native-host")
    raise SystemExit(native_host())
