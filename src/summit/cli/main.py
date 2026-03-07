#!/usr/bin/env python3
"""
Unified entry point for summit CLI.

Usage: summit <subcommand> [args...]
"""
import argparse
import sys


SUBCOMMANDS = {
    "prs":         ("summit.prs",             "cycling/running personal records"),
    "kom":         ("summit.kom",             "segment KOM detection"),
    "activities":  ("summit.activities",      "YTD activity summary"),
    "check":       ("summit.updates",         "check for new activities/segments"),
    "generate":    ("summit.cli.generate",    "assemble org-mode output"),
    "setup":       ("summit.cli.setup",       "Phase 1 initial cache build"),
    "update":      ("summit.cli.update",      "Phase 2 manual cache refresh"),
    "auto-update": ("summit.cli.auto_update", "non-interactive systemd target"),
}


def main():
    parser = argparse.ArgumentParser(
        prog="summit",
        description="Garmin KOM & personal records tracker",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    for name, (_, help_text) in SUBCOMMANDS.items():
        subparsers.add_parser(name, help=help_text, add_help=False)

    # Parse only the subcommand; leave remaining args for the target module.
    args, remaining = parser.parse_known_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    module_path = SUBCOMMANDS[args.command][0]

    # Rewrite sys.argv so the target module's own argparse sees the right args.
    sys.argv = [f"summit {args.command}"] + remaining

    module = __import__(module_path, fromlist=["main"])
    module.main()


if __name__ == "__main__":
    main()
