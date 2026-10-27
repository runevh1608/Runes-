from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from likvid import debitor, economic, forecast
from likvid.economic import AabenFaktura
from likvid.models import (Bankkonto, DebitorFaktura, ForecastLinje, ForecastSnapshot, ForventetFaktura, ManuelPost,
                           PleoAfdeling, PleoBudget, Selskab)
from likvid.perioder import er_periodeslut, kvartal_interval, periode_for, perioder_mellem
from likvid.talformat import formater_beloeb, fortolk_beloeb, fortolk_dato

IDAG = date(2026, 10, 27)  # tirsdag


def faktura(nr, dato, beloeb, valuta="DKK", dkk=None):
    return AabenFaktura(nr, "1", "Kunde", dato, dato, valuta, Decimal(beloeb), Decimal(beloeb), Decimal(dkk or beloeb))


class PeriodeTest(TestCase):
    def test_uge_fre_tors_delt_ved_maanedsskift(self):
        p = perioder_mellem(date(2026, 10, 23), date(2026, 11, 5))
        self.assertEqual([(x.start, x.slut) for x in p], [
            (date(2026, 10, 23), date(2026, 10, 29)),
            (date(2026, 10, 30), date(2026, 10, 31)),
            (date(2026, 11, 1), date(2026, 11, 5)),
        ])
        self.assertEqual(p[1].uge, p[2].uge)

    def test_kvartal_daekker_alle_dage_uden_overlap(self):
        fra, til = kvartal_interval(2026, 4)
        p = perioder_mellem(fra, til)
        self.assertEqual(p[0].start, fra)
        self.assertEqual(p[-1].slut, til)
        self.assertEqual(sum(x.dage for x in p), (til - fra).days + 1)

    def test_periodeslut(self):
        self.assertTrue(er_periodeslut(date(2026, 10, 29)))
        self.assertTrue(er_periodeslut(date(2026, 10, 31)))
        self.assertFalse(er_periodeslut(date(2026, 10, 30)))
        self.assertEqual(periode_for(date(2026, 10, 31)).start, date(2026, 10, 30))


class TalformatTest(TestCase):
    def test_formatering(self):
        self.assertEqual(formater_beloeb(Decimal("1234567.891")), "1.234.568")
        self.assertEqual(formater_beloeb(Decimal("-1234.5"), 2), "-1.234,50")
        self.assertEqual(formater_beloeb(Decimal("-0.2")), "0")

    def test_fortolkning(self):
        self.assertEqual(fortolk_beloeb("1.234,50"), Decimal("1234.50"))
        self.assertEqual(fortolk_beloeb("-50.000"), Decimal("-50000"))
        self.assertEqual(fortolk_beloeb("1234.5"), Decimal("1234.5"))
        self.assertEqual(fortolk_beloeb("1.234.567"), Decimal("1234567"))
        self.assertEqual(fortolk_beloeb("−200"), Decimal("-200"))
        self.assertIsNone(fortolk_beloeb(" "))
        with self.assertRaises(ValueError):
            fortolk_beloeb("abc")
        self.assertEqual(fortolk_dato("05.11.2026"), date(2026, 11, 5))
        self.assertEqual(fortolk_dato("2026-11-05"), date(2026, 11, 5))


class DebitorTest(TestCase):
    def setUp(self):
        self.med = Selskab.objects.get(kode="mediating")
        self.web = Selskab.objects.get(kode="webbler")
        self.bruger = get_user_model().objects.create(username="a")

    def test_vurdering_overlever_opdatering_og_betaling_lukker(self):
        debitor.synkroniser(self.med, [faktura(1, date(2026, 10, 1), 1000), faktura(2, date(2026, 10, 2), 500)], IDAG)
        f = DebitorFaktura.objects.get(nummer=1)
        debitor.gem_vurdering(f, date(2026, 11, 10), "Lovet", self.bruger)
        debitor.synkroniser(self.med, [faktura(1, date(2026, 10, 1), 800)], IDAG)
        f = debitor.aabne_fakturaer(self.med)[0]
        self.assertEqual(f.restbeloeb_dkk, Decimal(800))
        self.assertEqual(f.forventet_dato, date(2026, 11, 10))
        lukket = DebitorFaktura.objects.get(nummer=2)
        self.assertFalse(lukket.aaben)
        self.assertEqual(lukket.lukket_dato, IDAG)

    def test_standarddato_og_status(self):
        debitor.synkroniser(self.web, [faktura(5, date(2026, 10, 15), 100)], IDAG)
        f = debitor.aabne_fakturaer(self.web)[0]
        self.assertEqual(f.forventet_dato, date(2026, 10, 23))  # + 8 dage
        st = debitor.status(f, IDAG)
        self.assertTrue(st.forfalden)
        self.assertFalse(st.ikke_som_forventet)
        debitor.gem_vurdering(f, date(2026, 10, 26), "", self.bruger)
        self.assertTrue(debitor.status(f, IDAG).ikke_som_forventet)

    def test_uaendret_vurdering_gemmes_ikke_igen(self):
        debitor.synkroniser(self.med, [faktura(1, date(2026, 10, 1), 1000)], IDAG)
        f = debitor.aabne_fakturaer(self.med)[0]
        self.assertIsNotNone(debitor.gem_vurdering(f, None, "x", self.bruger))
        self.assertIsNone(debitor.gem_vurdering(f, None, "x", self.bruger))
        self.assertEqual(f.vurderinger.count(), 1)

    def test_forventet_faktura_fordeles_paa_hverdage(self):
        ff = ForventetFaktura.objects.create(selskab=self.med, beskrivelse="x", beloeb=Decimal(1000),
                                             fra_dato=date(2026, 11, 2), til_dato=date(2026, 11, 8), kredit_dage=0)
        dele = debitor.fordeling(ff)
        self.assertEqual(len(dele), 5)
        self.assertEqual(sum(b for _, b in dele), Decimal(1000))
        # Webbler fakturerer lørdag 31.10: ingen hverdage -> alle dage, + 8 dages kredit.
        ff2 = ForventetFaktura(selskab=self.web, beskrivelse="y", beloeb=Decimal(300), fra_dato=date(2026, 10, 31),
                               til_dato=date(2026, 10, 31), kredit_dage=8)
        self.assertEqual(debitor.fordeling(ff2), [(date(2026, 11, 8), Decimal(300))])

    def test_overskredne_lagt_i_aktuel_periode(self):
        debitor.synkroniser(self.med, [faktura(1, date(2026, 9, 1), 1000)], IDAG)
        res = debitor.forventede_indbetalinger(self.med, IDAG)
        self.assertEqual(res, [(IDAG, Decimal(1000), "faktura")])


