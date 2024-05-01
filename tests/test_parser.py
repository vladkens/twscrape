import json
import os
from pathlib import Path
from typing import (
    Any,
    AsyncContextManager,
    Callable,
    List,
    Optional,
)

import aiofiles
import typer
from twscrape import API, gather, parse_tweet
from twscrape.logger import set_log_level
from twscrape.models import PollCard, SummaryCard, Tweet, User, UserRef

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "mocked-data"
os.makedirs(DATA_DIR, exist_ok=True)

set_log_level("DEBUG")

