"""Entry point: python -m squidcode"""

import asyncio
import logging

import structlog

from squidcode.config import settings
from squidcode.main import run

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level, logging.INFO)
    ),
)

logger = structlog.get_logger()


def main():
    logger.info("squidcode.starting", version="0.1.0")
    asyncio.run(run())


if __name__ == "__main__":
    main()
