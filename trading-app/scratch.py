from datetime import datetime, timedelta
import calendar

def get_last_thursday(year, month):
    c = calendar.monthcalendar(year, month)
    for week in reversed(c):
        if week[calendar.THURSDAY] != 0:
            return datetime(year, month, week[calendar.THURSDAY]).date()

print(get_last_thursday(2024, 8))
