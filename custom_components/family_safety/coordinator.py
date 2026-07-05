"""Family Safety data hub."""

import contextlib
import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from urllib.parse import quote_plus

import asyncio

from homeassistant.core import HomeAssistant
from pyfamilysafety import FamilySafety
from pyfamilysafety.account import Account
from pyfamilysafety.exceptions import AggregatorException
from pyfamilysafety.helpers import API_TIMEZONE, localise_datetime
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed
)

from .const import NAME

_LOGGER = logging.getLogger(__name__)

SCREEN_TIME_RANGES: dict[str, int] = {
    "1d": 1,
    "7d": 7,
    "30d": 30,
}

WEB_ACTIVITY_ALLOW_STATUSES = ("Allowed", "Blocked")

MAX_ACTIVITY_ATTRIBUTE_ENTRIES = 50


def _milliseconds_to_minutes(value: Any) -> float:
    """Convert an API millisecond value to minutes."""
    try:
        return round((float(value or 0) / 1000) / 60, 2)
    except (TypeError, ValueError):
        return 0


def _range_datetimes(days: int) -> tuple[datetime, datetime]:
    """Return localised begin/end datetimes for an inclusive day range."""
    start_date = date.today() - timedelta(days=days - 1)
    start_time = localise_datetime(
        datetime.combine(start_date, time(0, 0, 0), tzinfo=API_TIMEZONE)
    )
    end_time = localise_datetime(
        datetime.combine(date.today(), time(23, 59, 59), tzinfo=API_TIMEZONE)
    )
    return start_time, end_time


def _format_api_datetime(value: datetime) -> str:
    """Format a datetime for Family Safety activity-report endpoints."""
    return quote_plus(value.strftime("%Y-%m-%dT%H:%M:%S%z"))


def _extract_activity_entries(raw_response: Any) -> list[dict[str, Any]]:
    """Extract activity entries from the currently undocumented API shapes."""
    if raw_response is None:
        return []

    if isinstance(raw_response, list):
        return [entry for entry in raw_response if isinstance(entry, dict)]

    if not isinstance(raw_response, dict):
        return []

    candidate_keys = (
        "webActivity",
        "webActivities",
        "searchActivity",
        "searchActivities",
        "activity",
        "activities",
        "activityItems",
        "items",
        "results",
        "value",
    )
    for key in candidate_keys:
        value = raw_response.get(key)
        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, dict)]

    entries: list[dict[str, Any]] = []
    for value in raw_response.values():
        if isinstance(value, list):
            entries.extend(entry for entry in value if isinstance(entry, dict))
    return entries


def _summarise_screen_time(
    raw_response: dict[str, Any] | None,
    start_time: datetime,
    end_time: datetime,
) -> dict[str, Any]:
    """Build a stable summary from a deviceScreenTimeUsage response."""
    usage_aggregates = {}
    if raw_response:
        usage_aggregates = raw_response.get("deviceUsageAggregates", {}) or {}

    device_usage = {}
    for device in usage_aggregates.get("deviceAggregates", []) or []:
        device_id = device.get("deviceId")
        if device_id is not None:
            device_usage[device_id] = _milliseconds_to_minutes(device.get("timeUsed"))

    total_ms = usage_aggregates.get("totalScreenTime", 0)
    return {
        "minutes": _milliseconds_to_minutes(total_ms),
        "total_milliseconds": total_ms or 0,
        "range_start": start_time.isoformat(),
        "range_end": end_time.isoformat(),
        "device_usage_minutes": device_usage,
    }


def _summarise_app_usage(raw_response: dict[str, Any] | None) -> dict[str, Any]:
    """Build today's app-usage summary from an appUsage response."""
    app_activity = []
    if raw_response:
        app_activity = raw_response.get("appActivity", []) or []

    usage_minutes: dict[str, float] = {}
    application_details: list[dict[str, Any]] = []
    for app in app_activity:
        if not isinstance(app, dict):
            continue
        display_name = app.get("displayName") or app.get("appId") or "Unknown"
        minutes = _milliseconds_to_minutes(app.get("usage"))
        usage_minutes[display_name] = round(
            usage_minutes.get(display_name, 0) + minutes,
            2,
        )
        application_details.append(
            {
                "app_id": app.get("appId"),
                "display_name": display_name,
                "minutes": minutes,
                "icon_url": app.get("iconUrl"),
            }
        )

    total_minutes = round(sum(usage_minutes.values()), 2)
    top_app = None
    top_minutes = 0
    if usage_minutes and total_minutes > 0:
        top_app, top_minutes = max(usage_minutes.items(), key=lambda item: item[1])

    return {
        "top_app": top_app,
        "top_minutes": top_minutes,
        "total_minutes": total_minutes,
        "application_usage_minutes": usage_minutes,
        "applications": application_details,
    }


