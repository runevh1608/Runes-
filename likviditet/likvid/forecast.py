"""Beregning af likviditetsforecast.

Hver linje får et beløb pr. periode fra sin kilde (tastet, debitorer, kreditorer
eller Pleo). Sumlinjer summerer andre linjer. Saldoen starter i bankkontiens
primosaldo og fremskrives med linjen "Pengestrømme i alt".
"""

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from . import debitor
from .models import Bankkonto, ForecastLinje, ManuelPost, PleoBudget, Selskab
from .perioder import Periode, kvartal_interval, maanedsnavn, perioder_mellem, uge_start

I_ALT = "i_alt"
NUL = Decimal("0")


@dataclass
class Beregning:
    selskab: Selskab
    perioder: list[Periode]
    linjer: list[ForecastLinje]
    vaerdier: dict[str, list[Decimal | None]] = field(default_factory=dict)
    primo: list[Decimal | None] = field(default_factory=list)
    ultimo: list[Decimal | None] = field(default_factory=list)

    def i_alt(self, i: int) -> Decimal:
        return self.vaerdier[I_ALT][i] or NUL


class Fordeler:
    """Lægger daterede beløb i den periode, datoen falder i."""

    def __init__(self, perioder: list[Periode]):
        self.perioder = perioder
        self.starter = [p.start for p in perioder]

    def indeks(self, d: date) -> int | None:
        i = bisect_right(self.starter, d) - 1
        if i >= 0 and self.perioder[i].indeholder(d):
            return i
        return None


def saldo_anker(selskab: Selskab) -> tuple[date, Decimal] | None:
    """Seneste kendte saldo (dato, beløb) for selskabet."""
    konti = list(Bankkonto.objects.filter(selskab=selskab))
    if not konti:
        return None
    return max(k.primo_dato for k in konti), sum((k.primo_saldo for k in konti), NUL)


def _pleo(selskab: Selskab, perioder: list[Periode]) -> list[Decimal]:
    """Månedsbudgettet fordeles efter antal dage i perioden. Udbetaling = negativt."""
    res = [NUL] * len(perioder)
    if not perioder:
        return res
    budget: dict[date, Decimal] = {}
    for b in PleoBudget.objects.filter(afdeling__selskab=selskab, afdeling__aktiv=True,
                                       maaned__gte=perioder[0].maaned, maaned__lte=perioder[-1].maaned):
        budget[b.maaned] = budget.get(b.maaned, NUL) + b.beloeb
    for i, p in enumerate(perioder):
        if p.maaned in budget:
            dage_i_maaned = (p.maaned.replace(day=28) + timedelta(days=4)).replace(day=1) - p.maaned
            res[i] = -(budget[p.maaned] * p.dage / dage_i_maaned.days).quantize(Decimal("0.01"))
    return res


def beregn_linjer(selskab: Selskab, perioder: list[Periode], idag: date) -> Beregning:
    linjer = list(ForecastLinje.objects.filter(selskab=selskab))
    b = Beregning(selskab, perioder, linjer)
    n = len(perioder)
    fordeler = Fordeler(perioder)
    starter = {p.start: i for i, p in enumerate(perioder)}

    manuelle = {}
    for mp in ManuelPost.objects.filter(linje__selskab=selskab, periode_start__in=list(starter)):
        manuelle.setdefault(mp.linje_id, {})[starter[mp.periode_start]] = mp.beloeb

    debitor_beloeb = None
    for linje in linjer:
        if linje.type == ForecastLinje.SUM:
            continue
        if linje.kilde == ForecastLinje.MANUEL:
            poster = manuelle.get(linje.id, {})
            b.vaerdier[linje.kode] = [poster.get(i) for i in range(n)]
        elif linje.kilde == ForecastLinje.DEBITOR:
            if debitor_beloeb is None:
                debitor_beloeb = [NUL] * n
                for d, beloeb, _ in debitor.forventede_indbetalinger(selskab, idag):
                    i = fordeler.indeks(d)
                    if i is not None:
                        debitor_beloeb[i] += beloeb
            b.vaerdier[linje.kode] = list(debitor_beloeb)
        elif linje.kilde == ForecastLinje.PLEO:
            b.vaerdier[linje.kode] = _pleo(selskab, perioder)
        else:
            # Kreditoropfølgning bygges i næste trin.
            b.vaerdier[linje.kode] = [NUL] * n

    sumlinjer = {l.kode: l for l in linjer if l.type == ForecastLinje.SUM}

    def summer(kode: str, i: int) -> Decimal:
        if kode in sumlinjer:
            return sum((summer(k, i) for k in sumlinjer[kode].sum_af), NUL)
        return b.vaerdier.get(kode, [NUL] * n)[i] or NUL

    for kode in sumlinjer:
        b.vaerdier[kode] = [summer(kode, i) for i in range(n)]
    b.vaerdier.setdefault(I_ALT, [NUL] * n)
    return b


def beregn(selskab: Selskab, fra: date, til: date, idag: date) -> Beregning:
    """Forecast for perioderne i [fra, til] inkl. primo- og ultimosaldo pr. periode."""
    perioder = perioder_mellem(fra, til)
    b = beregn_linjer(selskab, perioder, idag)
    anker = saldo_anker(selskab)
    b.primo, b.ultimo = [None] * len(perioder), [None] * len(perioder)
    if anker is None:
        return b
    anker_dato, saldo = anker
    if perioder and perioder[0].start > anker_dato + timedelta(days=1):
        mellem = beregn_linjer(selskab, perioder_mellem(anker_dato + timedelta(days=1), perioder[0].start - timedelta(days=1)), idag)
        saldo += sum((mellem.i_alt(i) for i in range(len(mellem.perioder))), NUL)
    for i, p in enumerate(perioder):
        if p.slut <= anker_dato:
            continue
        b.primo[i] = saldo
        saldo += b.i_alt(i)
        b.ultimo[i] = saldo
    return b


# ---------------------------------------------------------------- Visning


def _s(v) -> str | None:
    return None if v is None else str(v)


def _sum(vaerdier: list) -> Decimal | None:
    tal = [v for v in vaerdier if v is not None]
    return sum(tal, NUL) if tal else None


def kolonner(perioder: list[Periode], idag: date) -> list[dict]:
    """Periodekolonner med en månedskolonne efter hver måned og en kvartalskolonne til sidst."""
    res = []
    for i, p in enumerate(perioder):
        res.append({"type": "periode", "idx": [i], "start": p.start.isoformat(), "slut": p.slut.isoformat(),
                    "label": p.label, "uge": p.uge, "maaned": maanedsnavn(p.start), "aktuel": p.indeholder(idag)})
        if i == len(perioder) - 1 or perioder[i + 1].maaned != p.maaned:
            idx = [j for j, q in enumerate(perioder) if q.maaned == p.maaned]
            res.append({"type": "maaned", "idx": idx, "label": maanedsnavn(p.start).split()[0], "maaned": maanedsnavn(p.start)})
    res.append({"type": "total", "idx": list(range(len(perioder))), "label": "I alt"})
    return res


def tabel(b: Beregning, idag: date) -> dict:
    """Serialiserbar tabel (bruges både til visning og til gemte versioner)."""
    kols = kolonner(b.perioder, idag)
    min_saldo = b.selskab.minimumssaldo

    def celler(vaerdier):
        return [_s(vaerdier[k["idx"][0]]) if k["type"] == "periode" else _s(_sum([vaerdier[i] for i in k["idx"]])) for k in kols]

    def saldo_celler(liste, foerste: bool):
        return [_s(liste[k["idx"][0] if foerste else k["idx"][-1]]) if k["idx"] else None for k in kols]

    raekker = [{"id": l.id, "kode": l.kode, "navn": l.navn, "type": l.type, "kilde": l.kilde, "redigerbar": l.redigerbar,
               "celler": celler(b.vaerdier[l.kode])} for l in b.linjer]
    ultimo = saldo_celler(b.ultimo, False)
    under = [u is not None and Decimal(u) < min_saldo for u in ultimo]
    foerste_under = next((k for k, u in zip(kols, under) if u and k["type"] == "periode"), None)
    return {
        "selskab": {"kode": b.selskab.kode, "navn": b.selskab.navn, "minimumssaldo": str(min_saldo)},
        "kolonner": kols,
        "linjer": raekker,
        "primo": saldo_celler(b.primo, True),
        "ultimo": ultimo,
        "under_minimum": under,
        "foerste_under": foerste_under,
    }


def kvartalstabel(selskab: Selskab, aar: int, kvartal: int, idag: date) -> dict:
    fra, til = kvartal_interval(aar, kvartal)
    return tabel(beregn(selskab, fra, til, idag), idag)


def samlet_tabel(tabeller: list[dict]) -> dict:
    """Pengestrømme og ultimosaldo pr. selskab og samlet, i samme kolonner."""
    kols = tabeller[0]["kolonner"]
    raekker = []

    def plus(a, b):
        if a is None or b is None:
            return None
        return str(Decimal(a) + Decimal(b))

    total_strom = [str(NUL)] * len(kols)
    total_ultimo = [str(NUL)] * len(kols)
    for t in tabeller:
        strom = next(r["celler"] for r in t["linjer"] if r["kode"] == I_ALT)
        raekker.append({"navn": f"Pengestrømme, {t['selskab']['navn']}", "celler": strom, "type": "post"})
        total_strom = [plus(a, b) for a, b in zip(total_strom, strom)]
    raekker.append({"navn": "Pengestrømme i alt", "celler": total_strom, "type": "sum"})
    for t in tabeller:
        raekker.append({"navn": f"Ultimosaldo, {t['selskab']['navn']}", "celler": t["ultimo"], "type": "saldo",
                       "under": t["under_minimum"]})
        total_ultimo = [plus(a, b) for a, b in zip(total_ultimo, t["ultimo"])]
    raekker.append({"navn": "Ultimosaldo i alt", "celler": total_ultimo, "type": "saldo_total"})
    return {"kolonner": kols, "linjer": raekker}


def saldo_13_uger(selskab: Selskab, idag: date) -> dict:
    """Forventet saldo ved udgangen af hver af de næste 13 fre–tors-uger."""
    start = uge_start(idag)
    slut = start + timedelta(weeks=13, days=-1)
    b = beregn(selskab, start, slut, idag)
    labels, saldi = [], []
    for u in range(13):
        uge_slut = start + timedelta(weeks=u, days=6)
        i = max(j for j, p in enumerate(b.perioder) if p.slut <= uge_slut)
        labels.append(f"Uge {b.perioder[i].uge}")
        saldi.append(None if b.ultimo[i] is None else float(b.ultimo[i]))
    laveste = min((s for s in saldi if s is not None), default=None)
    return {"labels": labels, "saldi": saldi, "minimum": float(selskab.minimumssaldo), "laveste": laveste}
