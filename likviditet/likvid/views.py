from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import debitor, economic, forecast
from .models import (Aendringslog, Bankkonto, DebitorFaktura, ForecastLinje, ForecastSnapshot, ForventetFaktura,
                     ManuelPost, PleoAfdeling, PleoBudget, Selskab, Synkronisering)
from .perioder import kvartal_for, kvartal_interval, maanedsnavn, naeste_kvartal, periode_for, perioder_mellem
from .talformat import formater_dato, fortolk_beloeb, fortolk_dato


def idag() -> date:
    return timezone.localdate()


def _fejl(tekst: str) -> HttpResponse:
    return HttpResponseBadRequest(tekst, content_type="text/plain; charset=utf-8")


def _log(bruger, objekt: str, gammel, ny):
    Aendringslog.objects.create(bruger=bruger, objekt=objekt, gammel="" if gammel is None else str(gammel),
                                ny="" if ny is None else str(ny))


# ---------------------------------------------------------------- Overblik


DAGENS_OPGAVER = {
    1: [("Debitoropfølgning", "debitorer_start")],
    3: [("Debitoropfølgning", "debitorer_start"), ("Kreditoropfølgning", None)],
    4: [("Likviditetsforecast", "forecast")],
}


@login_required
def overblik(request):
    d = idag()
    selskaber = []
    for s in Selskab.objects.all():
        graf = forecast.saldo_13_uger(s, d)
        aabne = debitor.aabne_fakturaer(s)
        statusser = [debitor.status(f, d) for f in aabne]
        selskaber.append({
            "selskab": s,
            "graf": graf,
            "under_minimum": graf["laveste"] is not None and graf["laveste"] < graf["minimum"],
            "mangler_saldo": forecast.saldo_anker(s) is None,
            "aabent": sum((f.restbeloeb_dkk for f in aabne), Decimal(0)),
            "forfaldent": sum((f.restbeloeb_dkk for f, st in zip(aabne, statusser) if st.forfalden), Decimal(0)),
            "antal_ikke_som_forventet": sum(1 for st in statusser if st.ikke_som_forventet),
            "antal_uvurderede": sum(1 for st in statusser if not st.vurderet),
            "sidste_sync": Synkronisering.objects.filter(selskab=s, type="debitor").first(),
        })
    opgaver = list(DAGENS_OPGAVER.get(d.weekday(), []))
    if d.day == 20:
        opgaver.append(("Økonomiopfølgning", None))
    return render(request, "likvid/overblik.html", {
        "selskaber": selskaber, "opgaver": opgaver, "idag": d,
        "graf_data": {"labels": selskaber[0]["graf"]["labels"] if selskaber else [],
                      "serier": [{"navn": x["selskab"].navn, "saldi": x["graf"]["saldi"], "minimum": x["graf"]["minimum"]}
                                 for x in selskaber]},
    })


# ---------------------------------------------------------------- Debitorer

FILTRE = [("alle", "Alle åbne"), ("forfaldne", "Forfaldne"), ("ikke_som_forventet", "Ikke betalt som forventet"),
          ("uvurderede", "Uvurderede")]


def _debitor_raekke(f: DebitorFaktura, d: date) -> dict:
    return {"f": f, "status": debitor.status(f, d)}


