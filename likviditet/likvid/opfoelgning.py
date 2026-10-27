"""Økonomiopfølgning: faktiske tal fra lukkede uger mod det forecast, der var gemt på forhånd.

Sammenligningsgrundlaget er den seneste gemte version fra før perioden begyndte:
for en måned versionen fra før den 1., for en uge versionen fra senest den fredag ugen starter
(versionen der gemmes, når forrige uge lukkes).
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

from .models import ForecastSnapshot, Selskab, UgeFaktisk, UgeLukning
from .perioder import maanedsnavn, maanedsslut, uge_start

NUL = Decimal("0")


def _versioner() -> list[tuple[date, dict]]:
    from django.utils import timezone

    res = []
    for v in ForecastSnapshot.objects.order_by("oprettet").only("oprettet", "data"):
        if isinstance(v.data, dict) and "prognose" in v.data:
            res.append((timezone.localdate(v.oprettet), v.data["prognose"]))
    return res


def _forventet(versioner, selskab: str, felt: str, noegle: str, senest: date, kun_hele=False) -> dict | None:
    """Seneste version gemt senest på datoen, der har et tal for perioden."""
    for dato, prognose in reversed(versioner):
        if dato > senest:
            continue
        p = prognose.get(selskab, {}).get(felt, {}).get(noegle)
        if p and (not kun_hele or p.get("hel", True)):
            return {"dato": dato, **{k: Decimal(v) if isinstance(v, str) else v for k, v in p.items()}}
    return None


def _faktisk_debitor(selskab: Selskab, fra: date, til: date) -> Decimal:
    return UgeFaktisk.objects.filter(lukning__selskab=selskab, linje__kode="ind_debitor",
                                     periode_start__gte=fra, periode_start__lte=til).aggregate(s=Sum("beloeb"))["s"] or NUL


def _faktisk_saldo(selskab: Selskab, dato: date) -> Decimal | None:
    """Faktisk saldo ved udgangen af dagen, hvis den ligger i en lukket uge."""
    l = UgeLukning.objects.filter(selskab=selskab, fra_dato__lte=dato, til_dato__gte=dato).first()
    if not l:
        return None
    s = UgeFaktisk.objects.filter(lukning=l, periode_start__lte=dato).aggregate(s=Sum("beloeb"))["s"] or NUL
    return l.primo_saldo + s


def _lukket_til(selskab: Selskab) -> date | None:
    return UgeLukning.objects.filter(selskab=selskab).order_by("-til_dato").values_list("til_dato", flat=True).first()


def _afvigelse(forventet, faktisk):
    if forventet is None or faktisk is None:
        return None, None
    diff = faktisk - forventet
    pct = (diff / abs(forventet) * 100).quantize(Decimal("0.1")) if forventet else None
    return diff, pct


def maaneder(selskab: Selskab, idag: date, antal: int = 6) -> list[dict]:
    versioner = _versioner()
    lukket_til = _lukket_til(selskab)
    res = []
    m = idag.replace(day=1)
    for _ in range(antal):
        slut = maanedsslut(m)
        noegle = m.isoformat()[:7]
        f_saldo = _forventet(versioner, selskab.kode, "maaneder", noegle, m - timedelta(days=1), kun_hele=True)
        hel = bool(lukket_til and lukket_til >= slut)
        har_data = UgeLukning.objects.filter(selskab=selskab, fra_dato__lte=slut, til_dato__gte=m).exists()
        faktisk_deb = _faktisk_debitor(selskab, m, slut) if har_data else None
        faktisk_saldo = _faktisk_saldo(selskab, slut) if hel else None
        deb_fv = f_saldo["debitor"] if f_saldo else None
        saldo_fv = f_saldo["ultimo"] if f_saldo else None
        res.append({
            "maaned": maanedsnavn(m), "hel": hel, "lukket_til": lukket_til if lukket_til and m <= lukket_til < slut else None,
            "version_dato": f_saldo["dato"] if f_saldo else None,
            "saldo_forventet": saldo_fv, "saldo_faktisk": faktisk_saldo, "saldo_afvigelse": _afvigelse(saldo_fv, faktisk_saldo),
            "debitor_forventet": deb_fv, "debitor_faktisk": faktisk_deb,
            "debitor_afvigelse": _afvigelse(deb_fv, faktisk_deb) if hel else (None, None),
        })
        m = (m - timedelta(days=1)).replace(day=1)
    return res


def uger(selskab: Selskab, idag: date, antal: int = 13) -> list[dict]:
    """Debitorindbetalinger pr. lukket uge: forventet (version fra ugens start) mod faktisk."""
    versioner = _versioner()
    res = []
    for l in UgeLukning.objects.filter(selskab=selskab).order_by("-til_dato")[:antal]:
        start = uge_start(l.til_dato)
        f = _forventet(versioner, selskab.kode, "uger", start.isoformat(), start)
        faktisk = _faktisk_debitor(selskab, l.fra_dato, l.til_dato)
        res.append({"start": start, "slut": l.til_dato, "uge": (start + timedelta(days=6)).isocalendar().week,
                    "forventet": f["debitor"] if f else None, "faktisk": faktisk,
                    "afvigelse": _afvigelse(f["debitor"] if f else None, faktisk),
                    "saldo_forventet": f["ultimo"] if f else None, "saldo_faktisk": l.faktisk_saldo})
    return list(reversed(res))
