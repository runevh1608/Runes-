"""Kreditoropfølgning: åbne leverandørfakturaer fra e-conomic, planlagte betalingsdatoer og betalingsforslag."""

from datetime import date
from decimal import Decimal

from . import economic, spejl
from .models import KreditorPost, KreditorVurdering, Selskab, Synkronisering

FELTER = ("leverandoer_nummer", "leverandoer_navn", "fakturanummer", "tekst", "bilagsdato", "forfaldsdato",
          "valuta", "til_betaling", "til_betaling_dkk")


def synkroniser(selskab: Selskab, aabne: list[economic.AabenKreditor], idag: date) -> dict:
    return spejl.synkroniser(KreditorPost, selskab, "noegle", aabne, FELTER, idag)


def hent_fra_economic(selskab: Selskab, bruger, idag: date) -> dict:
    sync = Synkronisering(selskab=selskab, type="kreditor", bruger=bruger)
    try:
        aabne = economic.hent_aabne_kreditorer(economic.EconomicKlient(selskab.kode), idag)
        res = synkroniser(selskab, aabne, idag)
        sync.antal = res["aabne"]
        return res
    except economic.EconomicFejl as e:
        sync.fejl = str(e)
        raise
    finally:
        sync.save()


def aabne_poster(selskab: Selskab):
    return spejl.med_vurdering(KreditorPost.objects.filter(selskab=selskab, aaben=True), KreditorVurdering)


def gem_vurdering(p: KreditorPost, betalingsdato: date | None, kommentar: str, bruger) -> KreditorVurdering | None:
    v = p.vurdering
    if v and v.betalingsdato == betalingsdato and v.kommentar == kommentar:
        return None
    if not v and betalingsdato is None and not kommentar:
        return None
    ny = KreditorVurdering.objects.create(post=p, betalingsdato=betalingsdato, kommentar=kommentar, oprettet_af=bruger)
    p._vurdering_cache = ny
    p.alle_vurderinger = [ny] + getattr(p, "alle_vurderinger", [])
    return ny


def forventede_udbetalinger(selskab: Selskab, idag: date) -> list[tuple[date, Decimal]]:
    """(dato, beløb) med udbetalinger negative. Passerede datoer lægges på idag."""
    return [(max(p.betalingsdato, idag), -p.til_betaling_dkk) for p in aabne_poster(selskab)]
