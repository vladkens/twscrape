import json
import os
import re
from contextlib import ExitStack
from httpx import Client, Limits
from urllib.parse import urlparse, urljoin
import fake_useragent

import twscrape.api  # noqa: F401

REGEX_PATTERN = re.compile(r'queryId:"(?P<query_id>.+?)".+?operationName:"(?P<operation_name>.+?)"')


def script_url(k: str, v: str) -> str:
    """Return the script URL for the given key and version."""
    return f"https://abs.twimg.com/responsive-web/client-web/{k}.{v}.js"


def get_scripts() -> list[str]:
    """Return the list of scripts from the given URL."""
    cache_dir = os.path.join("/tmp", "twscrape-ops")
    os.makedirs(cache_dir, exist_ok=True)

    with ExitStack() as stack:
        client = stack.enter_context(httpx.Client(
            headers={"user-agent": fake_useragent.UserAgent().chrome},
            limits=Limits(timeout=10.0),
        ))

        response = client.get("https://twitter.com/elonmusk")
        response.raise_for_status()

        urls = []
        scripts = response.text.split('e=>e+"."+')[1].split('[e]+"a.js"')[0]
        try:
            for k, v in json.loads(scripts).items():
                urls.append(script_url(k, f"{v}a"))
        except json.JSONDecodeError as e:
            print(scripts)
            print(e)
            exit(1)

        v = response.text.split("/client-web/main.")[1].split(".")[0]
        urls.append(script_url("main", v))

        urls = [
            x
            for x in urls
            if "/i18n/" not in x and "/icons/" not in x and "react-syntax-highlighter" not in x
        ]

        for i, x in enumerate(urls, 1):
            cache_path = os.path.join(cache_dir, urlparse(x).path.split("/")[-1])
            if os.path.exists(cache_path):
                with open(cache_path) as fp:
                    urls[i - 1] = fp.read()
                continue

            print(f"({i:3d} / {len(urls):3d}) {x}")
            response = client.get(x)
            response.raise_for_status()

            with open(cache_path, "w") as fp:
                fp.write(response.text)
            urls[i - 1] = response.text

        return urls


def extract_pairs(scripts: list[str]) -> dict[str, str]:
    """Return the dictionary of operation names and query IDs."""
    all_pairs = collections.defaultdict(str)
    for txt in scripts:
        for match in REGEX_PATTERN.findall(txt):
            query_id, operation_name = match
            all_pairs[operation_name] = query_id

    return dict(all_pairs)


def print_pairs(all_pairs: dict[str, str]):
    """Print the pairs of operation names and query IDs."""
    for k, v in all_pairs.items():
        print(f'OP_{k} = "{v}/{k}"')

    print("-" * 40)

    for x in ops:
        print(f'OP_{x} = "{all_pairs.get(x, "???")}/{x}"')


if __name__ == "__main__":
    ops = [x.strip() for x in open("./twscrape/api.py").read().split("\n")]
    ops = [x.split("=")[0].removeprefix("OP_").strip() for x in ops if x.startswith("OP_")]

    scripts = get_scripts()
    all_pairs = extract_pairs(scripts)
    print_pairs(all_pairs)