@login_required
def debitorer(request, kode=None):
    selskaber = list(Selskab.objects.all())
    if kode is None:
        return redirect("debitorer", kode=selskaber[0].kode)
    s = get_object_or_404(Selskab, kode=kode)
    d = idag()
    filter_ = request.GET.get("vis", "alle")
    raekker = [_debitor_raekke(f, d) for f in debitor.aabne_fakturaer(s)]
    opsummering = {
        "aabent": sum((r["f"].restbeloeb_dkk for r in raekker), Decimal(0)),
        "forfaldent": sum((r["f"].restbeloeb_dkk for r in raekker if r["status"].forfalden), Decimal(0)),
        "antal": {"alle": len(raekker),
                  "forfaldne": sum(1 for r in raekker if r["status"].forfalden),
                  "ikke_som_forventet": sum(1 for r in raekker if r["status"].ikke_som_forventet),
                  "uvurderede": sum(1 for r in raekker if not r["status"].vurderet)},
    }
    if filter_ == "forfaldne":
        raekker = [r for r in raekker if r["status"].forfalden]
    elif filter_ == "ikke_som_forventet":
        raekker = [r for r in raekker if r["status"].ikke_som_forventet]
    elif filter_ == "uvurderede":
        raekker = [r for r in raekker if not r["status"].vurderet]

    # Forventede indbetalinger pr. periode de næste uger (fakturaer + forventede fakturaer).
    start = periode_for(d).start
    b = forecast.beregn_linjer(s, perioder_mellem(start, start + timedelta(weeks=8)), d)
    fremad = [{"periode": p, "beloeb": b.vaerdier["ind_debitor"][i]} for i, p in enumerate(b.perioder)]

    forventede = []
    for ff in ForventetFaktura.objects.filter(selskab=s, aktiv=True):
        dele = debitor.fordeling(ff)
        aktive = sum((bel for dato, bel in dele if dato - timedelta(days=ff.kredit_dage) >= d), Decimal(0))
        forventede.append({"ff": ff, "betaling_fra": dele[0][0], "betaling_til": dele[-1][0], "udloebet": ff.beloeb - aktive})

    return render(request, "likvid/debitorer.html", {
        "selskab": s, "selskaber": selskaber, "raekker": raekker, "filtre": FILTRE, "filter": filter_,
        "opsummering": opsummering, "fremad": fremad, "forventede": forventede, "idag": d,
        "sidste_sync": Synkronisering.objects.filter(selskab=s, type="debitor").first(),
        "economic_klar": economic.er_konfigureret(s.kode),
    })


@login_required
@require_POST
def debitor_hent(request, kode):
    s = get_object_or_404(Selskab, kode=kode)
    try:
        res = debitor.hent_fra_economic(s, request.user, idag())
    except economic.EconomicFejl as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"Hentet {res['aabne']} åbne fakturaer fra e-conomic: {res['nye']} nye, "
                                  f"{res['lukkede']} betalt/lukket siden sidst.")
    return redirect("debitorer", kode=kode)


@login_required
@require_POST
def debitor_vurdering(request, faktura_id):
    f = debitor.med_vurdering(DebitorFaktura.objects.filter(pk=faktura_id))
    if not f:
        return _fejl("Fakturaen findes ikke.")
    f = f[0]
    try:
        dato = fortolk_dato(request.POST.get("forventet_dato", ""))
    except ValueError as e:
        return _fejl(str(e))
    gammel = f.vurdering
    kommentar = request.POST.get("kommentar", "").strip()
    if gammel and "kommentar" not in request.POST:
        kommentar = gammel.kommentar
    if gammel and "forventet_dato" not in request.POST:
        dato = gammel.forventet_dato
    ny = debitor.gem_vurdering(f, dato, kommentar, request.user)
    if ny:
        f.alle_vurderinger = [ny] + f.alle_vurderinger
    return render(request, "likvid/_debitor_raekke.html", {"r": _debitor_raekke(f, idag()), "idag": idag()})


@login_required
@require_POST
def forventet_opret(request, kode):
    s = get_object_or_404(Selskab, kode=kode)
    try:
        beloeb = fortolk_beloeb(request.POST.get("beloeb", ""))
        fra = fortolk_dato(request.POST.get("fra_dato", ""))
        til = fortolk_dato(request.POST.get("til_dato", "")) or fra
        kredit = int(request.POST.get("kredit_dage") or s.standard_kredit_dage)
        if not beloeb or not fra:
            raise ValueError("Angiv beløb og fakturadato.")
        ff = ForventetFaktura(selskab=s, beskrivelse=request.POST.get("beskrivelse", "").strip() or "Forventet faktura",
                              beloeb=beloeb, fra_dato=fra, til_dato=til, kredit_dage=kredit, oprettet_af=request.user)
        ff.full_clean()
    except (ValueError, ValidationError) as e:
        messages.error(request, " ".join(e.messages) if isinstance(e, ValidationError) else str(e))
    else:
        ff.save()
        messages.success(request, f"Forventet faktura tilføjet: {ff.beskrivelse}.")
    return redirect(f"/debitorer/{kode}/#forventede")


@login_required
@require_POST
def forventet_fjern(request, pk):
    ff = get_object_or_404(ForventetFaktura, pk=pk)
    ff.aktiv = False
    ff.save(update_fields=["aktiv"])
    _log(request.user, f"Forventet faktura {ff.pk} ({ff.selskab}: {ff.beskrivelse})", "aktiv", "fjernet")
    messages.success(request, f"Forventet faktura fjernet: {ff.beskrivelse}.")
    return redirect(f"/debitorer/{ff.selskab.kode}/#forventede")


# ---------------------------------------------------------------- Forecast


