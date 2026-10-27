from django.db import migrations

P, I, S = "post", "info", "sum"
MAN, DEB, KRE, PLEO = "manuel", "debitor", "kreditor", "pleo"

SELSKABER = [
    ("mediating", "Mediating", 0, [
        ("oms", "Omsætning i perioden", I, MAN, []),
        ("ind_debitor", "Indbetalinger, debitorer", P, DEB, []),
        ("ind_stripe", "Indbetalinger, Stripe", P, MAN, []),
        ("sum_ind", "Indbetalinger fra driften", S, MAN, ["ind_debitor", "ind_stripe"]),
        ("indkoeb", "Indkøb i perioden", I, MAN, []),
        ("ud_kreditor", "Udbetalinger, kreditorer", P, KRE, []),
        ("ud_pleo", "Udbetalinger, PLEO", P, PLEO, []),
        ("loen", "Løn", P, MAN, []),
        ("sum_ud", "Udbetalinger fra driften", S, MAN, ["ud_kreditor", "ud_pleo", "loen"]),
        ("mellem", "Mellemregninger", P, MAN, []),
        ("moms", "Moms", P, MAN, []),
        ("oevrigt", "Øvrigt", P, MAN, []),
        ("sum_oevrige", "Øvrige ind- og udbetalinger", S, MAN, ["mellem", "moms", "oevrigt"]),
        ("i_alt", "Pengestrømme i alt", S, MAN, ["sum_ind", "sum_ud", "sum_oevrige"]),
    ]),
    ("webbler", "Webbler", 8, [
        ("ind_debitor", "Indbetalinger, debitorer", P, DEB, []),
        ("ud_kreditor", "Udbetalinger, kreditorer", P, KRE, []),
        ("ud_indkoeb", "Udbetalinger, løbende indkøb", P, MAN, []),
        ("loen", "Løn", P, MAN, []),
        ("sum_drift", "Pengestrøm fra driften", S, MAN, ["ind_debitor", "ud_kreditor", "ud_indkoeb", "loen"]),
        ("moms", "Moms", P, MAN, []),
        ("betalingsordning", "Betalingsordning", P, MAN, []),
        ("mellem", "Mellemregninger", P, MAN, []),
        ("oevrigt", "Øvrigt", P, MAN, []),
        ("sum_oevrige", "Øvrige ind- og udbetalinger", S, MAN, ["moms", "betalingsordning", "mellem", "oevrigt"]),
        ("i_alt", "Pengestrømme i alt", S, MAN, ["sum_drift", "sum_oevrige"]),
    ]),
]


def opret(apps, schema_editor):
    Selskab = apps.get_model("likvid", "Selskab")
    Linje = apps.get_model("likvid", "ForecastLinje")
    for nr, (kode, navn, kredit, linjer) in enumerate(SELSKABER):
        s = Selskab.objects.create(kode=kode, navn=navn, standard_kredit_dage=kredit, raekkefoelge=nr)
        for i, (lkode, lnavn, typ, kilde, sum_af) in enumerate(linjer):
            Linje.objects.create(selskab=s, kode=lkode, navn=lnavn, raekkefoelge=(i + 1) * 10,
                                 type=typ, kilde=kilde, sum_af=sum_af)


class Migration(migrations.Migration):
    dependencies = [("likvid", "0001_start")]
    operations = [migrations.RunPython(opret, migrations.RunPython.noop)]
