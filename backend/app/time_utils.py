from datetime import datetime, timedelta, timezone


VIETNAM_TIMEZONE = timezone(timedelta(hours=7), name="ICT")


def to_vietnam_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(VIETNAM_TIMEZONE)