def _kvartal(request, aar, kvartal):
    if aar is None:
        aar, kvartal = kvartal_for(idag())
    if not 1 <= kvartal <= 4:
        kvartal = 1
    return aar, kvartal


def _forecast_kontekst(aar, kvartal):
    d = idag()
    tabeller = [forecast.kvartalstabel(s, aar, kvartal, d) for s in Selskab.objects.all()]
    return {"tabeller": tabeller, "samlet": forecast.samlet_tabel(tabeller) if tabeller else None,
            "aar": aar, "kvartal": kvartal, "redigerbar": True}


@login_required
def forecast_vis(request, aar=None, kvartal=None):
    aar, kvartal = _kvartal(request, aar, kvartal)
    ktx = _forecast_kontekst(aar, kvartal)
    ktx.update({
        "forrige": naeste_kvartal(aar, kvartal, -1), "naeste": naeste_kvartal(aar, kvartal, 1),
        "aktuelt": kvartal_for(idag()),
        "mangler_saldo": [s for s in Selskab.objects.all() if forecast.saldo_anker(s) is None],
    })
    return render(request, "likvid/forecast.html", ktx)


@login_required
@require_POST
def forecast_post(request):
    linje = get_object_or_404(ForecastLinje, pk=request.POST.get("linje"))
    if not linje.redigerbar:
        return _fejl("Linjen beregnes automatisk og kan ikke tastes.")
    try:
        start = date.fromisoformat(request.POST.get("start", ""))
        beloeb = fortolk_beloeb(request.POST.get("vaerdi", ""))
        aar, kvartal = int(request.POST["aar"]), int(request.POST["kvartal"])
    except (ValueError, KeyError) as e:
        return _fejl(str(e) if isinstance(e, ValueError) and "beløb" in str(e) else "Ugyldig indtastning.")
    if periode_for(start).start != start:
        return _fejl("Ugyldig periode.")
    with transaction.atomic():
        mp = ManuelPost.objects.filter(linje=linje, periode_start=start).first()
        gammel = mp.beloeb if mp else None
        if beloeb is None:
            if mp:
                mp.delete()
        elif mp:
            mp.beloeb, mp.opdateret_af = beloeb, request.user
            mp.save()
        else:
            ManuelPost.objects.create(linje=linje, periode_start=start, beloeb=beloeb, opdateret_af=request.user)
        if gammel != beloeb:
            _log(request.user, f"{linje.selskab}: {linje.navn}, periode {formater_dato(start)}", gammel, beloeb)
    return render(request, "likvid/_forecast_tabeller.html", _forecast_kontekst(aar, kvartal))


@login_required
@require_POST
def forecast_gem_version(request, aar, kvartal):
    ktx = _forecast_kontekst(aar, kvartal)
    ForecastSnapshot.objects.create(
        oprettet_af=request.user, aarsag=ForecastSnapshot.MANUEL, titel=f"Forecast Q{kvartal} {aar}",
        note=request.POST.get("note", "").strip(),
        data={"aar": aar, "kvartal": kvartal, "tabeller": ktx["tabeller"], "samlet": ktx["samlet"]},
    )
    messages.success(request, f"Forecast for Q{kvartal} {aar} er gemt som version.")
    return redirect("forecast_kvartal", aar=aar, kvartal=kvartal)


@login_required
def versioner(request):
    return render(request, "likvid/versioner.html", {"versioner": ForecastSnapshot.objects.select_related("oprettet_af")})


@login_required
def version_vis(request, pk):
    v = get_object_or_404(ForecastSnapshot, pk=pk)
    return render(request, "likvid/version.html", {"v": v, "tabeller": v.data["tabeller"], "samlet": v.data["samlet"],
                                                   "redigerbar": False})


# ---------------------------------------------------------------- Pleo


def _pleo_kontekst(aar, kvartal):
    fra, _ = kvartal_interval(aar, kvartal)
    maaneder = [fra.replace(month=fra.month + i) for i in range(3)]
    grupper = []
    for s in Selskab.objects.all():
        afdelinger = list(PleoAfdeling.objects.filter(selskab=s, aktiv=True))
        budget = {(b.afdeling_id, b.maaned): b.beloeb for b in PleoBudget.objects.filter(afdeling__in=afdelinger, maaned__in=maaneder)}
        raekker = [{"afdeling": a, "celler": [(m, budget.get((a.id, m))) for m in maaneder]} for a in afdelinger]
        totaler = [sum((budget.get((a.id, m), Decimal(0)) for a in afdelinger), Decimal(0)) for m in maaneder]
        grupper.append({"selskab": s, "raekker": raekker, "totaler": totaler})
    return {"grupper": grupper, "maaneder": [(m, maanedsnavn(m)) for m in maaneder], "aar": aar, "kvartal": kvartal}


