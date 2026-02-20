from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from imapbackup import archive, cas, jobs

log = logging.getLogger(__name__)


def parse_arguments():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )

    parser.add_argument("--logfile", type=pathlib.Path, help="Log file path")
    parser.add_argument("--verbose", action="store_true", help="Set log level to DEBUG")

    subparsers = parser.add_subparsers(dest="subcommand")

    stats_parser = subparsers.add_parser("stats", description="Show stats of email archive")
    stats_parser.add_argument(
        "--docuware",
        action="store_true",
        help="Email archive is Docuware archive",
    )
    stats_parser.add_argument("source", type=pathlib.Path, help="Email archive directory")

    import_parser = subparsers.add_parser(
        "import",
        description="Import emails from source archive to destination",
    )
    import_parser.add_argument(
        "--docuware",
        action="store_true",
        help="Source archive is a Docuware email archive",
    )
    import_parser.add_argument(
        "--move",
        action="store_true",
        help="Move emails, i.e. remove emails from source after backup",
    )
    import_parser.add_argument(
        "source",
        type=pathlib.Path,
        help="Directory from which you want to copy/move the mails",
    )
    import_parser.add_argument("destination", type=pathlib.Path, help="Archive directory")

    addr_parser = subparsers.add_parser(
        "addresses",
        description="Show mail addresses of all emails in archive",
    )
    addr_parser.add_argument(
        "--docuware",
        action="store_true",
        help="Directory is a Docuware archive",
    )
    addr_parser.add_argument(
        "source",
        type=pathlib.Path,
        help="Archive directory",
    )

    dbupd_parser = subparsers.add_parser(
        "db-from-archive",
        description="Update metadata database by reading all archive items",
    )
    dbupd_parser.add_argument(
        "--mailbox",
        type=str,
        help="Mailbox identifier (matching a job file entry)",
    )
    dbupd_parser.add_argument(
        "source",
        type=pathlib.Path,
        help="Email archive directory",
    )

    return parser.parse_args()


def setup_logger(loglevel=logging.INFO, logfile=None):
    logger_format = "%(asctime)s %(levelname)s -- %(message)s"

    if logfile:
        logging.basicConfig(filename=logfile, level=loglevel, format=logger_format)
    else:
        logging.basicConfig(stream=sys.stderr, level=loglevel, format=logger_format)
    logger = logging.getLogger(__name__)
    logger.info("START")
    return logger


def run():
    args = parse_arguments()

    log = setup_logger(
        logfile=args.logfile,
        loglevel=logging.DEBUG
        if args.verbose
        else logging.INFO
        if args.logfile
        else logging.WARNING,
    )
    logging.getLogger("imapbackup.cas").setLevel(logging.INFO)

    def _archive(path: pathlib.Path) -> archive.MailArchive:
        return (archive.DocuwareMailArchive if args.docuware else archive.MailArchive)(path)

    if args.subcommand == "stats":
        count, size = _archive(args.source).stats()
        print(f"{args.source}: {count} emails in archive, {size:,} bytes total")
    elif args.subcommand == "addresses":
        for where, addr in _archive(args.source).addresses():
            print(where, addr)
    elif args.subcommand == "import":
        source = _archive(args.source)
        destination = cas.ContentAdressedStorage(args.destination, suffix=".eml")
        try:
            source.archive_to_cas(destination, move=args.move)
        except Exception as exc:
            log.error("Backup failed: %s", exc)
    elif args.subcommand == "db-from-archive":
        jobs.update_db_from_archive(args.source, mailbox=args.mailbox)


def main():
    try:
        run()
    except KeyboardInterrupt:
        log.warning("Interrupted!")


if __name__ == "__main__":
    main()

# vim: set et sw=4 ts=4:
