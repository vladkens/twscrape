import asyncio
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass
class Seen:
    method: str
    target: str
    headers: dict[str, str]
    raw_headers: list[str]
    body: bytes


@dataclass
class Reply:
    status: int = 200
    body: bytes = b"{}"
    headers: list[str] = field(default_factory=list)


@dataclass
class LocalServer:
    port: int
    seen: list[Seen]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


@asynccontextmanager
async def local_server(
    reply: Callable[[Seen], Reply | None] = lambda _: Reply(),
) -> AsyncGenerator[LocalServer]:
    """Loopback HTTP server, also usable as a proxy; a `None` reply drops the connection."""

    seen: list[Seen] = []

    async def handle(rd: asyncio.StreamReader, wr: asyncio.StreamWriter):
        head = await rd.readuntil(b"\r\n\r\n")
        line, *raw_headers = head.decode().strip().split("\r\n")
        headers = {k.lower(): v.strip() for k, v in (x.split(":", 1) for x in raw_headers)}
        body = await rd.readexactly(int(headers.get("content-length", 0)))

        method, target, _ = line.split(" ", 2)
        req = Seen(method, target, headers, raw_headers, body)
        seen.append(req)

        rep = reply(req)
        if rep is None:
            wr.close()
            return

        lines = [
            f"HTTP/1.1 {rep.status} X",
            f"Content-Length: {len(rep.body)}",
            "Connection: close",
            *rep.headers,
        ]
        wr.write("\r\n".join(lines).encode() + b"\r\n\r\n" + rep.body)
        await wr.drain()
        wr.close()

    srv = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield LocalServer(srv.sockets[0].getsockname()[1], seen)
    finally:
        srv.close()
