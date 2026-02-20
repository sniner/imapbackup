import argparse
import logging
import pathlib
import sys

import yaml

from imapbackup import jobs

log = logging.getLogger(__name__)


def parse_arguments():
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

    subparsers = parser.add_subparsers(dest="subcommand")

    list_parser = subparsers.add_parser(
        "list",
        description="List available folders on imap server",
    )
    list_parser.add_argument(
        "--job",
        type=pathlib.Path,
        required=True,
        help="YAML file with job descriptions",
    )

    backup_parser = subparsers.add_parser(
        "backup",
        description="Backup mails to local storage",
    )
    backup_parser.add_argument(
        "--job",
        type=pathlib.Path,
        required=True,
        help="YAML file with job descriptions",
    )
    backup_parser.add_argument(
        "destination",
        type=pathlib.Path,
        nargs="?",
        default=pathlib.Path("./backup"),
        help="Destination base directory",
    )

    return parser.parse_args()


def run_job(job: dict, args: argparse.Namespace):
    log.info(f"Job item: {job['name']}")

    if args.subcommand == "list":
        jobs.folder_list(job)
    elif args.subcommand == "backup":
        jobs.backup(job, args.destination)


def setup_logger(loglevel=logging.INFO, logfile=None):
    logger_format = "%(asctime)s %(levelname)s -- %(message)s"
    if logfile:
        logging.basicConfig(filename=logfile, level=loglevel, format=logger_format)
    else:
        logging.basicConfig(stream=sys.stderr, level=loglevel, format=logger_format)
    return logging.getLogger(__name__)


def main():
    args = parse_arguments()

    log = setup_logger(
        logfile=args.logfile, loglevel=logging.DEBUG if args.verbose else logging.INFO
    )
    logging.getLogger("imapclient").setLevel(logging.WARNING)
    logging.getLogger("imapbackup.cas").setLevel(logging.INFO)
    log.info("START")

    try:
        with open(args.job) as j:
            jobs = yaml.safe_load(j)

        for job_name, job in jobs.items():
            job["name"] = job_name
            run_job(job, args)
    except Exception as exc:
        log.exception("Fatal error: %s", exc)
    except KeyboardInterrupt:
        log.warning("Interrupted!")
    finally:
        log.info("FINISHED")


if __name__ == "__main__":
    main()


# vim: set et sw=4 ts=4:
