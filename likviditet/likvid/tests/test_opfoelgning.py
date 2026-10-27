from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from likvid import opfoelgning
from likvid.models import ForecastLinje, ForecastSnapshot, Selskab, UgeFaktisk, UgeLukning


def snapshot(dag: date, prognose: dict):
    tid = timezone.make_aware(datetime(dag.year, dag.month, dag.day, 12))
    with mock.patch("django.utils.timezone.now", return_value=tid):
        ForecastSnapshot.objects.create(aarsag="manuel", titel="x", data={"prognose": prognose})


class OpfoelgningTest(TestCase):
    def setUp(self):
        self.med = Selskab.objects.get(kode="mediating")
        self.deb = ForecastLinje.objects.get(selskab=self.med, kode="ind_debitor")
        self.loen = ForecastLinje.objects.get(selskab=self.med, kode="loen")

    def luk(self, fra, til, primo, poster):
        l = UgeLukning.objects.create(selskab=self.med, fra_dato=fra, til_dato=til, primo_saldo=primo,
                                      bevaegelser=sum(b for _, _, b in poster), faktisk_saldo=primo + sum(b for _, _, b in poster))
        for linje, start, b in poster:
            UgeFaktisk.objects.create(lukning=l, linje=linje, periode_start=start, beloeb=Decimal(b))

    def test_uge_og_maaned(self):
        snapshot(date(2026, 9, 25), {"mediating": {"uger": {"2026-10-02": {"debitor": "900", "ultimo": "5000"}},
                                                    "maaneder": {"2026-10": {"debitor": "4000", "ultimo": "4500", "hel": True}}}})
        # Version gemt midt i ugen tæller ikke for den uge.
        snapshot(date(2026, 10, 6), {"mediating": {"uger": {"2026-10-02": {"debitor": "1", "ultimo": "1"}}}})
        self.luk(date(2026, 10, 2), date(2026, 10, 8), Decimal(4000), [(self.deb, date(2026, 10, 2), 1000), (self.loen, date(2026, 10, 2), -200)])
        u = opfoelgning.uger(self.med, date(2026, 10, 27))
        self.assertEqual(len(u), 1)
        self.assertEqual((u[0]["forventet"], u[0]["faktisk"], u[0]["afvigelse"][0]), (Decimal(900), Decimal(1000), Decimal(100)))

        m = opfoelgning.maaneder(self.med, date(2026, 11, 20), antal=2)
        okt = m[1]
        self.assertFalse(okt["hel"])  # ikke lukket til månedsslut
        self.assertEqual((okt["debitor_forventet"], okt["debitor_faktisk"], okt["saldo_faktisk"]), (Decimal(4000), Decimal(1000), None))

        # Luk resten af oktober: 29.10–31.10 og 01.11–05.11 i samme uge.
        self.luk(date(2026, 10, 9), date(2026, 11, 5), Decimal(4800),
                 [(self.deb, date(2026, 10, 30), 3500), (self.loen, date(2026, 10, 30), -1000), (self.deb, date(2026, 11, 1), 50)])
        okt = opfoelgning.maaneder(self.med, date(2026, 11, 20), antal=2)[1]
        self.assertTrue(okt["hel"])
        self.assertEqual(okt["saldo_faktisk"], Decimal(7300))
        self.assertEqual(okt["saldo_afvigelse"], (Decimal(2800), Decimal("62.2")))
        self.assertEqual(okt["debitor_faktisk"], Decimal(4500))

    def test_maaned_uden_lukkede_uger_er_tom(self):
        self.luk(date(2026, 10, 2), date(2026, 10, 8), Decimal(0), [(self.deb, date(2026, 10, 2), 10)])
        sep = opfoelgning.maaneder(self.med, date(2026, 10, 27), antal=2)[1]
        self.assertIsNone(sep["debitor_faktisk"])
