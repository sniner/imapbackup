"""Copy emails between IMAP mailboxes."""

import argparse
import logging
import pathlib
import sys

from imapbackup import conf, jobs
from imapbackup.cli import setup_logger

log = logging.getLogger(__name__)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__
    )

    parser.add_argument(
        "--logfile",
        type=pathlib.Path,
        help="Log file path",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Set log level to DEBUG",
    )
    parser.add_argument(
        "--allow-exec",
        action="store_true",
        help="Allow execution of _cmd fields in configuration file",
    )
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        help="Configuration file (TOML)",
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    subparsers.add_parser(
        "folders",
        description="Show available folders in source mailbox",
    )

    copy_parser = subparsers.add_parser(
        "copy",
        description="Copy mails from source to destination mailbox",
    )
    copy_parser.add_argument(
        "--idle",
        action="store_true",
        help="Keep connected to server",
    )

    args = parser.parse_args()
    if args.subcommand is None:
        parser.print_help()
        raise SystemExit(2)
    if args.config is None:
        parser.error("the following arguments are required: --config")
    return args


def main() -> None:
    args = parse_arguments()

    setup_logger(
        logfile=args.logfile,
        loglevel=logging.DEBUG if args.verbose else logging.INFO,
    )
    log.info("START")

    if args.config.suffix.lower() != ".toml":
        print(f"Error: configuration file must be TOML format (.toml), got: {args.config}", file=sys.stderr)
        sys.exit(1)

    try:
        config = conf.load(args.config, allow_exec=args.allow_exec)
        source = conf.find(config.jobs, "role", "source")
        destination = conf.find(config.jobs, "role", "destination")

        if source is None or destination is None:
            log.error("Job missing source or destination role")
            return

        if args.subcommand == "folders":
            jobs.folder_list(source)
        elif args.subcommand == "copy":
            log.info(f"Copy job: {source.name} -> {destination.name}")
            jobs.copy(source, destination, idle=args.idle)
    except Exception as exc:
        log.error("Fatal error: %s", exc)
    except KeyboardInterrupt:
        log.warning("Interrupted!")
    finally:
        log.info("FINISHED")


if __name__ == "__main__":
    main()
