import logging
from datetime import datetime
import colorlog
from configuration import LOG_LEVEL
import os
import sys


def get_logger():
    # Create a logger and set its level to LOG_LEVEL
    log = logging.getLogger()
    log.setLevel(LOG_LEVEL)
    # Create a formatter with colorlog's ColoredFormatter
    if not log.handlers:
        formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s %(levelname)s: %(message)s",
            datefmt="%d-%m-%Y %H:%M:%S",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "bold_white",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )

        # Create a console handler and set the formatter
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        # Add the console handler to the logger
        log.addHandler(console_handler)
    return log


log = get_logger()

