"""Danske tal- og datoformater."""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def formater_beloeb(v, decimaler: int = 0, tom: str = "") -> str:
    """1234567.891 -> '1.234.568' (eller '1.234.567,89' med 2 decimaler)."""
    if v is None or v == "":
        return tom
    d = Decimal(str(v)).quantize(Decimal(1).scaleb(-decimaler), rounding=ROUND_HALF_UP)
    if d == 0:
        d = abs(d)
    tekst = f"{d:,.{decimaler}f}"
    return tekst.replace(",", "X").replace(".", ",").replace("X", ".")


def formater_dato(d, tom: str = "") -> str:
    if not d:
        return tom
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%d.%m.%Y")


_TUSIND = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d*)?$")


def fortolk_beloeb(tekst: str) -> Decimal | None:
    """Tolker et tastet beløb. Tom tekst giver None.

    Dansk notation er standard ('1.234,50', '-50000', '50.000'). Et enkelt punktum
    med 1-2 decimaler bagefter læses som decimaltegn ('1234.5').
    """
    t = (tekst or "").strip().replace(" ", "").replace(" ", "").replace("kr.", "").replace("kr", "")
    t = t.replace("−", "-")
    if not t:
        return None
    if _TUSIND.match(t):
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") == 1 and len(t.split(".")[1]) <= 2:
        pass
    else:
        t = t.replace(".", "")
    try:
        return Decimal(t)
    except InvalidOperation:
        raise ValueError(f"'{tekst}' er ikke et gyldigt beløb")


def fortolk_dato(tekst: str) -> date | None:
    t = (tekst or "").strip()
    if not t:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%y", "%d-%m-%y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{tekst}' er ikke en gyldig dato")
