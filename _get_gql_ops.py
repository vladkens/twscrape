import json
import os
import re

import httpx
from fake_useragent import UserAgent

"""
docker run --rm -p "3128:3128/tcp" -p "1080:1080/tcp" -e "PROXY_LOGIN=user" -e "PROXY_PASSWORD=pass" tarampampam/3proxy
docker run --rm -p "3129:3128/tcp" -p "1081:1080/tcp" tarampampam/3proxy
"""

client = httpx.Client(headers={"user-agent": UserAgent().chrome}, follow_redirects=True)

with open("./twscrape/api.py") as fp:
    ops = [x.strip() for x in fp.read().split("\n")]
    ops = [x.split("=")[0].removeprefix("OP_").strip() for x in ops if x.startswith("OP_")]


def script_url(k: str, v: str):
    return f"https://abs.twimg.com/responsive-web/client-web/{k}.{v}.js"


def get_page_text(url: str):
    rep = client.get(url)
    rep.raise_for_status()
    if ">document.location =" not in rep.text:
        return rep.text

    url = rep.text.split('document.location = "')[1].split('"')[0]
    rep = client.get(url)
    rep.raise_for_status()
    if 'action="https://x.com/x/migrate" method="post"' not in rep.text:
        return rep.text

    data = {}
    for x in rep.text.split("<input")[1:]:
        name = x.split('name="')[1].split('"')[0]
        value = x.split('value="')[1].split('"')[0]
        data[name] = value

    rep = client.post("https://x.com/x/migrate", json=data)
    rep.raise_for_status()

    return rep.text


def get_scripts():
    cache_dir = "/tmp/twscrape-ops"
    os.makedirs(cache_dir, exist_ok=True)

    text = get_page_text("https://x.com/elonmusk")
    urls = []

    scripts = text.split('e=>e+"."+')[1].split('[e]+"a.js"')[0]
    try:
        for k, v in json.loads(scripts).items():
            urls.append(script_url(k, f"{v}a"))
    except json.decoder.JSONDecodeError as e:
        print(scripts)
        print(e)
        exit(1)

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
        rep = client.get(x)
        rep.raise_for_status()

        with open(cache_path, "w") as fp:
            fp.write(rep.text)
        scripts.append(rep.text)

    return scripts


all_pairs = {}
for txt in get_scripts():
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
