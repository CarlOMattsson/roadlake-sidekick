# macOS

[English](macos.md)

<!-- description: Jobbpaketet är skrivet för macOS med Docker Desktop men har aldrig körts där. Här står vad som skiljer sig från Linux. -->

Jobbpaketet är skrivet för macOS med Docker Desktop men har aldrig körts där. Här står vad som skiljer sig från Linux.

Docker Desktop står för de interna näten och den publicerade porten, så det stängda nätet bör fungera likadant (ingen
värdbrandvägg ingår). Grindvakten litar på macOS nyckelrings certifikat för en https-modellserver (exporteras till
`deploy/work/generated/ca-bundle.pem`). Inget av detta har körts på en Mac: macvägarna (launchd-agenten,
nyckelringsexporten, Claude Desktops inställningsmapp och `docker exec`-posten, som bara förutsätter att `docker` finns
på en absolut sökväg) är skrivna efter dokumentationen. Räkna macOS som otestat.
