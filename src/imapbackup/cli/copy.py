import argparse
import logging
import pathlib
import sys
import yaml

from imapbackup import jobs, conf

log = logging.getLogger(__name__)


def parse_arguments():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)

    parser.add_argument(
        "--logfile",
        type=pathlib.Path,
        help="Log file path"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Set log level to DEBUG"
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    list_parser = subparsers.add_parser(
        "list", description="Show available messages in source mailbox"
    )
    list_parser.add_argument(
        "--job",
        type=pathlib.Path,
        required=True,
        help="YAML file with job descriptions"
    )

    backup_parser = subparsers.add_parser(
        "copy", description="Copy mails from source to destination mailbox"
    )
    backup_parser.add_argument(
        "--job",
        type=pathlib.Path,
        required=True,
        help="YAML file with job descriptions"
    )
    backup_parser.add_argument(
        "--idle",
        action="store_true",
        help="Keep connected to server"
    )

    return parser.parse_args()

def setup_logger(loglevel=logging.INFO, logfile=None):
    logger_format = '%(asctime)s %(levelname)s -- %(message)s'
    if logfile:
        logging.basicConfig(filename=logfile,
                            level=loglevel,
                            format=logger_format)
    else:
        logging.basicConfig(stream=sys.stderr,
                            level=loglevel,
                            format=logger_format)
    return logging.getLogger(__name__)


def main():
    global log

    args = parse_arguments()

    log = setup_logger(logfile=args.logfile, loglevel=logging.DEBUG if args.verbose else logging.INFO)
    logging.getLogger("imapclient").setLevel(logging.WARNING)
    logging.getLogger("imapbackup.cas").setLevel(logging.INFO)
    log.info("START")

    try:
        config = conf.load(args.job)
        source = conf.find(config, "role", "source")
        destination = conf.find(config, "role", "destination")

        if args.subcommand=="list":
            jobs.folder_list(source)
        elif args.subcommand=="copy":
            log.info(f"Copy job: {source.get('name', '?')} -> {destination.get('name', '?')}")
            jobs.copy(source, destination, idle=args.idle)
    except Exception as exc:
        log.error("Fatal error: %s", exc)
    except KeyboardInterrupt:
        log.warning("Interrupted!")
    finally:
        log.info("FINISHED")


if __name__ == "__main__":
    main()


# vim: set et sw=4 ts=4:

