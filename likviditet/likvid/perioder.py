"""Forecast-perioder: uger fra fredag til torsdag, delt ved månedsskift.

Ugenummeret er ISO-ugen for ugens torsdag (fire af ugens syv dage ligger i den uge).
"""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

FREDAG, TORSDAG = 4, 3
MAANEDER = ["januar", "februar", "marts", "april", "maj", "juni", "juli",
            "august", "september", "oktober", "november", "december"]


def maanedsslut(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def uge_start(d: date) -> date:
    """Fredagen der starter den fre–tors-uge, d ligger i."""
    return d - timedelta(days=(d.weekday() - FREDAG) % 7)


def er_periodeslut(d: date) -> bool:
    return d.weekday() == TORSDAG or d == maanedsslut(d)


@dataclass(frozen=True)
class Periode:
    start: date
    slut: date

    @property
    def uge_start(self) -> date:
        return uge_start(self.start)

    @property
    def uge(self) -> int:
        return (self.uge_start + timedelta(days=6)).isocalendar().week

    @property
    def maaned(self) -> date:
        return self.start.replace(day=1)

    @property
    def dage(self) -> int:
        return (self.slut - self.start).days + 1

    @property
    def label(self) -> str:
        return f"{self.start:%d.%m}–{self.slut:%d.%m}"

    def indeholder(self, d: date) -> bool:
        return self.start <= d <= self.slut


def periode_for(d: date) -> Periode:
    start = max(uge_start(d), d.replace(day=1))
    slut = min(uge_start(d) + timedelta(days=6), maanedsslut(d))
    return Periode(start, slut)


def perioder_mellem(fra: date, til: date) -> list[Periode]:
    """Alle perioder der overlapper [fra, til]."""
    res, d = [], fra
    while d <= til:
        p = periode_for(d)
        res.append(p)
        d = p.slut + timedelta(days=1)
    return res


def kvartal_for(d: date) -> tuple[int, int]:
    return d.year, (d.month - 1) // 3 + 1


def kvartal_interval(aar: int, kvartal: int) -> tuple[date, date]:
    start = date(aar, 3 * kvartal - 2, 1)
    return start, maanedsslut(date(aar, 3 * kvartal, 1))


def naeste_kvartal(aar: int, kvartal: int, skridt: int = 1) -> tuple[int, int]:
    n = aar * 4 + (kvartal - 1) + skridt
    return n // 4, n % 4 + 1


def maanedsnavn(d: date) -> str:
    return f"{MAANEDER[d.month - 1].capitalize()} {d.year}"
