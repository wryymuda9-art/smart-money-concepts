"""Enable ``python -m xauusd_agent ...`` (delegates to the CLI)."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
