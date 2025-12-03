from dataclasses import dataclass
from typing import Dict, List, Sequence

from deadline_calculator import DeadlineCalculator
from sharepoint_requests_reader import SharePointRequestsReader


@dataclass(frozen=True)
class RequestDataset:
    """Aggregated data needed by the UI layer."""

    todo_requests: List[dict]
    grouped_requests: Dict[str, List[dict]]
    state_cache: Dict[str, int]
    meta_cache: Dict[str, str]
    processed_requests: List[dict]


class RequestDataService:
    """
    Facade responsible for retrieving, transforming, and grouping SharePoint data.
    Keeps UI code lean and focused on presentation (SoC / SOLID: SRP).
    """

    def __init__(
        self,
        reader: SharePointRequestsReader | None = None,
        calculator: DeadlineCalculator | None = None,
        *,
        categories: Sequence[str] | None = None,
    ):
        self.reader = reader or SharePointRequestsReader()
        self.calculator = calculator or DeadlineCalculator()
        self.categories = list(
            categories
            if categories is not None
            else ["Request", "Staff Movement", "Inquiry", "Information", "Others"]
        )

    def get_categories(self) -> list[str]:
        """Exposes configured categories without allowing callers to mutate state."""
        return list(self.categories)

    def load(
        self,
        *,
        limit_dates: int = 1,
        include_unread: bool = True,
    ) -> RequestDataset:
        """Fetches raw requests, enriches them, and returns grouped datasets."""
        raw_requests = self.reader.fetch_active_requests(
            limit_dates=limit_dates,
            include_unread=include_unread,
        )
        processed_requests = self.calculator.process_requests(raw_requests)

        state_cache = {req["id"]: req.get("unread_emails", 0) for req in processed_requests}
        meta_cache = {req["id"]: req.get("modified_at") for req in processed_requests}

        grouped_requests: Dict[str, List[dict]] = {cat: [] for cat in self.categories}
        for req in processed_requests:
            target_category = self._resolve_category(req.get("category"))
            grouped_requests[target_category].append(req)

        todo_requests = [req for req in processed_requests if self._is_todo_status(req.get("status", ""))]

        # Remove empty entries to avoid empty tabs downstream.
        grouped_requests = {k: v for k, v in grouped_requests.items() if v}

        return RequestDataset(
            todo_requests=todo_requests,
            grouped_requests=grouped_requests,
            state_cache=state_cache,
            meta_cache=meta_cache,
            processed_requests=processed_requests,
        )

    def update_request_properties(
        self,
        request_id: str,
        *,
        status: str | None = None,
        priority: str | None = None,
        category: str | None = None,
    ) -> bool:
        """
        Persists property changes while keeping the UI layer decoupled from SharePoint.
        """
        if not request_id:
            return False

        return self.reader.update_request_metadata(
            request_id,
            new_status=status,
            new_priority=priority,
            new_category=category,
        )

    def _resolve_category(self, raw_value: str | None) -> str:
        if not raw_value:
            return "Others"

        raw = str(raw_value).lower()
        for category in self.categories:
            if category.lower() in raw:
                return category
        return "Others"

    @staticmethod
    def _is_todo_status(status_value: str | None) -> bool:
        if not status_value:
            return False
        normalized = str(status_value).lower()
        return "pending" in normalized or "progress" in normalized

