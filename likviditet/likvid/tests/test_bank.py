from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from likvid import bank, forecast
from likvid.models import Bankkonto, ForecastLinje, ForecastSnapshot, KategoriRegel, Postering, Selskab, UgeLukning

IDAG = date(2026, 10, 27)

CSV = """Dato;Tekst;Beløb;Saldo
22-10-2026;LØN OKTOBER;-300,00;1.150,00
21-10-2026;STRIPE PAYOUT;250,00;1.450,00
16-10-2026;Indbetaling Kunde;200,00;1.200,00
""".encode("cp1252")


class CsvTest(TestCase):
    def test_overskrift_dansk_format_og_tegnsaet(self):
        r = bank.laes_csv(CSV)
        self.assertEqual(len(r), 3)
        self.assertEqual((r[0].dato, r[0].tekst, r[0].beloeb, r[0].saldo),
                         (date(2026, 10, 22), "LØN OKTOBER", Decimal("-300.00"), Decimal("1150.00")))

    def test_uden_overskrift_og_alternative_navne(self):
        r = bank.laes_csv("16.10.2026;Tekst;1.234,50;2.000,00\n".encode())
        self.assertEqual(r[0].beloeb, Decimal("1234.50"))
        r = bank.laes_csv('"Rentedato";"Bogført";"Posteringstekst";"Beløb"\n"15-10-2026";"16-10-2026";"X";"-5,00"\n'.encode())
        self.assertEqual((r[0].dato, r[0].saldo), (date(2026, 10, 16), None))

    def test_fejl(self):
        with self.assertRaises(bank.ImportFejl):
            bank.laes_csv(b"A;B;C\n1;2;3\n")
        with self.assertRaises(bank.ImportFejl):
            bank.laes_csv("Dato;Tekst;Beløb\n16-10-2026;X;abc\n".encode())


class LukningTest(TestCase):
    def setUp(self):
        self.med = Selskab.objects.get(kode="mediating")
        self.web = Selskab.objects.get(kode="webbler")
        self.konto = Bankkonto.objects.create(selskab=self.med, navn="Drift", primo_saldo=Decimal(1000), primo_dato=date(2026, 10, 15))
        self.bruger = get_user_model().objects.create(username="a")
        KategoriRegel.objects.create(soegetekst="løn", linje_kode="loen")
        KategoriRegel.objects.create(soegetekst="stripe", linje_kode="ind_stripe", selskab=self.med)
        KategoriRegel.objects.create(soegetekst="payout", linje_kode="oevrigt")

    def test_import_dubletter_og_regler(self):
        u = bank.importer(self.konto, "a.csv", CSV, self.bruger)
        self.assertEqual((u.antal_nye, u.antal_dubletter), (3, 0))
        u = bank.importer(self.konto, "b.csv", CSV, self.bruger)
        self.assertEqual((u.antal_nye, u.antal_dubletter), (0, 3))
        koder = {p.tekst: p.linje.kode if p.linje else None for p in Postering.objects.all()}
        self.assertEqual(koder, {"LØN OKTOBER": "loen", "STRIPE PAYOUT": "ind_stripe", "Indbetaling Kunde": None})

    def test_manuel_kategori_overskrives_ikke(self):
        bank.importer(self.konto, "a.csv", CSV, self.bruger)
        p = Postering.objects.get(tekst="LØN OKTOBER")
        p.linje, p.kategori_kilde = ForecastLinje.objects.get(selskab=self.med, kode="oevrigt"), Postering.MANUEL
        p.save()
        bank.anvend_regler(self.med)
        p.refresh_from_db()
        self.assertEqual(p.linje.kode, "oevrigt")

    def test_afstemning_og_lukning(self):
        bank.importer(self.konto, "a.csv", CSV, self.bruger)
        a = bank.afstemning(self.med)
        self.assertEqual((a.fra, a.til, a.beregnet, a.bank_saldo, a.ukategoriseret), 
                         (date(2026, 10, 16), date(2026, 10, 22), Decimal(1150), Decimal(1150), 1))
        with self.assertRaises(bank.LukFejl):
            bank.luk_uge(self.med, Decimal(1150), self.bruger, IDAG)  # ukategoriseret
        p = Postering.objects.get(tekst="Indbetaling Kunde")
        p.linje = ForecastLinje.objects.get(selskab=self.med, kode="ind_debitor")
        p.save()
        with self.assertRaises(bank.LukFejl):
            bank.luk_uge(self.med, Decimal(1100), self.bruger, IDAG)  # går ikke op
        with self.assertRaises(bank.LukFejl):
            bank.luk_uge(self.med, Decimal(1150), self.bruger, date(2026, 10, 22))  # ugen er ikke slut
        l = bank.luk_uge(self.med, Decimal(1150), self.bruger, IDAG, snapshot_data=lambda _: {"x": 1})
        self.assertEqual(Postering.objects.filter(lukning=l).count(), 3)
        self.assertEqual(ForecastSnapshot.objects.filter(aarsag="lukning").count(), 1)
        with self.assertRaises(Exception):
            l.save()

        # Forecast viser faktiske tal for den lukkede uge og starter saldoen fra banksaldoen.
        b = forecast.beregn(self.med, date(2026, 10, 1), date(2026, 10, 29), IDAG)
        i = [x.start for x in b.perioder].index(date(2026, 10, 16))
        self.assertTrue(b.lukket[i])
        self.assertEqual(b.vaerdier["loen"][i], Decimal(-300))
        self.assertEqual(b.vaerdier["ind_stripe"][i], Decimal(250))
        self.assertEqual((b.primo[i], b.ultimo[i]), (Decimal(1000), Decimal(1150)))
        self.assertIsNone(b.vaerdier["ud_pleo"][i - 1])  # før startsaldo
        self.assertEqual(b.primo[i + 1], Decimal(1150))
        self.assertEqual(bank.naeste_uge(self.med)[:2], (date(2026, 10, 23), date(2026, 10, 29)))

    def test_import_springer_lukkede_datoer_over(self):
        UgeLukning.objects.create(selskab=self.med, fra_dato=date(2026, 10, 16), til_dato=date(2026, 10, 22),
                                  primo_saldo=0, bevaegelser=0, faktisk_saldo=0)
        u = bank.importer(self.konto, "a.csv", CSV, self.bruger)
        self.assertEqual((u.antal_nye, u.antal_dubletter), (0, 3))