class ForecastTest(TestCase):
    def setUp(self):
        self.med = Selskab.objects.get(kode="mediating")
        self.med.minimumssaldo = Decimal(900)
        self.med.save()
        Bankkonto.objects.create(selskab=self.med, navn="Drift", primo_saldo=Decimal(1000), primo_dato=date(2026, 10, 22))

    def post(self, kode, start, beloeb):
        ManuelPost.objects.create(linje=ForecastLinje.objects.get(selskab=self.med, kode=kode), periode_start=start,
                                  beloeb=Decimal(beloeb))

    def test_sumlinjer_info_og_saldo(self):
        self.post("loen", date(2026, 10, 30), -300)
        self.post("oms", date(2026, 10, 30), 99999)  # info tæller ikke med
        self.post("ind_stripe", date(2026, 10, 23), 50)
        debitor.synkroniser(self.med, [faktura(1, date(2026, 11, 3), 200)], IDAG)
        b = forecast.beregn(self.med, date(2026, 10, 1), date(2026, 11, 5), IDAG)
        i = [p.start for p in b.perioder].index(date(2026, 10, 30))
        self.assertEqual(b.vaerdier["sum_ud"][i], Decimal(-300))
        self.assertEqual(b.vaerdier["i_alt"][i], Decimal(-300))
        self.assertIsNone(b.ultimo[0])  # før primo
        self.assertEqual(b.ultimo[i - 1], Decimal(1050))
        self.assertEqual(b.ultimo[i], Decimal(750))
        self.assertEqual(b.ultimo[i + 1], Decimal(950))

    def test_saldo_fremskrives_til_senere_kvartal_og_minimum(self):
        self.post("loen", date(2026, 12, 25), -500)
        t = forecast.kvartalstabel(self.med, 2027, 1, IDAG)
        self.assertEqual(Decimal(t["primo"][0]), Decimal(500))
        self.assertTrue(all(t["under_minimum"][k] for k in range(len(t["kolonner"]))))
        t4 = forecast.kvartalstabel(self.med, 2026, 4, IDAG)
        self.assertEqual(t4["foerste_under"]["start"], "2026-12-25")

    def test_pleo_fordeles_efter_dage(self):
        a = PleoAfdeling.objects.create(selskab=self.med, navn="Salg")
        PleoBudget.objects.create(afdeling=a, maaned=date(2026, 11, 1), beloeb=Decimal(3000))
        b = forecast.beregn_linjer(self.med, perioder_mellem(date(2026, 11, 1), date(2026, 11, 30)), IDAG)
        self.assertEqual(b.vaerdier["ud_pleo"][0], Decimal(-500))  # 5 af 30 dage
        self.assertEqual(sum(b.vaerdier["ud_pleo"]), Decimal(-3000))

    def test_version_kan_ikke_aendres(self):
        v = ForecastSnapshot.objects.create(aarsag="manuel", titel="x", data={})
        with self.assertRaises(Exception):
            v.save()
        with self.assertRaises(Exception):
            v.delete()


@override_settings(ECONOMIC_APP_SECRET_TOKEN="app", ECONOMIC_BASE_URL="https://e.test")
class EconomicTest(TestCase):
    def test_hent_aabne_debitorer_med_paginering(self):
        side1 = {"collection": [{"bookedInvoiceNumber": 7, "date": "2026-10-01", "dueDate": "2026-10-09", "currency": "EUR",
                                 "grossAmount": 100, "remainder": 100, "remainderInBaseCurrency": 746.0,
                                 "customer": {"customerNumber": 12}, "recipient": {"name": "Kunde A"}}],
                 "pagination": {"nextPage": "https://e.test/invoices/unpaid?skippages=1"}}
        side2 = {"collection": [{"bookedInvoiceNumber": 8, "date": "2026-10-02", "currency": "DKK", "grossAmount": 50,
                                 "remainder": 25, "customer": {"customerNumber": 13}, "recipient": {"name": "B"}}],
                 "pagination": {}}
        session = mock.Mock(headers={})
        session.get.side_effect = [mock.Mock(status_code=200, json=lambda: side1), mock.Mock(status_code=200, json=lambda: side2)]
        with mock.patch.dict("os.environ", {"ECONOMIC_GRANT_TOKEN_MEDIATING": "g"}):
            res = economic.hent_aabne_debitorer(economic.EconomicKlient("mediating", session=session))
        self.assertEqual(session.headers["X-AgreementGrantToken"], "g")
        self.assertEqual([r.nummer for r in res], [7, 8])
        self.assertEqual(res[0].restbeloeb_dkk, Decimal("746.0"))
        self.assertEqual(res[1].restbeloeb_dkk, Decimal(25))
        self.assertIsNone(res[1].forfaldsdato)

    def test_ikke_konfigureret(self):
        with self.assertRaises(economic.EconomicFejl):
            economic.EconomicKlient("webbler")


