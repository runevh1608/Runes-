"""Læse-klient til e-conomic REST API. Appen kalder kun GET."""

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import requests
from django.conf import settings


class EconomicFejl(Exception):
    def __init__(self, besked: str, status: int | None = None):
        super().__init__(besked)
        self.status = status


def grant_token(selskabskode: str) -> str:
    return os.environ.get(f"ECONOMIC_GRANT_TOKEN_{selskabskode.upper()}", "")


def er_konfigureret(selskabskode: str) -> bool:
    return bool(settings.ECONOMIC_APP_SECRET_TOKEN and grant_token(selskabskode))


class EconomicKlient:
    def __init__(self, selskabskode: str, session: requests.Session | None = None):
        if not er_konfigureret(selskabskode):
            raise EconomicFejl(
                f"e-conomic er ikke sat op for {selskabskode}. Sæt ECONOMIC_APP_SECRET_TOKEN "
                f"og ECONOMIC_GRANT_TOKEN_{selskabskode.upper()}."
            )
        self.session = session or requests.Session()
        self.session.headers.update({
            "X-AppSecretToken": settings.ECONOMIC_APP_SECRET_TOKEN,
            "X-AgreementGrantToken": grant_token(selskabskode),
            "Content-Type": "application/json",
        })

    def hent_alle(self, sti: str, pagesize: int = 1000, **ekstra) -> list[dict]:
        url = sti if sti.startswith("http") else f"{settings.ECONOMIC_BASE_URL}{sti}"
        params = {"pagesize": pagesize, **ekstra}
        res = []
        while url:
            try:
                svar = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as e:
                raise EconomicFejl(f"Kunne ikke kontakte e-conomic: {e}") from e
            if svar.status_code != 200:
                raise EconomicFejl(f"e-conomic svarede {svar.status_code}: {svar.text[:300]}", svar.status_code)
            data = svar.json()
            res.extend(data.get("collection", []))
            url = data.get("pagination", {}).get("nextPage")
            params = None  # nextPage indeholder allerede parametrene
        return res


@dataclass
class AabenFaktura:
    nummer: int
    kunde_nummer: str
    kunde_navn: str
    fakturadato: date
    forfaldsdato: date | None
    valuta: str
    beloeb: Decimal
    restbeloeb: Decimal
    restbeloeb_dkk: Decimal


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


def hent_aabne_debitorer(klient: EconomicKlient) -> list[AabenFaktura]:
    """Ubetalte bogførte fakturaer. Beløb i DKK er e-conomics omregning (remainderInBaseCurrency)."""
    res = []
    for f in klient.hent_alle("/invoices/unpaid"):
        rest = _dec(f.get("remainder"))
        rest_dkk = f.get("remainderInBaseCurrency")
        res.append(AabenFaktura(
            nummer=int(f["bookedInvoiceNumber"]),
            kunde_nummer=str((f.get("customer") or {}).get("customerNumber", "")),
            kunde_navn=(f.get("recipient") or {}).get("name", ""),
            fakturadato=date.fromisoformat(f["date"]),
            forfaldsdato=date.fromisoformat(f["dueDate"]) if f.get("dueDate") else None,
            valuta=f.get("currency") or "DKK",
            beloeb=_dec(f.get("grossAmount")),
            restbeloeb=rest,
            restbeloeb_dkk=_dec(rest_dkk) if rest_dkk is not None else rest,
        ))
    return res


@dataclass
class AabenKreditor:
    noegle: str
    leverandoer_nummer: str
    leverandoer_navn: str
    fakturanummer: str
    tekst: str
    bilagsdato: date
    forfaldsdato: date | None
    valuta: str
    til_betaling: Decimal
    til_betaling_dkk: Decimal


def hent_aabne_kreditorer(klient: EconomicKlient, idag: date) -> list[AabenKreditor]:
    """Leverandørfakturaer med restbeløb fra de seneste regnskabsår.

    Hentes som posteringer (entryType supplierInvoice). Leverandørfakturaer er
    negative på leverandørkontoen, så restbeløbet vendes: positivt = vi skal betale.
    """
    navne = {str(l["supplierNumber"]): l.get("name", "") for l in klient.hent_alle("/suppliers")}
    res = []
    for aar in klient.hent_alle("/accounting-years"):
        if date.fromisoformat(aar["toDate"]) < date(idag.year - 2, 1, 1):
            continue
        url = aar.get("entries") or f"{aar['self']}/entries"
        try:
            poster = klient.hent_alle(url, filter="entryType$eq:supplierInvoice$and:remainder$ne:0")
        except EconomicFejl as e:
            if e.status != 400:
                raise
            poster = klient.hent_alle(url, filter="entryType$eq:supplierInvoice")
        for p in poster:
            rest = _dec(p.get("remainder"))
            if rest == 0:
                continue
            rest_dkk = p.get("remainderInBaseCurrency")
            nr = str((p.get("supplier") or {}).get("supplierNumber", ""))
            res.append(AabenKreditor(
                noegle=f"{aar['year']}-{p['entryNumber']}",
                leverandoer_nummer=nr,
                leverandoer_navn=navne.get(nr, ""),
                fakturanummer=str(p.get("supplierInvoiceNumber") or ""),
                tekst=p.get("text") or "",
                bilagsdato=date.fromisoformat(p["date"]),
                forfaldsdato=date.fromisoformat(p["dueDate"]) if p.get("dueDate") else None,
                valuta=p.get("currency") or "DKK",
                til_betaling=-rest,
                til_betaling_dkk=-(_dec(rest_dkk) if rest_dkk is not None else rest),
            ))
    return res
