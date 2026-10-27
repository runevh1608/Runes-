"""Fælles logik for lister, der spejles fra e-conomic (debitorer og kreditorer)."""

from datetime import date

from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone


@transaction.atomic
def synkroniser(model, selskab, noegle: str, aabne: list, felter: tuple[str, ...], idag: date) -> dict:
    """Opdaterer spejlet med listen af åbne poster. Poster der ikke længere er åbne lukkes; vurderinger røres ikke."""
    nu = timezone.now()
    eksisterende = {getattr(o, noegle): o for o in model.objects.filter(selskab=selskab)}
    set_noegler, nye, genaabnet = set(), 0, 0
    for a in aabne:
        n = getattr(a, noegle)
        set_noegler.add(n)
        o = eksisterende.get(n)
        if o is None:
            o = model(selskab=selskab, **{noegle: n})
            nye += 1
        elif not o.aaben:
            genaabnet += 1
        for felt in felter:
            setattr(o, felt, getattr(a, felt))
        o.aaben, o.sidst_set, o.lukket_dato = True, nu, None
        o.save()
    lukkede = [o for n, o in eksisterende.items() if o.aaben and n not in set_noegler]
    for o in lukkede:
        o.aaben, o.lukket_dato = False, idag
        o.save(update_fields=["aaben", "lukket_dato"])
    return {"aabne": len(aabne), "nye": nye, "lukkede": len(lukkede), "genaabnet": genaabnet}


def med_vurdering(qs, vurdering_model):
    """Forudindlæser vurderinger, så .vurdering ikke giver en forespørgsel pr. række."""
    poster = list(qs.select_related("selskab").prefetch_related(
        Prefetch("vurderinger", queryset=vurdering_model.objects.select_related("oprettet_af").order_by("-oprettet", "-id"),
                 to_attr="alle_vurderinger")))
    for o in poster:
        o._vurdering_cache = o.alle_vurderinger[0] if o.alle_vurderinger else False
    return poster
