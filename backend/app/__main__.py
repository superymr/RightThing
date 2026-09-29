"""支持 `python -m app.cli` 与 `python -m app`。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
