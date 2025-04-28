import asyncio
import os

import httpx

from twscrape import API


async def download_file(client: httpx.AsyncClient, url: str, outdir: str):
    filename = url.split("/")[-1].split("?")[0]
    outpath = os.path.join(outdir, filename)

    async with client.stream("GET", url) as resp:
        with open(outpath, "wb") as f:
            async for chunk in resp.aiter_bytes():
                f.write(chunk)


async def load_user_media(api: API, user_id: int, outdir: str):
    os.makedirs(outdir, exist_ok=True)
    all_photos = []
    all_videos = []

    async for doc in api.user_media(user_id):
        all_photos.extend([x.url for x in doc.media.photos])
        for video in doc.media.videos:
            variant = sorted(video.variants, key=lambda x: x.bitrate)[-1]
            all_videos.append(variant.url)

    async with httpx.AsyncClient() as client:
        await asyncio.gather(
            *[download_file(client, url, outdir) for url in all_photos],
            *[download_file(client, url, outdir) for url in all_videos],
        )


async def main():
    api = API()
    await load_user_media(api, 2244994945, "data_media")


if __name__ == "__main__":
    asyncio.run(main())
