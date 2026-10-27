"""Kontoudtog: CSV-import, kategorisering via regler, afstemning og lukning af uger."""

import csv
import hashlib
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum

from .models import (Bankkonto, ForecastLinje, ForecastSnapshot, KategoriRegel, Kontoudtog, Postering, Selskab,
                     UgeFaktisk, UgeLukning)
from .perioder import TORSDAG, perioder_mellem
from .talformat import fortolk_beloeb, fortolk_dato

NUL = Decimal("0")


class ImportFejl(Exception):
    pass


# ---------------------------------------------------------------- CSV


@dataclass
class Raekke:
    dato: date
    tekst: str
    beloeb: Decimal
    saldo: Decimal | None


KOLONNER = {
    "dato": ("bogført", "bogfoert", "bogføringsdato", "dato", "date", "posteringsdato"),
    "tekst": ("tekst", "posteringstekst", "beskrivelse", "text", "modtager", "navn"),
    "beloeb": ("beløb", "beloeb", "beløb i dkk", "amount", "bevægelse"),
    "saldo": ("saldo", "balance"),
}


def _dekod(data: bytes) -> str:
    for kodning in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(kodning)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _find_kolonner(overskrift: list[str]) -> dict[str, int]:
    navne = [o.strip().strip('"').lower() for o in overskrift]
    res = {}
    for felt, kandidater in KOLONNER.items():
        for kandidat in kandidater:  # Første kandidat der findes, vinder (fx "bogført" før "rentedato")
            if kandidat in navne:
                res[felt] = navne.index(kandidat)
                break
        else:
            for i, n in enumerate(navne):
                if any(k in n for k in kandidater) and i not in res.values() and not (felt == "dato" and "rente" in n):
                    res[felt] = i
                    break
    return res


def _er_dato(tekst: str) -> bool:
    try:
        return fortolk_dato(tekst) is not None
    except ValueError:
        return False


def laes_csv(data: bytes) -> list[Raekke]:
    """Læser et kontoudtog. Kolonner findes via overskrifter; uden overskrift antages dato;tekst;beløb;saldo."""
    tekst = _dekod(data)
    foerste = tekst.splitlines()[0] if tekst.strip() else ""
    separator = max([";", ",", "\t"], key=foerste.count)
    raekker = [r for r in csv.reader(io.StringIO(tekst), delimiter=separator) if any(c.strip() for c in r)]
    if not raekker:
        raise ImportFejl("Filen er tom.")
    if _er_dato(raekker[0][0]):
        kol = {"dato": 0, "tekst": 1, "beloeb": 2, "saldo": 3}
    else:
        kol = _find_kolonner(raekker[0])
        raekker = raekker[1:]
        mangler = [f for f in ("dato", "tekst", "beloeb") if f not in kol]
        if mangler:
            raise ImportFejl(f"Kunne ikke finde kolonne(r) for {', '.join(mangler)} i overskriften: "
                             f"{foerste.strip()}")
    res = []
    for nr, r in enumerate(raekker, start=2):
        try:
            saldo = fortolk_beloeb(r[kol["saldo"]]) if "saldo" in kol and kol["saldo"] < len(r) else None
            res.append(Raekke(fortolk_dato(r[kol["dato"]]), r[kol["tekst"]].strip(), fortolk_beloeb(r[kol["beloeb"]]), saldo))
        except (ValueError, IndexError, TypeError) as e:
            raise ImportFejl(f"Linje {nr} kunne ikke læses ({e}): {separator.join(r)}")
    return res


def _noegle(r: Raekke, nr: int) -> str:
    return hashlib.sha256(f"{r.dato}|{r.tekst}|{r.beloeb}|{r.saldo}|{nr}".encode()).hexdigest()