class FamilySafetyCoordinator(DataUpdateCoordinator):
    """Family safety data updater."""

    def __init__(self,
                 hass: HomeAssistant,
                 family_safety: FamilySafety,
                 update_interval: int=60) -> None:
        """Init the coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            name=NAME,
            update_interval=timedelta(seconds=update_interval)
        )
        self.api: FamilySafety = family_safety
        self.screen_time_ranges: dict[str, dict[str, dict[str, Any]]] = {}
        self.application_usage_today: dict[str, dict[str, Any]] = {}
        self.web_activity_today: dict[str, dict[str, Any]] = {}
        self.search_activity_today: dict[str, dict[str, Any]] = {}

    async def _async_update_data(self):
        """Fetch and update data from the API."""
        try:
            async with asyncio.timeout(59):
                with contextlib.suppress(AggregatorException):
                    await self.api.update()
                await self._async_update_extra_data()
                return {
                    "screen_time_ranges": self.screen_time_ranges,
                    "application_usage_today": self.application_usage_today,
                    "web_activity_today": self.web_activity_today,
                    "search_activity_today": self.search_activity_today,
                }
        except Exception as err:
            raise UpdateFailed(f"Error communicating with API {err}") from err

    async def _async_update_extra_data(self) -> None:
        """Fetch additive per-account data not exposed by upstream entities."""
        try:
            async with asyncio.timeout(30):
                await asyncio.gather(
                    *[
                        self._async_update_account_extra_data(account)
                        for account in self.api.accounts
                    ]
                )
        except Exception as err:  # pragma: no cover - defensive: do not break old entities.
            _LOGGER.warning("Unable to update extended Family Safety data: %s", err)

    async def _async_update_account_extra_data(self, account: Account) -> None:
        """Fetch additive data for one Family Safety account."""
        self.application_usage_today[account.user_id] = _summarise_app_usage(
            account.application_usage
        )

        screen_time_ranges: dict[str, dict[str, Any]] = {}
        for key, days in SCREEN_TIME_RANGES.items():
            start_time, end_time = _range_datetimes(days)
            if key == "1d":
                screen_time_ranges[key] = _summarise_screen_time(
                    account.screentime_usage,
                    start_time,
                    end_time,
                )
                continue

            try:
                usage = await account.get_screentime_usage(
                    start_time=start_time,
                    end_time=end_time,
                )
                screen_time_ranges[key] = _summarise_screen_time(
                    usage.get("devices"),
                    start_time,
                    end_time,
                )
            except Exception as err:  # pragma: no cover - depends on remote API.
                _LOGGER.warning(
                    "Unable to update %s screen-time data for account %s: %s",
                    key,
                    account.user_id,
                    err,
                )
                screen_time_ranges[key] = _summarise_screen_time(
                    None,
                    start_time,
                    end_time,
                )

        self.screen_time_ranges[account.user_id] = screen_time_ranges
        self.web_activity_today[account.user_id] = await self._async_get_web_activity(
            account.user_id
        )
        self.search_activity_today[account.user_id] = await self._async_get_search_activity(
            account.user_id
        )

    async def _async_get_web_activity(self, user_id: str) -> dict[str, Any]:
        """Fetch today's web activity using pyfamilysafety's raw endpoint map."""
        start_time, end_time = _range_datetimes(1)
        entries: list[dict[str, Any]] = []
        successful_statuses: list[str] = []
        for allow_status in WEB_ACTIVITY_ALLOW_STATUSES:
            try:
                response = await self.api.api.send_request(
                    endpoint="get_user_web_activity",
                    USER_ID=user_id,
                    BEGIN_TIME=_format_api_datetime(start_time),
                    END_TIME=_format_api_datetime(end_time),
                    ALLOW_STATUS=allow_status,
                )
                status_entries = _extract_activity_entries(response.get("json"))
                for entry in status_entries:
                    entry.setdefault("allowStatus", allow_status)
                entries.extend(status_entries)
                successful_statuses.append(allow_status)
            except Exception as err:  # pragma: no cover - depends on remote API/options.
                _LOGGER.debug(
                    "No %s web activity for account %s: %s",
                    allow_status,
                    user_id,
                    err,
                )

        return {
            "count": len(entries),
            "recent_entries": entries[:MAX_ACTIVITY_ATTRIBUTE_ENTRIES],
            "range_start": start_time.isoformat(),
            "range_end": end_time.isoformat(),
            "allow_statuses": successful_statuses,
        }

    async def _async_get_search_activity(self, user_id: str) -> dict[str, Any]:
        """Fetch today's search activity using pyfamilysafety's raw endpoint map."""
        start_time, end_time = _range_datetimes(1)
        try:
            response = await self.api.api.send_request(
                endpoint="get_user_search_activity",
                USER_ID=user_id,
                BEGIN_TIME=_format_api_datetime(start_time),
                END_TIME=_format_api_datetime(end_time),
            )
            entries = _extract_activity_entries(response.get("json"))
        except Exception as err:  # pragma: no cover - depends on remote API/options.
            _LOGGER.debug("No search activity for account %s: %s", user_id, err)
            entries = []

        return {
            "count": len(entries),
            "recent_entries": entries[:MAX_ACTIVITY_ATTRIBUTE_ENTRIES],
            "range_start": start_time.isoformat(),
            "range_end": end_time.isoformat(),
        }
