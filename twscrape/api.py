import asyncio
import json
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import aiohttp
from httpx import Response

from .accounts_pool import AccountsPool
from .constants import GQL_FEATURES
from .constants import GQL_URL
from .exceptions import TwitterScraperException
from .queue_client import QueueClient
from .utils import encode_params

class TwitterScraper:
    def __init__(
        self,
        accounts_pool: AccountsPool,
        queue_client: QueueClient,
    ):
        self.accounts_pool = accounts_pool
        self.queue_client = queue_client

    async def fetch(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Fetches data from the GraphQL API.

        Args:
            query (str): The GraphQL query to be executed.
            variables (Optional[Dict[str, Any]], optional): Variables for the query. Defaults to None.

        Raises:
            TwitterScraperException: If the request fails or the response is not valid.

        Returns:
            Dict[str, Any]: The response data as a dictionary.
        """
        account = await self.accounts_pool.get()
        headers = {
            "Authorization": f"Bearer {account.token}",
            "User-Agent": "TwitterScraper/1.0",
            "X-Twitter-Active-User": "yes",
            "X-Twitter-Client-Language": "en",
            "X-Twitter-Client-Version": "1.0",
            "X-Twitter-Recursion-Method": "get",
        }

        params = encode_params(
            features=GQL_FEATURES,
            dry_run=False,
            canonical_url="",
            timeline_type="combined",
        )

        async with aiohttp.ClientSession() as session:
            async with session.post(GQL_URL, json={"query": query, "variables": variables}, headers=headers, params=params) as resp:
                if resp.status != 200:
                    return await self._handle_response_error(resp)

                data = await resp.json()
                return data

    async def _handle_response_error(self, response: Response) -> Dict[str, Any]:
        """Handles errors in the response.

        Args:
            response (Response): The response object.

        Raises:
            TwitterScraperException: If the response contains an error.

        Returns:
            Dict[str, Any]: The response data as a dictionary.
        """
        error_data = await response.json()
        raise TwitterScraperException(error_data.get("errors")[0].get("message"))