@transaction.atomic
def importer(konto: Bankkonto, filnavn: str, data: bytes, bruger) -> Kontoudtog:
    raekker = laes_csv(data)
    udtog = Kontoudtog.objects.create(bankkonto=konto, filnavn=filnavn, importeret_af=bruger)
    eksisterende = set(Postering.objects.filter(bankkonto=konto).values_list("noegle", flat=True))
    lukket_til = UgeLukning.objects.filter(selskab=konto.selskab).order_by("-til_dato").values_list("til_dato", flat=True).first()
    taeller, nye, dubletter = defaultdict(int), [], 0
    for i, r in enumerate(raekker):
        grund = (r.dato, r.tekst, r.beloeb, r.saldo)
        taeller[grund] += 1
        n = _noegle(r, taeller[grund])
        if n in eksisterende or (lukket_til and r.dato <= lukket_til):
            dubletter += 1
            continue
        nye.append(Postering(bankkonto=konto, kontoudtog=udtog, dato=r.dato, tekst=r.tekst, beloeb=r.beloeb,
                             saldo=r.saldo, noegle=n, raekkefoelge=i))
        eksisterende.add(n)
    Postering.objects.bulk_create(nye)
    udtog.antal_nye, udtog.antal_dubletter = len(nye), dubletter
    udtog.save()
    anvend_regler(konto.selskab)
    return udtog


# ---------------------------------------------------------------- Regler


def bogfoerbare_linjer(selskab: Selskab):
    return ForecastLinje.objects.filter(selskab=selskab, type=ForecastLinje.POST)


def find_regel(tekst: str, selskab: Selskab, regler: list[KategoriRegel], koder: set[str]) -> KategoriRegel | None:
    """Selskabsspecifikke regler før fælles; længste søgetekst først."""
    t = tekst.lower()
    kandidater = [r for r in regler if r.soegetekst.lower() in t and r.linje_kode in koder
                  and (r.selskab_id is None or r.selskab_id == selskab.id)]
    kandidater.sort(key=lambda r: (r.selskab_id is None, -len(r.soegetekst)))
    return kandidater[0] if kandidater else None


def anvend_regler(selskab: Selskab) -> int:
    """Kategoriserer åbne posteringer, der ikke er kategoriseret manuelt."""
    linjer = {l.kode: l for l in bogfoerbare_linjer(selskab)}
    regler = list(KategoriRegel.objects.filter(aktiv=True).filter(Q(selskab=selskab) | Q(selskab__isnull=True)))
    aendret = 0
    for p in Postering.objects.filter(bankkonto__selskab=selskab, lukning__isnull=True).exclude(kategori_kilde=Postering.MANUEL):
        r = find_regel(p.tekst, selskab, regler, set(linjer))
        ny_linje = linjer[r.linje_kode] if r else None
        if (p.linje_id, p.regel_id) != (ny_linje and ny_linje.id, r and r.id):
            p.linje, p.regel, p.kategori_kilde = ny_linje, r, Postering.REGEL if r else ""
            p.save(update_fields=["linje", "regel", "kategori_kilde"])
            aendret += 1
    return aendret


# ---------------------------------------------------------------- Afstemning og lukning


def seneste_lukning(selskab: Selskab) -> UgeLukning | None:
    return UgeLukning.objects.filter(selskab=selskab).order_by("-til_dato").first()


def naeste_uge(selskab: Selskab) -> tuple[date, date, Decimal] | None:
    """(fra, til, primo) for den næste uge, der skal lukkes. None hvis der ikke er en startsaldo."""
    sidste = seneste_lukning(selskab)
    if sidste:
        fra, primo = sidste.til_dato + timedelta(days=1), sidste.faktisk_saldo
    else:
        konto = Bankkonto.objects.filter(selskab=selskab).first()
        if not konto:
            return None
        fra, primo = konto.primo_dato + timedelta(days=1), konto.primo_saldo
    til = fra + timedelta(days=(TORSDAG - fra.weekday()) % 7)
    return fra, til, primo


@dataclass
class Afstemning:
    fra: date
    til: date
    primo: Decimal
    bevaegelser: Decimal
    beregnet: Decimal
    bank_saldo: Decimal | None  # Saldo fra kontoudtoget på ugens sidste postering, hvis banken oplyser den
    ukategoriseret: int
    antal: int


