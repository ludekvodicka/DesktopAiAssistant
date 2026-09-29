import sys
from desktop_ai_assistant.bridge import native_host

if __name__ == "__main__":
    if sys.argv[1:] == ["--version"]:
        from desktop_ai_assistant import __version__
        print(__version__)
        raise SystemExit(0)
    sys.argv.insert(1, "--native-host")
    raise SystemExit(native_host())
