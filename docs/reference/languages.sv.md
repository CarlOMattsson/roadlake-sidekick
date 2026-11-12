# Språk i rummen, appen och servern

[English](languages.md)

<!-- description: Rummen och Android-appen har var sin språkinställning, med svenska som förval och engelska som alternativ. Här står också vilket språk serverns kommandon använder. -->

Rummen och Android-appen har var sin språkinställning, med svenska som förval och engelska som alternativ. Här står också vilket språk serverns kommandon använder.

## Rummen

Texterna i rummen är på svenska som standard (`SIDEKICK_MCP_APP_LOCALE=sv`). Sätt `SIDEKICK_MCP_APP_LOCALE=en` på servern för engelska.

## Jobbpaketet

Alla kommandon i `tools/work.sh` skriver på svenska eller engelska: `SIDEKICK_WORK_LANG=sv|en`, annars
`SIDEKICK_WORK_LOCALE` i `work.env`, annars systemets `LANG`. Det är ett annat val än språket i apparna och i Hindsights
svar, som är `SIDEKICK_WORK_LOCALE` i `work.env`: första körningen kopierar `sv` från mallen och guiden ändrar värdet
bara om det saknas. Sätt `SIDEKICK_WORK_LOCALE=en` där och kör `bash tools/work.sh start` för engelska apptexter.

## Android-appen

Appens språk är en egen inställning och följer aldrig systemspråket: svenska som förval, engelska som
alternativ. Det bestäms när webbpaketet byggs, av metataggen `sidekick-app-locale` i `frontend/mobile.html`
(`sv` eller `en`). För en engelsk app ändrar du `content="sv"` till `content="en"` före
`npm run build:mobile`. Kopplingsskärmen, widgeten och påminnelsernas aviseringar följer samma språk. Undantaget är
widgetväljarens namn och förhandsvisning, som följer telefonens språk. Parkopplingskommandots egna meddelanden följer `SIDEKICK_MCP_APP_LOCALE`.
