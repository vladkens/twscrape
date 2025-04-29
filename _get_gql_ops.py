import asyncio
import os
import re

import httpx

from twscrape.xclid import get_scripts_list, get_tw_page_text, script_url


async def get_scripts():
    cache_dir = "/tmp/twscrape-ops"
    os.makedirs(cache_dir, exist_ok=True)

    text = await get_tw_page_text("https://x.com/elonmusk")
    urls = list(get_scripts_list(text))

    v = text.split("/client-web/main.")[1].split(".")[0]
    urls.append(script_url("main", v))

    urls = [
        x
        for x in urls
        if "/i18n/" not in x and "/icons/" not in x and "react-syntax-highlighter" not in x
    ]

    scripts = []
    for i, x in enumerate(urls, 1):
        cache_path = os.path.join(cache_dir, x.split("/")[-1].split("?")[0])
        if os.path.exists(cache_path):
            with open(cache_path) as fp:
                scripts.append(fp.read())
            continue

        print(f"({i:3d} / {len(urls):3d}) {x}")
        rep = await httpx.AsyncClient().get(x)
        rep.raise_for_status()

        with open(cache_path, "w") as fp:
            fp.write(rep.text)
        scripts.append(rep.text)

    return scripts


async def main():
    with open("./twscrape/api.py") as fp:
        ops = [x.strip() for x in fp.read().split("\n")]
        ops = [x.split("=")[0].removeprefix("OP_").strip() for x in ops if x.startswith("OP_")]

    all_pairs = {}
    for txt in await get_scripts():
        pairs = re.findall(r'queryId:"(.+?)".+?operationName:"(.+?)"', txt)
        pairs = {op_name: op_id for op_id, op_name in pairs}

        for k, v in pairs.items():
            if k in all_pairs and v != all_pairs[k]:
                print(f"DIFF: {k} = {v} != {all_pairs[k]}")

            all_pairs[k] = v

    for k, v in all_pairs.items():
        print(f'OP_{k} = "{v}/{k}"')

    print("-" * 40)

    for x in ops:
        print(f'OP_{x} = "{all_pairs.get(x, "???")}/{x}"')


if __name__ == "__main__":
    asyncio.run(main())
