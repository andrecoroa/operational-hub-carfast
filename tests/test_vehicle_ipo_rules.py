from datetime import date, timedelta

from app.web.router import ipo_dates_compatible


def test_rentway_ipo_accepts_exact_and_up_to_seven_days_early():
    calculated = date(2030, 4, 2)

    assert ipo_dates_compatible(calculated, calculated)
    assert ipo_dates_compatible(calculated, calculated - timedelta(days=7))


def test_rentway_ipo_rejects_more_than_seven_days_early_or_any_day_late():
    calculated = date(2030, 4, 2)

    assert not ipo_dates_compatible(calculated, calculated - timedelta(days=8))
    assert not ipo_dates_compatible(calculated, calculated + timedelta(days=1))
