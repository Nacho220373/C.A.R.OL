from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from deadline_calculator import DeadlineCalculator
from sharepoint_requests_reader import SharePointRequestsReader


class RequestService:
    """
    Facade that groups all SharePoint-driven operations used by the UI layer.
    Handles caching, concurrency and keeps business logic out of the view code.
    """

    def __init__(
        self,
        reader: SharePointRequestsReader | None = None,
        calculator: DeadlineCalculator | None = None,
        *,
        file_cache_ttl: int = 180,
        max_workers: int = 8,
    ):
        self.reader = reader or SharePointRequestsReader()
        self.calculator = calculator or DeadlineCalculator()
        self.file_cache_ttl = file_cache_ttl
        self.max_workers = max_workers
        self._file_cache: dict[str, dict] = {}
        self._cache_lock = threading.Lock()

    # ----------- Public API -----------
    def ensure_drive_ready(self):
        """
        Triggers drive discovery ahead of time to hide latency from the UI thread.
        """
        self.reader._get_drive_id()

    def load_requests(
        self,
        *,
        limit_dates: int = 1,
        hydrate_unread: bool = True,
        force_unread_refresh: bool = False,
    ):
        """
        Returns processed requests with calculated deadline metadata and unread counts.
        """
        raw_requests = self.reader.fetch_active_requests(
            limit_dates=limit_dates,
            include_unread_scan=False,
        )

        if hydrate_unread and raw_requests:
            raw_requests = self._with_unread_counts(raw_requests, force_unread_refresh)

        return self.calculator.process_requests(raw_requests)

    def get_request_files(self, request_id: str, *, force_refresh: bool = False):
        return self._get_files(request_id, force_refresh=force_refresh)

    def download_file(self, download_url: str, filename: str):
        return self.reader.download_file_locally(download_url, filename)

    def update_request_metadata(self, item_id, new_status=None, new_priority=None):
        result = self.reader.update_request_metadata(item_id, new_status, new_priority)
        if result:
            self.invalidate_request(item_id)
        return result

    def invalidate_request(self, request_id: str):
        with self._cache_lock:
            self._file_cache.pop(request_id, None)

    # ----------- Internal helpers -----------
    def _with_unread_counts(self, requests_list, force_refresh):
        def hydrate(req):
            files = self._get_files(req["id"], force_refresh=force_refresh)
            unread = sum(1 for f in files if self._is_unread_email(f))
            enriched = req.copy()
            enriched["unread_emails"] = unread
            return enriched

        workers = min(self.max_workers, max(1, len(requests_list)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(hydrate, requests_list))

    def _get_files(self, request_id, force_refresh=False):
        now = time.time()
        with self._cache_lock:
            cached = self._file_cache.get(request_id)
            if (
                cached
                and not force_refresh
                and (now - cached["ts"]) < self.file_cache_ttl
            ):
                return cached["files"]

        files = self.reader.get_request_files(request_id)

        with self._cache_lock:
            self._file_cache[request_id] = {"files": files, "ts": time.time()}

        return files

    @staticmethod
    def _is_unread_email(file_info):
        name = str(file_info.get("name", "")).lower()
        status = file_info.get("status")
        is_email = name.endswith(".eml") or name.endswith(".msg")
        return is_email and status == "To Be Reviewed"
