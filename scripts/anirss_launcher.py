"""PyInstaller entry point that preserves AniRSS package import semantics."""

from anirss.app import main

if __name__ == "__main__":
    raise SystemExit(main())
