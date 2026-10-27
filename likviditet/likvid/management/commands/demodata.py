"""Fylder databasen med fiktive data, så appen kan afprøves uden e-conomic."""

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from likvid import debitor
from likvid.economic import AabenFaktura
from likvid.models import (Bankkonto, DebitorFaktura, DebitorVurdering, ForecastLinje, ManuelPost, PleoAfdeling,
                           PleoBudget, Selskab)
from likvid.perioder import perioder_mellem, uge_start

KUNDER = ["Nordlys ApS", "Bryggen A/S", "Kontorhuset", "Fjord Media", "Hansen & Co", "Vestkyst Gruppen",
          "Brandt Consult", "Lindholm IT", "Søndergaard Biler", "Aros Event", "Novum Holding", "Kastrup Logistik"]


class Command(BaseCommand):
    help = "Opretter fiktive demodata (fakturaer, saldi, budgetter, tastede linjer) og brugeren demo/demo."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Kør selvom der allerede er fakturaer.")

    def handle(self, *args, force=False, **kw):
        if DebitorFaktura.objects.exists() and not force:
            raise CommandError("Der findes allerede fakturaer. Brug --force for at tilføje demodata alligevel.")
        rnd = random.Random(42)
        idag = timezone.localdate()
        anker = uge_start(idag) - timedelta(days=1)  # Torsdag før aktuel uge
        U = get_user_model()
        bruger, ny = U.objects.get_or_create(username="demo", defaults={"is_staff": True, "is_superuser": True})
        if ny:
            bruger.set_password("demo")
            bruger.save()

        med, web = Selskab.objects.get(kode="mediating"), Selskab.objects.get(kode="webbler")
        med.minimumssaldo, web.minimumssaldo = Decimal(300000), Decimal(500000)
        med.save(), web.save()
        for s, saldo in ((med, 640000), (web, 1150000)):
            Bankkonto.objects.update_or_create(selskab=s, defaults={"navn": "Driftskonto", "kontonummer": "7670 0000000",
                                                                    "primo_saldo": Decimal(saldo), "primo_dato": anker})

        # Mediating: mange små fakturaer, nogle i EUR, forfalder ved udstedelse.
        fakt = []
        for n in range(24):
            d = idag - timedelta(days=rnd.randint(0, 45))
            beloeb = Decimal(rnd.randrange(4000, 90000))
            valuta = rnd.choice(["DKK", "DKK", "EUR", "SEK"])
            kurs = {"DKK": 1, "EUR": Decimal("7.46"), "SEK": Decimal("0.65")}[valuta]
            fakt.append(AabenFaktura(20400 + n, str(1000 + n % 12), KUNDER[n % 12], d, d, valuta,
                                     (beloeb / kurs).quantize(Decimal("0.01")), (beloeb / kurs).quantize(Decimal("0.01")), beloeb))
        debitor.synkroniser(med, fakt, idag)

        # Webbler: alle faktureret sidste dag i forrige måned, 8 dages kredit.
        ult = idag.replace(day=1) - timedelta(days=1)
        fakt = [AabenFaktura(8100 + n, str(500 + n), KUNDER[(n + 3) % 12], ult, ult + timedelta(days=8), "DKK",
                             Decimal(rnd.randrange(15000, 120000)), Decimal(0), Decimal(0)) for n in range(9)]
        for f in fakt:
            f.restbeloeb = f.restbeloeb_dkk = f.beloeb
        debitor.synkroniser(web, fakt, idag)

        for f in DebitorFaktura.objects.filter(selskab=med)[:6]:
            DebitorVurdering.objects.create(faktura=f, forventet_dato=idag + timedelta(days=rnd.randint(-5, 20)),
                                            kommentar=rnd.choice(["Lovet betaling via mail", "Rykker sendt", "Venter på PO", ""]),
                                            oprettet_af=bruger)

        for s, afdelinger in ((med, {"Salg": 18000, "Marketing": 42000, "Administration": 6000}),):
            for navn, beloeb in afdelinger.items():
                a, _ = PleoAfdeling.objects.get_or_create(selskab=s, navn=navn)
                for m in range(-1, 6):
                    maaned = (idag.replace(day=1) + timedelta(days=32 * m)).replace(day=1)
                    PleoBudget.objects.update_or_create(afdeling=a, maaned=maaned, defaults={"beloeb": Decimal(beloeb)})

        perioder = perioder_mellem(anker + timedelta(days=1), idag + timedelta(days=200))
        tastet = {
            med: {"loen": -410000, "ind_stripe": 35000, "oms": 260000, "indkoeb": 70000, "moms": -180000},
            web: {"loen": -520000, "ud_indkoeb": -25000, "moms": -240000, "betalingsordning": -15000},
        }
        for s, linjer in tastet.items():
            for kode, beloeb in linjer.items():
                linje = ForecastLinje.objects.get(selskab=s, kode=kode)
                for p in perioder:
                    sidste_i_maaned = (p.slut + timedelta(days=1)).month != p.slut.month
                    if kode == "loen" and not sidste_i_maaned:
                        continue
                    if kode == "moms" and not (p.start.month in (3, 6, 9, 12) and p.start.day == 1):
                        continue
                    if kode == "betalingsordning" and p.start.day != 1:
                        continue
                    if kode in ("ind_stripe", "oms", "indkoeb", "ud_indkoeb"):
                        beloeb_p = Decimal(beloeb) * p.dage / 7
                    else:
                        beloeb_p = Decimal(beloeb)
                    ManuelPost.objects.update_or_create(linje=linje, periode_start=p.start,
                                                        defaults={"beloeb": beloeb_p.quantize(Decimal(1)), "opdateret_af": bruger})
        self.stdout.write(self.style.SUCCESS("Demodata oprettet. Log ind med demo / demo."))
