"""Abstract base class for TikTok search providers.

Allows swapping between Playwright scraping, TikAPI, Apify, etc.
without changing business logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TikTokResult:
    """A single TikTok video search result."""

    video_url: str
    video_id: str
    creator_username: str
    creator_profile_url: str
    caption: str
    view_count: int
    like_count: int = 0
    comment_count: int = 0


class TikTokProvider(ABC):
    """Interface for TikTok search providers."""

    @abstractmethod
    def search(self, query: str, max_results: int = 10) -> list[TikTokResult]:
        """
        Search TikTok for videos matching the query.

        Args:
            query: Search string (e.g., "Nike Air Max review")
            max_results: Maximum results to return

        Returns:
            List of TikTokResult sorted by relevance/view count
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Clean up resources (browser instances, API connections, etc.)."""
        ...
