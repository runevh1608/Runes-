"""Datamodel for likviditetsstyringen.

Princip: e-conomic er sandheden for bogførte tal. Fakturaer spejles her, men
vores egne vurderinger gemmes separat og overskrives aldrig (nye rækker), så
historikken bevares.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .perioder import er_periodeslut

BELOEB = dict(max_digits=14, decimal_places=2)


class Selskab(models.Model):
    kode = models.SlugField(unique=True)
    navn = models.CharField(max_length=100)
    standard_kredit_dage = models.PositiveIntegerField(
        default=0, help_text="Uvurderede fakturaer forventes betalt på fakturadato + dette antal dage."
    )
    minimumssaldo = models.DecimalField(**BELOEB, default=Decimal("0"))
    raekkefoelge = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["raekkefoelge", "navn"]
        verbose_name = "selskab"
        verbose_name_plural = "selskaber"

    def __str__(self):
        return self.navn


class Bankkonto(models.Model):
    selskab = models.ForeignKey(Selskab, on_delete=models.PROTECT, related_name="bankkonti")
    navn = models.CharField(max_length=100)
    kontonummer = models.CharField(max_length=40, blank=True)
    primo_saldo = models.DecimalField(**BELOEB, default=Decimal("0"), help_text="Saldo ved udgangen af primodatoen.")
    primo_dato = models.DateField(help_text="Skal være en periodeslut: en torsdag eller sidste dag i en måned.")

    class Meta:
        verbose_name = "bankkonto"
        verbose_name_plural = "bankkonti"

    def __str__(self):
        return f"{self.selskab} – {self.navn}"

    def clean(self):
        if self.primo_dato and not er_periodeslut(self.primo_dato):
            raise ValidationError({"primo_dato": "Primodatoen skal være en torsdag eller sidste dag i en måned."})


class ForecastLinje(models.Model):
    POST, INFO, SUM = "post", "info", "sum"
    TYPER = [(POST, "Tæller med"), (INFO, "Info (tæller ikke med)"), (SUM, "Sum")]
    MANUEL, DEBITOR, KREDITOR, PLEO = "manuel", "debitor", "kreditor", "pleo"
    KILDER = [(MANUEL, "Tastes pr. uge"), (DEBITOR, "Debitoropfølgning"), (KREDITOR, "Kreditoropfølgning"), (PLEO, "Pleo-budget")]

    selskab = models.ForeignKey(Selskab, on_delete=models.PROTECT, related_name="linjer")
    kode = models.SlugField()
    navn = models.CharField(max_length=100)
    raekkefoelge = models.PositiveIntegerField()
    type = models.CharField(max_length=10, choices=TYPER, default=POST)
    kilde = models.CharField(max_length=10, choices=KILDER, default=MANUEL)
    sum_af = models.JSONField(default=list, blank=True, help_text="Koder på de linjer, en sumlinje summerer.")

    class Meta:
        ordering = ["selskab", "raekkefoelge"]
        unique_together = [("selskab", "kode")]
        verbose_name = "forecast-linje"
        verbose_name_plural = "forecast-linjer"

    def __str__(self):
        return f"{self.selskab}: {self.navn}"

    @property
    def redigerbar(self):
        return self.type != self.SUM and self.kilde == self.MANUEL


class ManuelPost(models.Model):
    """Et tastet beløb på en linje i en periode. Ændringer logges i Aendringslog."""

    linje = models.ForeignKey(ForecastLinje, on_delete=models.PROTECT, related_name="poster")
    periode_start = models.DateField()
    beloeb = models.DecimalField(**BELOEB)
    opdateret = models.DateTimeField(auto_now=True)
    opdateret_af = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        unique_together = [("linje", "periode_start")]


class Aendringslog(models.Model):
    tidspunkt = models.DateTimeField(auto_now_add=True)
    bruger = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    objekt = models.CharField(max_length=200)
    gammel = models.TextField(blank=True)
    ny = models.TextField(blank=True)

    class Meta:
        ordering = ["-tidspunkt"]
        verbose_name = "ændring"
        verbose_name_plural = "ændringslog"


# ---------------------------------------------------------------- Debitorer


class DebitorFaktura(models.Model):
    """Spejl af en bogført faktura i e-conomic. Slettes aldrig; lukkes når den ikke længere er åben."""

    selskab = models.ForeignKey(Selskab, on_delete=models.PROTECT, related_name="debitorfakturaer")
    nummer = models.BigIntegerField()
    kunde_nummer = models.CharField(max_length=40, blank=True)
    kunde_navn = models.CharField(max_length=200, blank=True)
    fakturadato = models.DateField()
    forfaldsdato = models.DateField(null=True, blank=True)
    valuta = models.CharField(max_length=3, default="DKK")
    beloeb = models.DecimalField(**BELOEB, help_text="Fakturabeløb inkl. moms i fakturaens valuta.")
    restbeloeb = models.DecimalField(**BELOEB, help_text="Restbeløb i fakturaens valuta.")
    restbeloeb_dkk = models.DecimalField(**BELOEB)
    aaben = models.BooleanField(default=True)
    foerst_set = models.DateTimeField(auto_now_add=True)
    sidst_set = models.DateTimeField()
    lukket_dato = models.DateField(null=True, blank=True, help_text="Dato hvor fakturaen ikke længere var åben i e-conomic.")

    class Meta:
        unique_together = [("selskab", "nummer")]
        ordering = ["fakturadato", "nummer"]
        verbose_name = "debitorfaktura"
        verbose_name_plural = "debitorfakturaer"

    def __str__(self):
        return f"{self.selskab} faktura {self.nummer}"

    @property
    def standard_dato(self) -> date:
        return self.fakturadato + timedelta(days=self.selskab.standard_kredit_dage)

    @property
    def vurdering(self):
        """Gældende vurdering = den nyeste. Kan være forudindlæst via prefetch."""
        cache = getattr(self, "_vurdering_cache", None)
        if cache is not None:
            return cache or None
        v = self.vurderinger.order_by("-oprettet", "-id").first()
        self._vurdering_cache = v or False
        return v

    @property
    def forventet_dato(self) -> date:
        v = self.vurdering
        return v.forventet_dato if v and v.forventet_dato else self.standard_dato


class DebitorVurdering(models.Model):
    """Vores vurdering af en faktura. Kun nye rækker; den nyeste gælder."""

    faktura = models.ForeignKey(DebitorFaktura, on_delete=models.PROTECT, related_name="vurderinger")
    forventet_dato = models.DateField(null=True, blank=True)
    kommentar = models.TextField(blank=True)
    oprettet = models.DateTimeField(auto_now_add=True)
    oprettet_af = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-oprettet", "-id"]
        verbose_name = "debitorvurdering"
        verbose_name_plural = "debitorvurderinger"


class ForventetFaktura(models.Model):
    """Faktura der endnu ikke er udstedt. Beløbet fordeles ligeligt på hverdage i fakturaintervallet."""

    selskab = models.ForeignKey(Selskab, on_delete=models.PROTECT, related_name="forventede_fakturaer")
    beskrivelse = models.CharField(max_length=200)
    beloeb = models.DecimalField(**BELOEB, help_text="Samlet beløb i DKK inkl. moms.")
    fra_dato = models.DateField(help_text="Første forventede fakturadato.")
    til_dato = models.DateField(help_text="Sidste forventede fakturadato.")
    kredit_dage = models.PositiveIntegerField()
    aktiv = models.BooleanField(default=True)
    oprettet = models.DateTimeField(auto_now_add=True)
    oprettet_af = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["fra_dato"]
        verbose_name = "forventet faktura"
        verbose_name_plural = "forventede fakturaer"

    def clean(self):
        if self.fra_dato and self.til_dato and self.til_dato < self.fra_dato:
            raise ValidationError("Til-dato skal være efter fra-dato.")


class Synkronisering(models.Model):
    selskab = models.ForeignKey(Selskab, on_delete=models.PROTECT)
    type = models.CharField(max_length=20)
    tidspunkt = models.DateTimeField(auto_now_add=True)
    bruger = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    antal = models.PositiveIntegerField(default=0)
    fejl = models.TextField(blank=True)

    class Meta:
        ordering = ["-tidspunkt"]


# ---------------------------------------------------------------- Pleo


class PleoAfdeling(models.Model):
    selskab = models.ForeignKey(Selskab, on_delete=models.PROTECT, related_name="pleo_afdelinger")
    navn = models.CharField(max_length=100)
    aktiv = models.BooleanField(default=True)

    class Meta:
        ordering = ["navn"]
        verbose_name = "Pleo-afdeling"
        verbose_name_plural = "Pleo-afdelinger"

    def __str__(self):
        return f"{self.selskab}: {self.navn}"


class PleoBudget(models.Model):
    afdeling = models.ForeignKey(PleoAfdeling, on_delete=models.PROTECT, related_name="budgetter")
    maaned = models.DateField(help_text="Første dag i måneden.")
    beloeb = models.DecimalField(**BELOEB, help_text="Forventet forbrug i måneden (positivt tal).")

    class Meta:
        unique_together = [("afdeling", "maaned")]


# ---------------------------------------------------------------- Historik


class ForecastSnapshot(models.Model):
    """Fastfrosset kopi af et forecast. Kan ikke ændres eller slettes."""

    MANUEL, LUKNING = "manuel", "lukning"
    oprettet = models.DateTimeField(auto_now_add=True)
    oprettet_af = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    aarsag = models.CharField(max_length=20, choices=[(MANUEL, "Gemt manuelt"), (LUKNING, "Uge lukket")])
    titel = models.CharField(max_length=200)
    note = models.TextField(blank=True)
    data = models.JSONField()

    class Meta:
        ordering = ["-oprettet"]
        verbose_name = "forecast-version"
        verbose_name_plural = "forecast-versioner"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("En gemt forecast-version kan ikke ændres.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("En gemt forecast-version kan ikke slettes.")


# ---------------------------------------------------------------- Kreditorer


class KreditorPost(models.Model):
    """Spejl af en åben leverandørfaktura i e-conomic. Slettes aldrig; lukkes når den er betalt."""

    selskab = models.ForeignKey(Selskab, on_delete=models.PROTECT, related_name="kreditorposter")
    noegle = models.CharField(max_length=40, help_text="Regnskabsår og posteringsnummer i e-conomic.")
    leverandoer_nummer = models.CharField(max_length=40, blank=True)
    leverandoer_navn = models.CharField(max_length=200, blank=True)
    fakturanummer = models.CharField(max_length=60, blank=True)
    tekst = models.CharField(max_length=250, blank=True)
    bilagsdato = models.DateField()
    forfaldsdato = models.DateField(null=True, blank=True)
    valuta = models.CharField(max_length=3, default="DKK")
    til_betaling = models.DecimalField(**BELOEB, help_text="Restbeløb i fakturaens valuta. Positivt = vi skal betale.")
    til_betaling_dkk = models.DecimalField(**BELOEB)
    aaben = models.BooleanField(default=True)
    foerst_set = models.DateTimeField(auto_now_add=True)
    sidst_set = models.DateTimeField()
    lukket_dato = models.DateField(null=True, blank=True)

    class Meta:
        unique_together = [("selskab", "noegle")]
        ordering = ["forfaldsdato", "bilagsdato"]
        verbose_name = "kreditorpost"
        verbose_name_plural = "kreditorposter"

    def __str__(self):
        return f"{self.selskab}: {self.leverandoer_navn} {self.fakturanummer}"

    @property
    def standard_dato(self) -> date:
        return self.forfaldsdato or self.bilagsdato

    @property
    def vurdering(self):
        cache = getattr(self, "_vurdering_cache", None)
        if cache is not None:
            return cache or None
        v = self.vurderinger.order_by("-oprettet", "-id").first()
        self._vurdering_cache = v or False
        return v

    @property
    def betalingsdato(self) -> date:
        v = self.vurdering
        return v.betalingsdato if v and v.betalingsdato else self.standard_dato


class KreditorVurdering(models.Model):
    """Planlagt betalingsdato og kommentar. Kun nye rækker; den nyeste gælder."""

    post = models.ForeignKey(KreditorPost, on_delete=models.PROTECT, related_name="vurderinger")
    betalingsdato = models.DateField(null=True, blank=True)
    kommentar = models.TextField(blank=True)
    oprettet = models.DateTimeField(auto_now_add=True)
    oprettet_af = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-oprettet", "-id"]
        verbose_name = "kreditorvurdering"
        verbose_name_plural = "kreditorvurderinger"


# ---------------------------------------------------------------- Bank og lukning af uger


class KategoriRegel(models.Model):
    """Posteringer hvis tekst indeholder søgeteksten, kategoriseres til linjen med denne kode."""

    soegetekst = models.CharField(max_length=100)
    linje_kode = models.SlugField(help_text="Kode på forecast-linjen, fx loen eller ind_stripe.")
    selskab = models.ForeignKey(Selskab, null=True, blank=True, on_delete=models.PROTECT,
                                help_text="Tom = gælder begge selskaber.")
    aktiv = models.BooleanField(default=True)
    oprettet = models.DateTimeField(auto_now_add=True)
    oprettet_af = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["soegetekst"]
        verbose_name = "kategoriseringsregel"
        verbose_name_plural = "kategoriseringsregler"

    def __str__(self):
        return f"'{self.soegetekst}' → {self.linje_kode}"


class Kontoudtog(models.Model):
    bankkonto = models.ForeignKey(Bankkonto, on_delete=models.PROTECT, related_name="kontoudtog")
    filnavn = models.CharField(max_length=200)
    importeret = models.DateTimeField(auto_now_add=True)
    importeret_af = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    antal_nye = models.PositiveIntegerField(default=0)
    antal_dubletter = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-importeret"]


class UgeLukning(models.Model):
    """En afstemt og lukket uge for ét selskab. Kan ikke ændres eller slettes."""

    selskab = models.ForeignKey(Selskab, on_delete=models.PROTECT, related_name="lukninger")
    fra_dato = models.DateField()
    til_dato = models.DateField(help_text="Altid en torsdag.")
    primo_saldo = models.DecimalField(**BELOEB)
    bevaegelser = models.DecimalField(**BELOEB)
    faktisk_saldo = models.DecimalField(**BELOEB)
    lukket = models.DateTimeField(auto_now_add=True)
    lukket_af = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["selskab", "-til_dato"]
        unique_together = [("selskab", "til_dato")]
        verbose_name = "lukket uge"
        verbose_name_plural = "lukkede uger"

    def __str__(self):
        return f"{self.selskab}: {self.fra_dato:%d.%m}–{self.til_dato:%d.%m.%Y}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("En lukket uge kan ikke ændres.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("En lukket uge kan ikke slettes.")


class UgeFaktisk(models.Model):
    """Faktisk beløb pr. linje og periode i en lukket uge."""

    lukning = models.ForeignKey(UgeLukning, on_delete=models.PROTECT, related_name="faktiske")
    linje = models.ForeignKey(ForecastLinje, on_delete=models.PROTECT)
    periode_start = models.DateField()
    beloeb = models.DecimalField(**BELOEB)

    class Meta:
        unique_together = [("lukning", "linje", "periode_start")]


class Postering(models.Model):
    MANUEL, REGEL = "manuel", "regel"

    bankkonto = models.ForeignKey(Bankkonto, on_delete=models.PROTECT, related_name="posteringer")
    kontoudtog = models.ForeignKey(Kontoudtog, on_delete=models.PROTECT, related_name="posteringer")
    dato = models.DateField()
    tekst = models.CharField(max_length=300)
    beloeb = models.DecimalField(**BELOEB)
    saldo = models.DecimalField(**BELOEB, null=True, blank=True, help_text="Saldo efter posteringen, hvis banken oplyser den.")
    noegle = models.CharField(max_length=64, help_text="Bruges til at springe dubletter over ved overlappende import.")
    raekkefoelge = models.PositiveIntegerField(default=0)
    linje = models.ForeignKey(ForecastLinje, null=True, blank=True, on_delete=models.PROTECT)
    kategori_kilde = models.CharField(max_length=10, blank=True, choices=[(MANUEL, "Manuel"), (REGEL, "Regel")])
    regel = models.ForeignKey(KategoriRegel, null=True, blank=True, on_delete=models.SET_NULL)
    lukning = models.ForeignKey(UgeLukning, null=True, blank=True, on_delete=models.PROTECT, related_name="posteringer",
                                help_text="Sat når ugen er lukket; posteringen er så arkiveret.")

    class Meta:
        ordering = ["dato", "raekkefoelge", "id"]
        unique_together = [("bankkonto", "noegle")]
        verbose_name = "postering"
        verbose_name_plural = "posteringer"
