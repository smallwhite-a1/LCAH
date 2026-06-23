from __future__ import annotations

import sys

from lcah.cli import build_agent, build_arg_parser
from lcah.tui.app import LCAHTuiApp


def main(argv=None):
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.prompt:
        print("LCAH TUI does not accept one-shot prompts; start the TUI and type there.", file=sys.stderr)
        return 2
    agent = build_agent(args)
    LCAHTuiApp(agent).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
