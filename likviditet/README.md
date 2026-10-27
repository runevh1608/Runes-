# Likviditet

Intern app til den ugentlige likviditetsstyring for Mediating og Webbler.

**Status:** Debitoropfølgning, forecast, Pleo-budget, versioner og opsætning er bygget.
Kreditoropfølgning, CSV-import/lukning af uge og økonomiopfølgning følger.

## Teknik

- Django 5.2 + SQLite (én fil: `data/likviditet.sqlite3`). Server-renderede sider; lidt vanilla JS gemmer felter automatisk.
- Chart.js ligger lokalt i `likvid/static`, så appen ikke afhænger af et CDN.
- e-conomic læses via REST API (kun GET). Appen gemmer kun jeres vurderinger og tastede tal.

## Kom i gang lokalt

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser      # én bruger pr. person
.venv/bin/python manage.py runserver
```

Vil I bare prøve appen med fiktive tal: `.venv/bin/python manage.py demodata` (opretter også brugeren demo/demo).
Brug den kun i en database, I ikke skal bruge til rigtige tal.

## Drift med Docker

```sh
cp .env.example .env    # udfyld
docker compose up -d --build
docker compose exec likviditet python manage.py createsuperuser
```

Databasen ligger i `./data`. **Tag backup af den mappe** – den indeholder al historik.

## e-conomic

Sæt `ECONOMIC_APP_SECRET_TOKEN` og et grant-token pr. selskab (`ECONOMIC_GRANT_TOKEN_MEDIATING`,
`ECONOMIC_GRANT_TOKEN_WEBBLER`). Debitorer hentes fra `/invoices/unpaid`; beløb i DKK er e-conomics egen
omregning (`remainderInBaseCurrency`).

## Regler i beregningen

- Perioder: fredag–torsdag, delt ved månedsskift. Ugenummer = ISO-ugen for ugens torsdag.
- Debitorer: forventet dato = seneste vurdering, ellers fakturadato + standardkredit (Mediating 0, Webbler 8).
  Er datoen passeret, og fakturaen stadig åben, ligger beløbet i den aktuelle periode.
- Forventede fakturaer: beløbet fordeles ligeligt på hverdage i fakturaintervallet (ingen hverdage → alle dage);
  betaling = fakturadag + kredit. Dele med fakturadag før i dag udløber.
- Pleo: månedsbudget pr. afdeling fordelt efter antal dage i perioden.
- Saldo: primosaldo pr. dato (torsdag eller månedsslut) fremskrives med "Pengestrømme i alt". Info-linjer tæller ikke med.
- Historik: vurderinger gemmes som nye rækker, tastede tal logges, og gemte forecast-versioner kan ikke ændres eller slettes.

## Tests

```sh
.venv/bin/python manage.py test likvid
```
