"""Point d'entree de ``python -m mascotforge``."""
from __future__ import annotations

import sys

from mascotforge import cli


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        try:
            from mascotforge.mcp_server import run
        except ModuleNotFoundError as exc:
            if exc.name == "mcp":
                print(
                    "Le paquet mcp est absent. Installez les dependances avec "
                    "python -m pip install -r requirements.txt.",
                    file=sys.stderr,
                )
                return 1
            raise
        run()
        return 0
    return cli.main()


if __name__ == "__main__":
    raise SystemExit(main())
