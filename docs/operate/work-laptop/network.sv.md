# Så är nätet stängt

[English](network.md)

<!-- description: Jobbpaketets containrar har ingen väg ut. Här står hur nätverket är stängt och hur du tillåter fler adresser än modellservern. -->

Jobbpaketets containrar har ingen väg ut. Här står hur nätverket är stängt och hur du tillåter fler adresser än modellservern.

## Så är nätet stängt

Alla Sidekick-containrar ligger på Docker-nät utan väg ut. Enda undantaget är en låst HAProxy-container (`gateway`) som
vidarebefordrar till exakt en adress, modellservern i `work.env`, och bara under dess bassökväg (allt annat får 403).
Den publicerar också HTTP-ytan för MCP enbart på `127.0.0.1` (Claude Desktop använder den inte; den svarar 401 utan
token och inga token utfärdas längre). Det fungerar likadant på varje Docker-värd och kräver inga
brandväggsändringar. Datorns egna certifikatlager används för en https-modellserver.

## Tillåtna adresser

Utöver modellservern går ingenting att nå. För att tillåta fler (till exempel en separat inbäddningsserver) lista
värdnamn med port i `SIDEKICK_WORK_ALLOW=embed.foretag.lan:443,filer.foretag.lan:8443` (eller svara på guidens fråga).
Varje post blir en ren TCP-genomsläppning i grindvakten, så klienten behåller det riktiga namnet och kontrollerar det
riktiga certifikatet. Begränsningar: bara värdnamn (inga IP-adresser) och varje post behöver en egen port (även skild
från modellserverns och 8765). Allt annat förblir spärrat. `status` visar vad som nås.
