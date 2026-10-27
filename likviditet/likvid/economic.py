"""Læse-klient til e-conomic REST API. Appen kalder kun GET."""

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import requests
from django.conf import settings


class EconomicFejl(Exception):
    pass


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

    def hent_alle(self, sti: str, pagesize: int = 1000) -> list[dict]:
        url = f"{settings.ECONOMIC_BASE_URL}{sti}"
        params = {"pagesize": pagesize}
        res = []
        while url:
            try:
                svar = self.session.get(url, params=params, timeout=30)
            except requests.RequestException as e:
                raise EconomicFejl(f"Kunne ikke kontakte e-conomic: {e}") from e
            if svar.status_code != 200:
                raise EconomicFejl(f"e-conomic svarede {svar.status_code}: {svar.text[:300]}")
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