def afstemning(selskab: Selskab) -> Afstemning | None:
    uge = naeste_uge(selskab)
    if not uge:
        return None
    fra, til, primo = uge
    poster = list(Postering.objects.filter(bankkonto__selskab=selskab, lukning__isnull=True, dato__gte=fra, dato__lte=til))
    bevaegelser = sum((p.beloeb for p in poster), NUL)
    med_saldo = [p for p in poster if p.saldo is not None]
    bank_saldo = None
    if med_saldo:
        # Filen kan være sorteret begge veje. Dagens sidste postering er den, hvis saldo
        # ikke er "saldo før" for en anden postering samme dag.
        sidste_dag = max(p.dato for p in med_saldo)
        dagens = [p for p in med_saldo if p.dato == sidste_dag]
        foer = {p.saldo - p.beloeb for p in dagens}
        sidste = [p for p in dagens if p.saldo not in foer]
        bank_saldo = (sidste[0] if len(sidste) == 1 else max(dagens, key=lambda p: p.raekkefoelge)).saldo
    return Afstemning(fra, til, primo, bevaegelser, primo + bevaegelser, bank_saldo,
                      sum(1 for p in poster if p.linje_id is None), len(poster))


class LukFejl(Exception):
    pass


@transaction.atomic
def luk_uge(selskab: Selskab, faktisk_saldo: Decimal, bruger, idag: date, snapshot_data=None) -> UgeLukning:
    a = afstemning(selskab)
    if a is None:
        raise LukFejl("Angiv først en primosaldo under Opsætning.")
    if a.til >= idag:
        raise LukFejl(f"Ugen slutter {a.til:%d.%m.%Y} og kan først lukkes dagen efter.")
    if a.ukategoriseret:
        raise LukFejl(f"{a.ukategoriseret} postering{'er' if a.ukategoriseret > 1 else ''} mangler en linje.")
    if a.beregnet != faktisk_saldo:
        raise LukFejl(f"Afstemningen går ikke op: primo + posteringer = {a.beregnet}, banksaldo = {faktisk_saldo}.")
    lukning = UgeLukning.objects.create(selskab=selskab, fra_dato=a.fra, til_dato=a.til, primo_saldo=a.primo,
                                        bevaegelser=a.bevaegelser, faktisk_saldo=faktisk_saldo, lukket_af=bruger)
    poster = Postering.objects.filter(bankkonto__selskab=selskab, lukning__isnull=True, dato__gte=a.fra, dato__lte=a.til)
    perioder = perioder_mellem(a.fra, a.til)
    summer = defaultdict(lambda: NUL)
    for p in poster:
        start = next(x.start for x in perioder if x.indeholder(p.dato))
        summer[(p.linje_id, start)] += p.beloeb
    for linje in bogfoerbare_linjer(selskab):
        for per in perioder:
            UgeFaktisk.objects.create(lukning=lukning, linje=linje, periode_start=per.start, beloeb=summer[(linje.id, per.start)])
    poster.update(lukning=lukning)
    if snapshot_data is not None:
        ForecastSnapshot.objects.create(oprettet_af=bruger, aarsag=ForecastSnapshot.LUKNING,
                                        titel=f"{selskab}: uge lukket {a.fra:%d.%m}–{a.til:%d.%m.%Y}", data=snapshot_data(lukning))
    return lukning


def faktiske(selskab: Selskab, starter: list[date]) -> dict:
    """{(linje_kode, periode_start): beløb} og {periode_start: lukning} for lukkede perioder."""
    vaerdier, lukninger = {}, {}
    for f in UgeFaktisk.objects.filter(lukning__selskab=selskab, periode_start__in=starter).select_related("linje", "lukning"):
        vaerdier[(f.linje.kode, f.periode_start)] = f.beloeb
        lukninger[f.periode_start] = f.lukning
    return {"vaerdier": vaerdier, "lukninger": lukninger}


def primo_i_lukket_periode(lukning: UgeLukning, periode_start: date) -> Decimal:
    tidligere = UgeFaktisk.objects.filter(lukning=lukning, periode_start__lt=periode_start).aggregate(s=Sum("beloeb"))["s"]
    return lukning.primo_saldo + (tidligere or NUL)