@login_required
def pleo(request, aar=None, kvartal=None):
    aar, kvartal = _kvartal(request, aar, kvartal)
    ktx = _pleo_kontekst(aar, kvartal)
    ktx.update({"forrige": naeste_kvartal(aar, kvartal, -1), "naeste": naeste_kvartal(aar, kvartal, 1)})
    return render(request, "likvid/pleo.html", ktx)


@login_required
@require_POST
def pleo_budget(request):
    afdeling = get_object_or_404(PleoAfdeling, pk=request.POST.get("afdeling"))
    try:
        maaned = date.fromisoformat(request.POST.get("maaned", "")).replace(day=1)
        beloeb = fortolk_beloeb(request.POST.get("vaerdi", ""))
        aar, kvartal = int(request.POST["aar"]), int(request.POST["kvartal"])
    except (ValueError, KeyError) as e:
        return _fejl(str(e))
    if beloeb is not None:
        beloeb = abs(beloeb)
    b = PleoBudget.objects.filter(afdeling=afdeling, maaned=maaned).first()
    gammel = b.beloeb if b else None
    if beloeb is None and b:
        b.delete()
    elif beloeb is not None:
        PleoBudget.objects.update_or_create(afdeling=afdeling, maaned=maaned, defaults={"beloeb": beloeb})
    if gammel != beloeb:
        _log(request.user, f"Pleo-budget {afdeling}, {maanedsnavn(maaned)}", gammel, beloeb)
    return render(request, "likvid/_pleo_tabeller.html", _pleo_kontekst(aar, kvartal))


@login_required
@require_POST
def pleo_afdeling(request, kode):
    s = get_object_or_404(Selskab, kode=kode)
    navn = request.POST.get("navn", "").strip()
    if navn:
        PleoAfdeling.objects.create(selskab=s, navn=navn)
        messages.success(request, f"Afdelingen {navn} er oprettet.")
    return redirect(request.POST.get("tilbage") or "pleo")


# ---------------------------------------------------------------- Opsætning


@login_required
def opsaetning(request):
    selskaber = list(Selskab.objects.all())
    if request.method == "POST":
        s = get_object_or_404(Selskab, kode=request.POST.get("selskab"))
        try:
            kredit = int(request.POST.get("standard_kredit_dage", s.standard_kredit_dage))
            minimum = fortolk_beloeb(request.POST.get("minimumssaldo", "")) or Decimal(0)
            primo_saldo = fortolk_beloeb(request.POST.get("primo_saldo", ""))
            primo_dato = fortolk_dato(request.POST.get("primo_dato", ""))
            with transaction.atomic():
                for felt, ny in (("standard_kredit_dage", kredit), ("minimumssaldo", minimum)):
                    if getattr(s, felt) != ny:
                        _log(request.user, f"{s}: {felt}", getattr(s, felt), ny)
                        setattr(s, felt, ny)
                s.save()
                if primo_dato is not None and primo_saldo is not None:
                    konto = s.bankkonti.first() or Bankkonto(selskab=s, navn="Driftskonto")
                    konto.navn = request.POST.get("konto_navn", "").strip() or konto.navn
                    konto.kontonummer = request.POST.get("kontonummer", "").strip()
                    if (konto.primo_saldo, konto.primo_dato) != (primo_saldo, primo_dato):
                        _log(request.user, f"{s}: primosaldo", f"{konto.primo_saldo} pr. {konto.primo_dato}" if konto.pk else "",
                             f"{primo_saldo} pr. {primo_dato}")
                    konto.primo_saldo, konto.primo_dato = primo_saldo, primo_dato
                    konto.full_clean()
                    konto.save()
        except (ValueError, ValidationError) as e:
            messages.error(request, " ".join(e.messages) if isinstance(e, ValidationError) else str(e))
        else:
            messages.success(request, f"Opsætningen for {s} er gemt.")
        return redirect("opsaetning")
    return render(request, "likvid/opsaetning.html", {
        "selskaber": [{"s": s, "konto": s.bankkonti.first(), "economic": economic.er_konfigureret(s.kode)} for s in selskaber],
        "log": Aendringslog.objects.select_related("bruger")[:30],
    })
