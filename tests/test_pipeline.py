"""Tests for scheduler service."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services.scheduler import calculate_next_slot, daily_capacity_remaining


class TestCalculateNextSlot:
    """Test pin scheduling slot calculation."""

    def test_generates_requested_count(self):
        slots = calculate_next_slot([], count=5)
        assert len(slots) == 5

    def test_slots_are_sorted(self):
        slots = calculate_next_slot([], count=5)
        for i in range(1, len(slots)):
            assert slots[i] >= slots[i - 1]

    def test_slots_are_timezone_aware(self):
        slots = calculate_next_slot([], count=1)
        assert slots[0].tzinfo is not None

    def test_single_slot(self):
        slots = calculate_next_slot([], count=1)
        assert len(slots) == 1

    def test_respects_existing_scheduled(self):
        tz = ZoneInfo("Asia/Manila")
        now = datetime.now(tz)
        # Simulate many already-scheduled pins today
        existing = [now + timedelta(hours=i) for i in range(20)]
        slots = calculate_next_slot(existing, count=1)
        # Should schedule for tomorrow since today is full
        assert len(slots) == 1


class TestDailyCapacityRemaining:
    """Test daily capacity calculation."""

    def test_empty_schedule(self):
        remaining = daily_capacity_remaining([])
        assert remaining > 0

    def test_full_schedule(self):
        tz = ZoneInfo("Asia/Manila")
        now = datetime.now(tz)
        # Fill up today
        existing = [now + timedelta(minutes=i * 10) for i in range(50)]
        remaining = daily_capacity_remaining(existing)
        assert remaining == 0
