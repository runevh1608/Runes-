# Sådan åbner I appen

Appen kører på jeres egen computer og vises i browseren. Det kræver ingen kodning.

## 1. Installér Python (kun første gang)

1. Gå til <https://www.python.org/downloads/> og klik på den gule knap "Download Python".
2. Åbn den hentede fil.
   - **Windows:** sæt flueben i **"Add python.exe to PATH"** nederst i vinduet, og klik "Install Now".
   - **Mac:** klik "Fortsæt" igennem installationen.

## 2. Hent appen

1. Log ind på GitHub og åbn linket:
   <https://github.com/runevh1608/Runes-/archive/refs/heads/claude/liquidity-management-app-t5jbty.zip>
   Så hentes en ZIP-fil.
2. Pak ZIP-filen ud: højreklik → "Udpak alle" (Windows) eller dobbeltklik (Mac).
3. Flyt den udpakkede mappe et fast sted hen, fx Dokumenter. Åbn mappen **likviditet** inde i den.

## 3. Start appen

| | Prøv med fiktive tal | Brug med rigtige tal |
|---|---|---|
| Windows | Dobbeltklik **Start demo (Windows)** | Dobbeltklik **Start (Windows)** |
| Mac | Dobbeltklik **Start demo (Mac)** | Dobbeltklik **Start (Mac)** |

- Første gang tager det et par minutter. Der åbner et sort vindue med tekst. Det er normalt.
- Browseren åbner selv på <http://127.0.0.1:8000>.
- **Demo:** log ind med brugernavn `demo` og adgangskode `demo`.
- **Rigtige tal:** første gang bliver du i det sorte vindue bedt om et brugernavn og en adgangskode. Det er jeres login til appen.
- Lad det sorte vindue stå åbent, mens I bruger appen. Når det lukkes, stopper appen. Engelsk tekst om "development server" i vinduet kan ignoreres.

Demo og rigtige tal er helt adskilt. I kan prøve demoen så meget I vil uden at påvirke jeres rigtige data.

### Hvis computeren advarer

- **Windows:** "Windows har beskyttet din pc" → klik "Flere oplysninger" → "Kør alligevel".
- **Mac:** "kan ikke åbnes, fordi den er fra en ukendt udvikler" → højreklik på filen → "Åbn" → "Åbn".

## 4. Første opsætning med rigtige tal

1. **Opsætning:** angiv minimumssaldo og primosaldo for hvert selskab. Datoen skal være en torsdag eller sidste dag i en måned.
2. **Opsætning → administrationen → Brugere:** opret en bruger til din kollega.
3. Indtil e-conomic er koblet på, er knapperne "Hent fra e-conomic" grå. Kontoudtog kan importeres under **Pengestrømme**.

## Vigtigt om data

Alle jeres tal ligger i mappen `data` inde i `likviditet`. **Tag jævnligt en kopi af den mappe**, fx til et fælles drev.

Appen kører kun på den computer, hvor den er startet. Skal I begge bruge den fra hver jeres computer samtidig, skal den
ligge på en server. Det kan en IT-person sætte op med Docker-opsætningen beskrevet i `README.md`.
