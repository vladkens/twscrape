import os

from twscrape.accounts_pool import AccountsPool
from twscrape.db import DB


def get_pool(db_path: str):
    DB._init_once[db_path] = False
    if os.path.exists(db_path):
        os.remove(db_path)

    pool = AccountsPool(db_path)
    return pool
