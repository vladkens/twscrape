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
            limits=Limits(timeout=10.0, max_redirects=10, max_connections=10, max_content_size=10485760),
        ))

        response = client.get("https://twitter.com/elonmusk")
        if response.status_code != 200:
            print(f"Failed to download the scripts: HTTP status code {response.status_code}")
            exit(1)

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
                try:
                    with open(cache_path) as fp:
                        urls[i - 1] = fp.read()
                except Exception as e:
                    print(f"Failed to read the cache file {cache_path}: {e}")
                    urls[i - 1] = ""
                continue

            print(f"({i:3d} / {len(urls):3d}) {x}")
            try:
                response = client.get(x)
            except Exception as e:
                print(f"Failed to download the script {x}: {e}")
                urls[i - 1] = ""
                continue

            if response.status_code != 200:
                print(f"Failed to download the script {x}: HTTP status code {response.status_code}")
                urls[i - 1] = ""
                continue

            try:
                with open(cache_path, "w") as fp:
                    fp.write(response.text)
                urls[i - 1] = response.text
            except Exception as e:
                print(f"Failed to write the cache file {cache_path}: {e}")
                urls[i - 1] = ""

        return urls


def extract_pairs(scripts: list[str]) -> dict[str, str]:
    """Return the dictionary of operation names and query IDs."""
    all_pairs = collections.defaultdict(str)
    last_end = 0
    for txt in scripts:
        for match in REGEX_PATTERN.finditer(txt, last_end):
            query_id, operation_name = match.groups()
            all_pairs[operation_name] = query_id
            last_end = match.end()

    return dict(all_pairs)


def print_pairs(all_pairs: dict[str, str]):
    """Print the pairs of operation names and query IDs."""
    for k, v in all_pairs.items():
        print(f'OP_{k} = "{v}/{k}"')

    print("-" * 40)

    for x in ops:
        try:
            print(f'OP_{x} = "{all_pairs[x]}/{x}"')
        except KeyError:
            print(f'OP_{x} = "???/{x}"')


if __name__ == "__main__":
    ops = [x.strip() for x in open("./twscrape/api.py").read().split("\n")]
    ops = [x.split("=")[0].removeprefix("OP_").strip() for x in ops if x.startswith("OP_")]

    if not ops:
        print("The ops list is empty")
        exit(1)

    scripts = get_scripts()
    all_pairs = extract_pairs(scripts)
    print_pairs(all_pairs)
