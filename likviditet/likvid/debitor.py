"""Debitoropfølgning: synkronisering fra e-conomic, status og forventede indbetalinger."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone

from . import economic
from .models import DebitorFaktura, DebitorVurdering, ForventetFaktura, Selskab, Synkronisering


@transaction.atomic
def synkroniser(selskab: Selskab, aabne: list[economic.AabenFaktura], idag: date) -> dict:
    """Opdaterer spejlet med listen af åbne fakturaer. Vurderinger røres ikke."""
    nu = timezone.now()
    eksisterende = {f.nummer: f for f in DebitorFaktura.objects.filter(selskab=selskab)}
    set_numre, nye, genaabnet = set(), 0, 0
    for a in aabne:
        set_numre.add(a.nummer)
        f = eksisterende.get(a.nummer)
        if f is None:
            f = DebitorFaktura(selskab=selskab, nummer=a.nummer)
            nye += 1
        elif not f.aaben:
            genaabnet += 1
        for felt in ("kunde_nummer", "kunde_navn", "fakturadato", "forfaldsdato", "valuta",
                     "beloeb", "restbeloeb", "restbeloeb_dkk"):
            setattr(f, felt, getattr(a, felt))
        f.aaben, f.sidst_set, f.lukket_dato = True, nu, None
        f.save()
    lukkede = [f for n, f in eksisterende.items() if f.aaben and n not in set_numre]
    for f in lukkede:
        f.aaben, f.lukket_dato = False, idag
        f.save(update_fields=["aaben", "lukket_dato"])
    return {"aabne": len(aabne), "nye": nye, "lukkede": len(lukkede), "genaabnet": genaabnet}


def hent_fra_economic(selskab: Selskab, bruger, idag: date) -> dict:
    sync = Synkronisering(selskab=selskab, type="debitor", bruger=bruger)
    try:
        aabne = economic.hent_aabne_debitorer(economic.EconomicKlient(selskab.kode))
        res = synkroniser(selskab, aabne, idag)
        sync.antal = res["aabne"]
        return res
    except economic.EconomicFejl as e:
        sync.fejl = str(e)
        raise
    finally:
        sync.save()


def med_vurdering(qs):
    """Forudindlæser vurderinger, så faktura.vurdering ikke giver en forespørgsel pr. række."""
    fakturaer = list(qs.select_related("selskab").prefetch_related(
        Prefetch("vurderinger", queryset=DebitorVurdering.objects.select_related("oprettet_af").order_by("-oprettet", "-id"),
                 to_attr="alle_vurderinger")))
    for f in fakturaer:
        f._vurdering_cache = f.alle_vurderinger[0] if f.alle_vurderinger else False
    return fakturaer


def aabne_fakturaer(selskab: Selskab):
    return med_vurdering(DebitorFaktura.objects.filter(selskab=selskab, aaben=True))


@dataclass
class Status:
    forfalden: bool
    dage_forfalden: int
    ikke_som_forventet: bool
    vurderet: bool
    udskudt_fra: date | None


def status(f: DebitorFaktura, idag: date) -> Status:
    forfald = f.forfaldsdato or f.standard_dato
    v = f.vurdering
    udskudt_fra = None
    for tidligere in getattr(f, "alle_vurderinger", [])[1:]:
        if tidligere.forventet_dato and tidligere.forventet_dato < f.forventet_dato:
            udskudt_fra = tidligere.forventet_dato
            break
    return Status(
        forfalden=forfald < idag,
        dage_forfalden=max(0, (idag - forfald).days),
        ikke_som_forventet=bool(v and v.forventet_dato and v.forventet_dato < idag),
        vurderet=bool(v and (v.forventet_dato or v.kommentar)),
        udskudt_fra=udskudt_fra,
    )


def gem_vurdering(f: DebitorFaktura, forventet_dato: date | None, kommentar: str, bruger) -> DebitorVurdering | None:
    """Gemmer en ny vurdering, hvis den adskiller sig fra den gældende."""
    v = f.vurdering
    if v and v.forventet_dato == forventet_dato and v.kommentar == kommentar:
        return None
    if not v and forventet_dato is None and not kommentar:
        return None
    ny = DebitorVurdering.objects.create(faktura=f, forventet_dato=forventet_dato, kommentar=kommentar, oprettet_af=bruger)
    f._vurdering_cache = ny
    return ny


def hverdage(fra: date, til: date) -> list[date]:
    alle = [fra + timedelta(days=i) for i in range((til - fra).days + 1)]
    return [d for d in alle if d.weekday() < 5] or alle


def fordeling(ff: ForventetFaktura) -> list[tuple[date, Decimal]]:
    """(betalingsdato, beløb) for hver fakturadag. Sidste dag får afrundingsresten."""
    dage = hverdage(ff.fra_dato, ff.til_dato)
    pr_dag = (ff.beloeb / len(dage)).quantize(Decimal("0.01"))
    res = [(d + timedelta(days=ff.kredit_dage), pr_dag) for d in dage]
    res[-1] = (res[-1][0], ff.beloeb - pr_dag * (len(dage) - 1))
    return res


def forventede_indbetalinger(selskab: Selskab, idag: date) -> list[tuple[date, Decimal, str]]:
    """Alle forventede indbetalinger som (dato, beløb, kilde).

    Åbne fakturaer med en passeret forventet dato lægges på idag (aktuel periode).
    Dele af forventede fakturaer med fakturadag før idag er udløbet og tæller ikke.
    """
    res = []
    for f in aabne_fakturaer(selskab):
        res.append((max(f.forventet_dato, idag), f.restbeloeb_dkk, "faktura"))
    for ff in ForventetFaktura.objects.filter(selskab=selskab, aktiv=True):
        for betalingsdato, beloeb in fordeling(ff):
            if betalingsdato - timedelta(days=ff.kredit_dage) >= idag:
                res.append((betalingsdato, beloeb, "forventet"))
    return res