class KreditorTest(TestCase):
    def setUp(self):
        self.med = Selskab.objects.get(kode="mediating")
        self.bruger = get_user_model().objects.create(username="a")
        Bankkonto.objects.create(selskab=self.med, navn="Drift", primo_saldo=Decimal(1000), primo_dato=date(2026, 10, 22))

    def kreditor(self, noegle, forfald, beloeb):
        return economic.AabenKreditor(noegle, "1", "Lev", "F1", "", forfald - timedelta(days=8), forfald, "DKK",
                                      Decimal(beloeb), Decimal(beloeb))

    def test_betalingsdato_og_forecast(self):
        from likvid import kreditor
        kreditor.synkroniser(self.med, [self.kreditor("2026-1", date(2026, 11, 3), 400),
                                        self.kreditor("2026-2", date(2026, 10, 1), 100)], IDAG)
        p = next(x for x in kreditor.aabne_poster(self.med) if x.noegle == "2026-1")
        kreditor.gem_vurdering(p, date(2026, 11, 20), "Aftalt", self.bruger)
        res = sorted(kreditor.forventede_udbetalinger(self.med, IDAG))
        self.assertEqual(res, [(IDAG, Decimal(-100)), (date(2026, 11, 20), Decimal(-400))])
        b = forecast.beregn(self.med, date(2026, 10, 23), date(2026, 11, 26), IDAG)
        self.assertEqual(b.vaerdier["ud_kreditor"][0], Decimal(-100))
        self.assertEqual(b.vaerdier["ud_kreditor"][-1], Decimal(-400))
        self.assertEqual(b.ultimo[-1], Decimal(500))
        kreditor.synkroniser(self.med, [self.kreditor("2026-2", date(2026, 10, 1), 100)], IDAG)
        lukket = kreditor.KreditorPost.objects.get(noegle="2026-1")
        self.assertFalse(lukket.aaben)
        self.assertEqual(lukket.vurderinger.count(), 1)


@override_settings(ECONOMIC_APP_SECRET_TOKEN="app", ECONOMIC_BASE_URL="https://e.test")
class EconomicKreditorTest(TestCase):
    def svar(self, status, data):
        return mock.Mock(status_code=status, json=lambda: data, text="fejl")

    def test_hent_kreditorer_med_fallback_og_fortegn(self):
        session = mock.Mock(headers={})
        poster = {"collection": [
            {"entryNumber": 11, "entryType": "supplierInvoice", "date": "2026-10-01", "dueDate": "2026-10-15",
             "currency": "EUR", "remainder": -100, "remainderInBaseCurrency": -746, "supplier": {"supplierNumber": 3},
             "supplierInvoiceNumber": "A-1", "text": "Licens"},
            {"entryNumber": 12, "entryType": "supplierInvoice", "date": "2026-10-02", "remainder": 0,
             "supplier": {"supplierNumber": 3}}], "pagination": {}}
        session.get.side_effect = [
            self.svar(200, {"collection": [{"supplierNumber": 3, "name": "Adobe"}], "pagination": {}}),
            self.svar(200, {"collection": [{"year": "2026", "toDate": "2026-12-31", "self": "https://e.test/accounting-years/2026"},
                                           {"year": "2020", "toDate": "2020-12-31", "self": "https://e.test/accounting-years/2020"}],
                            "pagination": {}}),
            self.svar(400, {}),
            self.svar(200, poster),
        ]
        with mock.patch.dict("os.environ", {"ECONOMIC_GRANT_TOKEN_MEDIATING": "g"}):
            res = economic.hent_aabne_kreditorer(economic.EconomicKlient("mediating", session=session), IDAG)
        self.assertEqual(len(res), 1)
        k = res[0]
        self.assertEqual((k.noegle, k.leverandoer_navn, k.til_betaling, k.til_betaling_dkk), ("2026-11", "Adobe", Decimal(100), Decimal(746)))
        self.assertEqual(session.get.call_args_list[2].args[0], "https://e.test/accounting-years/2026/entries")
        self.assertEqual(session.get.call_count, 4)  # 2020 springes over
