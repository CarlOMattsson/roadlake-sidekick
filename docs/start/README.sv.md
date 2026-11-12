# Välj din väg

[English](README.md)

<!-- description: Fyra sätt att börja med Sidekick – egen server, jobbdatorn, din första dag eller utveckling – och vad du behöver för vart och ett. -->

Det finns fyra sätt att börja. Välj efter var Sidekick ska köra och vad du vill göra.

:::note[Förhandsversion]
Sidekick 0.1.0 är en förhandsversion. Installationen är övad i Linux-containrar och följd från en ren klon. Den är inte provad mot riktiga Claude-anslutningar, en riktig GitHub-inloggning eller macOS.
:::

## Det här behöver du för en egen server

- **En Claude-plan som stöder anpassade connectors.** En connector är kopplingen som låter Claude använda verktygen på din server.
- **En publik HTTPS-adress till servern.** Det kan vara en domän eller en tunnel. Claude når servern från Anthropics moln, så en adress som bara finns i ditt hemnätverk räcker inte.
- **Ett GitHub-konto.** Det används för inloggningen.
- **Linux x86_64 med Docker och Docker Compose.**

Jobbdatorn och utvecklarvägen behöver ingen publik adress. De använder Claude Desktop på samma dator.

## Fyra vägar

### Egen server

För dig som vill självhosta, alltså köra Sidekick på en maskin du själv styr: en VPS eller en hemdator som alltid är på. Du behöver allt i listan ovan. Det här är vägen om du vill använda Sidekick från Claude på flera enheter och para ihop Android-appen.

[Gå till Första starten på en server](self-hosted-server.sv.md)

### Jobbdatorn

För dig som vill använda Sidekick på jobbet utan publik adress. Jobbpaketet kör Sidekick och ett privat minne i Docker på din laptop och pratar med Claude Desktop lokalt. Containrarna når bara företagets modellserver, men det Claude Desktop läser delas med Claude. Du behöver Ubuntu med Docker, Claude Desktop och adressen till företagets egen modellserver. Det finns ingen väg till telefonen i det här paketet.

[Gå till Sidekick på jobbdatorn](work-laptop.sv.md)

### Din första dag

För dig som redan har en server igång och Claude ansluten. Guiden tar dig genom alla fyra rum i ett samtal.

[Gå till Din första dag med Sidekick](first-day.sv.md)

### Utveckla och bidra

För dig som vill köra Sidekick lokalt, läsa koden eller föreslå en ändring. Du behöver en egen dator med Python 3.13 och `uv`, Node.js 22 och Docker. Claude Desktop kan starta Sidekick lokalt, utan publik adress.

[Gå till Kör Sidekick lokalt som utvecklare](first-contribution.sv.md)

## När du är igång

Användarguiden beskriver rummen ett i taget. Driftsguiderna beskriver uppdatering, backup och Android-appen.

- [Läs användarguiden](../guide/README.sv.md)
- [Läs driftsöversikten](../operate/README.sv.md)
- [Läs vem som ser vad](../explanation/security-and-privacy.sv.md)
