"""Pin scheduling with randomized, human-like timing.

Distributes pins across the day within configured business hours
with jitter to avoid detection as automated posting.
"""

import logging
import random
from datetime import datetime, timedelta

from zoneinfo import ZoneInfo

from app.config import settings

logger = logging.getLogger(__name__)


def calculate_next_slot(
    existing_scheduled: list[datetime],
    count: int = 1,
) -> list[datetime]:
    """
    Calculate the next available time slots for pin publishing.

    Distributes pins evenly across remaining business hours today
    (or tomorrow if today is full), with random jitter.

    Args:
        existing_scheduled: Already-scheduled pin times for today
        count: Number of slots to generate

    Returns:
        List of datetime objects (timezone-aware) for scheduling
    """
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)

    max_per_day = settings.pins_per_day_max
    start_hour = settings.schedule_start_hour
    end_hour = settings.schedule_end_hour

    # Count how many are already scheduled today
    today_count = sum(
        1
        for dt in existing_scheduled
        if dt.astimezone(tz).date() == now.date()
    )

    slots: list[datetime] = []
    current_date = now.date()

    while len(slots) < count:
        remaining_today = max_per_day - today_count

        if remaining_today <= 0:
            # Move to next day
            current_date += timedelta(days=1)
            today_count = sum(
                1
                for dt in existing_scheduled
                if dt.astimezone(tz).date() == current_date
            )
            remaining_today = max_per_day - today_count
            continue

        # Calculate business hours window
        if current_date == now.date():
            # Today — start from now (or start_hour, whichever is later)
            window_start = max(
                now,
                datetime(current_date.year, current_date.month, current_date.day, start_hour, 0, tzinfo=tz),
            )
        else:
            window_start = datetime(
                current_date.year, current_date.month, current_date.day, start_hour, 0, tzinfo=tz
            )

        window_end = datetime(
            current_date.year, current_date.month, current_date.day, end_hour, 0, tzinfo=tz
        )

        if window_start >= window_end:
            # Past business hours — move to next day
            current_date += timedelta(days=1)
            today_count = 0
            continue

        # Divide remaining window into intervals
        window_minutes = int((window_end - window_start).total_seconds() / 60)
        slots_to_fill = min(count - len(slots), remaining_today)

        if slots_to_fill <= 0:
            current_date += timedelta(days=1)
            today_count = 0
            continue

        interval = window_minutes // slots_to_fill

        for i in range(slots_to_fill):
            # Base time + random jitter (±15 minutes)
            base_minutes = i * interval
            jitter = random.randint(-15, 15)
            offset_minutes = max(0, base_minutes + jitter)

            slot_time = window_start + timedelta(minutes=offset_minutes)

            # Ensure it's within the window
            slot_time = min(slot_time, window_end - timedelta(minutes=1))
            slot_time = max(slot_time, window_start + timedelta(minutes=1))

            slots.append(slot_time)
            today_count += 1

        if len(slots) < count:
            current_date += timedelta(days=1)
            today_count = 0

    # Sort and add micro-jitter (random seconds) to look more natural
    slots.sort()
    return [
        slot + timedelta(seconds=random.randint(0, 59))
        for slot in slots
    ]


def should_publish_now() -> bool:
    """Check if current time is within business hours for immediate publish."""
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    return settings.schedule_start_hour <= now.hour < settings.schedule_end_hour


def daily_capacity_remaining(existing_scheduled: list[datetime]) -> int:
    """How many more pins can be scheduled today."""
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    today_count = sum(
        1
        for dt in existing_scheduled
        if dt.astimezone(tz).date() == today
    )
    return max(0, settings.pins_per_day_max - today_count)
