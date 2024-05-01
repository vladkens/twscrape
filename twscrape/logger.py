import sys
from typing import Literal
from loguru import logger

def set\_logger(log\_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = 'INFO') -> None:
"""
Sets up the logger with the specified log level.

:param log\_level: The log level to use. Default is 'INFO'.
:type log\_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
"""
logger.remove()
logger.add(sys.stderr, level=log\_level)

set\_logger()

logger.info('This is an info message')
logger.error('This is an error message')
