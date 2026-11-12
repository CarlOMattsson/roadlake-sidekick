# Vanliga frågor

[English](faq.md)

<!-- description: Korta svar om vad Sidekick är, vad Claude ser, licens och pris, drift och Android-appen, med länkar till sidan som förklarar mer. -->

Korta svar på det folk brukar undra innan de installerar. Varje svar länkar till sidan som förklarar mer.

## Produkten

### Vad är Sidekick?

Sidekick är en personlig assistent som du kör på din egen server. Du sköter uppgifter, dagbok, kontakter och inköp genom att prata med Claude, och rummen öppnas i samtalet när du vill klicka själv. [Läs hur samtalet och rummen hänger ihop](guide/README.sv.md).

### Behöver jag Claude?

Ja. Sidekick har inget eget webbgränssnitt. Claude är gränssnittet, och Android-appen är en andra yta för arbete, dagbok och inköp. [Läs vad Android-appen gör](guide/android-app.sv.md).

### Vilken Claude-plan behöver jag?

En plan som stöder anpassade connectors, alltså kopplingar till egna servrar. På Team och Enterprise lägger en organisationsägare till connectorn först. [Läs hur du ansluter Claude](operate/connect-claude.sv.md).

### Är Sidekick färdigt?

Nej. Version 0.1.0 är den första versionen och är inte släppt ännu. Från och med första releasen har varje release en signerad containeravbild och en signerad Android-APK; till dess bygger du båda själv ur källkoden. Den används dagligen med Claude, med Android-appen på en riktig telefon och på Linux; macOS är ännu inte provat. [Se vad som är provat](maintainers/release.sv.md).

### Varför är rummen på svenska?

Svenska är förval. Sätt `SIDEKICK_MCP_APP_LOCALE=en` på servern för engelska etiketter. [Läs mer om språk](reference/languages.sv.md).

## Data och integritet

### Var ligger mina data?

I PostgreSQL på din egen server. Sidekick skickar ingen telemetri och har ingen central tjänst. [Läs vem som ser vad](explanation/security-and-privacy.sv.md).

### Läser Claude min dagbok?

Bara om du ger connectorn behörigheten `journal:read`. Då kan Claude läsa inläggen, också själva texten, och det Claude läser delas med Claude. Exempelkonfigurationen ger ingen tillgång till dagboken. [Läs vad Claude ser](explanation/security-and-privacy.sv.md#vad-claude-ser).

### Skickas mina data till någon AI-leverantör?

Sidekick anropar ingen språkmodell på egen hand. Claude ser det som dess behörigheter tillåter. Slår du på minnet skickas text till den modellleverantör du själv har ställt in. [Läs om minnet](guide/control-and-memory.sv.md).

### Kan jag radera något för gott?

Inte från Claude eller rummen, där allt hamnar i papperskorgen och går att återställa. Den som sköter servern tömmer papperskorgen med ett kommando. Dagboksinlägg och varor går inte att radera för gott alls. [Läs hur du tömmer papperskorgen](operate/empty-trash.sv.md).

## Licens och pris

### Vad kostar Sidekick?

Ingenting. Alla funktioner finns utan licensnyckel. En frivillig nyckel tar bort påminnelsen om gratisversionen, och priserna för den finns i tabellen. [Se pristabellen](explanation/licensing.sv.md#priser).

### Vad händer när nyckeln går ut?

Påminnelsen kommer tillbaka. Inget annat ändras: dina data och alla funktioner är som förut. [Läs vad nyckeln gör](explanation/licensing.sv.md).

### Hur får jag nyckeln när jag har köpt?

Nyckeln skickas med e-post när betalningen är klar. Betalningen sker i Polars kassa. Nycklar säljs inte än. [Läs hur köpet går till](explanation/licensing.sv.md#så-köper-du).

### Är det öppen källkod?

Nej. Sidekick är källtillgängligt: du kan läsa och ändra koden, men licensen sätter gränser för spridning och försäljning. Licenstexten gäller, och sammanfattningen är inte licensen. [Läs licensen i klartext](explanation/licensing.sv.md).

### Får en konsult installera det åt mig?

Ja. En konsult eller byrå får installera, anpassa och sköta Sidekick på din egen installation och ta betalt för arbetet. De får inte ta betalt för programmet, för nycklar eller för tillgång, och de får inte erbjuda Sidekick som en hostad tjänst. [Läs vad licensen tillåter](explanation/licensing.sv.md).

## Drift

### Kan jag köra utan publik adress?

Ja, på två sätt: jobbpaketet kör Sidekick på en laptop mot Claude Desktop lokalt. Som utvecklare kan du också låta Claude Desktop starta Sidekick på din egen dator. Claude på webben och i telefonen behöver en publik HTTPS-adress. [Välj din väg](start/README.sv.md).

### Hur uppdaterar jag?

Ta en backup först. Sedan uppdaterar du antingen från källkoden eller till en signerad avbild med `update.sh`, som bara visar planen tills du lägger till `--apply`. Det finns ingen publicerad avbild än, så tills vidare gäller källkodsvägen. [Läs hur du uppdaterar](operate/update.sv.md).

### Hur flyttar jag mina data?

Ta en backup i den gamla installationen, starta den nya från en tom databas och importera backupen med samma nyckel. Telefoner, inloggningar och licensnyckeln följer inte med och får göras om. [Läs hur du flyttar data](operate/move-data.sv.md).

## Android

### Finns det en iOS-app?

Nej. Det finns en Android-app. Från och med första releasen laddar du ner en signerad APK från releasen på GitHub, och du kan också bygga den själv ur källkoden. [Läs om Android-appen](guide/android-app.sv.md).

### Behöver appen Googles tjänster?

Nej. Påminnelserna går via UnifiedPush och appen ntfy, utan Firebase. [Läs om widgeten och påminnelserna](guide/today-widget.sv.md).

### Kan jag skapa uppgifter i appen?

Inte i Android-appen. Där läser och bockar du av arbete, skriver och ändrar dagboksinlägg för hand, och skapar inköpslistor och lägger till varor. Uppgifter skapar du i Claude, genom att be om dem eller med + i rummet Arbete; projekt skapar du genom att be Claude. [Läs vad appen gör och inte gör](guide/android-app.sv.md).
