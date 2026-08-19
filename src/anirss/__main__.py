"""Allow ``python -m anirss`` to launch the desktop application."""

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
