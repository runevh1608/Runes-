#!/bin/bash
# Fælles opstart for Mac (og Linux). Kaldes fra "Start (Mac).command".
cd "$(dirname "$0")/.." || exit 1
export DATA_DIR DEMO

fejl() {
  echo
  echo "  Noget gik galt. Tag et skærmbillede af dette vindue og send det til den, der hjælper jer."
  read -r -p "  Tryk Enter for at lukke."
  exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
  echo
  echo "  Python er ikke installeret. Hent det fra https://www.python.org/downloads/ og installer det."
  echo "  Dobbeltklik derefter på start-filen igen."
  open "https://www.python.org/downloads/" 2>/dev/null
  read -r -p "  Tryk Enter for at lukke."
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Forbereder appen første gang. Det tager et par minutter ..."
  python3 -m venv .venv || fejl
fi
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt || fejl

NY=0
[ -f "$DATA_DIR/likviditet.sqlite3" ] || NY=1
.venv/bin/python manage.py migrate --noinput -v 0 || fejl

if [ "$NY" = 1 ]; then
  if [ "$DEMO" = 1 ]; then
    .venv/bin/python manage.py demodata || fejl
  else
    echo
    echo "  Opret jeres første bruger. Den anden bruger kan oprettes inde i appen under Administration."
    echo "  Mailadresse kan springes over med Enter. Adgangskoden vises ikke, mens du skriver."
    echo
    .venv/bin/python manage.py createsuperuser || fejl
  fi
fi

echo
echo "  Appen kører nu på http://127.0.0.1:8000"
echo "  Lad dette vindue være åbent, mens I bruger appen. Luk vinduet for at stoppe den."
echo
(sleep 2; open "http://127.0.0.1:8000" 2>/dev/null || xdg-open "http://127.0.0.1:8000" 2>/dev/null) &
.venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
