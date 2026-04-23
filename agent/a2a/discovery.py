"""
A2A Agent Discovery
Fetch Agent Cards from /.well-known/agent.json with TTL caching.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional

import aiohttp

from agent.a2a.models import AgentCard

logger = logging.getLogger(__name__)

DEFAULT_WELL_KNOWN_PATH = "/.well-known/agent.json"
DEFAULT_TTL_SECONDS = 300


class _CacheEntry:
    def __init__(self, card: AgentCard, timestamp: float):
        self.card = card
        self.timestamp = timestamp


class AgentDiscovery:
    """Discover external A2A agents and cache their AgentCards."""

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self._cache: Dict[str, _CacheEntry] = {}
        self._ttl = ttl_seconds
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def discover(self, url: str) -> Optional[AgentCard]:
        """
        Discover a single agent by fetching its AgentCard.
        
        Args:
            url: Base URL of the remote agent (e.g., http://localhost:8000).
                 The well-known path is appended automatically.
        
        Returns:
            AgentCard or None if discovery fails.
        """
        # Check cache first
        now = time.time()
        cached = self._cache.get(url)
        if cached and (now - cached.timestamp) < self._ttl:
            logger.debug(f"[AgentDiscovery] Cache hit for {url}")
            return cached.card

        # Build well-known URL
        well_known_url = url.rstrip("/") + DEFAULT_WELL_KNOWN_PATH

        try:
            session = await self._get_session()
            async with session.get(well_known_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    card = AgentCard.model_validate(data)
                    # Ensure URL is set if missing
                    if not card.url:
                        card.url = url.rstrip("/")
                    self._cache[url] = _CacheEntry(card, now)
                    logger.info(f"[AgentDiscovery] Discovered agent '{card.name}' at {url}")
                    return card
                else:
                    text = await resp.text()
                    logger.warning(f"[AgentDiscovery] Failed to discover {url}: HTTP {resp.status} {text[:200]}")
                    return None
        except Exception as e:
            logger.warning(f"[AgentDiscovery] Error discovering {url}: {e}")
            return None

    async def discover_all(self, urls: List[str]) -> List[AgentCard]:
        """
        Discover multiple agents concurrently.
        
        Args:
            urls: List of base URLs to discover.
        
        Returns:
            List of successfully discovered AgentCards.
        """
        tasks = [self.discover(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        cards: List[AgentCard] = []
        for url, result in zip(urls, results):
            if isinstance(result, AgentCard):
                cards.append(result)
            elif isinstance(result, Exception):
                logger.warning(f"[AgentDiscovery] Exception discovering {url}: {result}")
        logger.info(f"[AgentDiscovery] Discovered {len(cards)}/{len(urls)} agents")
        return cards

    def invalidate(self, url: str) -> None:
        """Invalidate cache entry for a URL."""
        self._cache.pop(url, None)

    def invalidate_all(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    async def close(self) -> None:
        """Close underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
