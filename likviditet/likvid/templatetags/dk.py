from decimal import Decimal

from django import template

from ..talformat import formater_beloeb, formater_dato

register = template.Library()


@register.filter
def kr(v, decimaler=0):
    """Beløb i dansk format. Minus vises som typografisk minus."""
    return formater_beloeb(v, int(decimaler)).replace("-", "−")


@register.filter
def kr_input(v):
    """Beløb til et inputfelt (almindelig bindestreg, så det kan tastes igen)."""
    return formater_beloeb(v, 0)


@register.filter
def dkdato(v):
    return formater_dato(v)


@register.filter
def negativ(v):
    try:
        return v is not None and v != "" and Decimal(str(v)) < 0
    except Exception:
        return False


@register.filter
def med(a, b):
    return zip(a, b)


@register.filter
def idx(liste, i):
    try:
        return liste[i]
    except (IndexError, TypeError, KeyError):
        return None
