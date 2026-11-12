# Ange en licensnyckel

[English](license-key.md)

<!-- description: Ange en licensnyckel i ett rum, i Android-appen eller från kommandoraden på servern. Bara instansens ägare kan göra det. -->

Ange en licensnyckel i ett rum, i Android-appen eller från kommandoraden på servern. Bara instansens ägare kan göra det.

Bara instansens ägare kan ange en nyckel. Använd ett av sätten nedan.

- **I en MCP-app.** Tryck på markeringen i toppraden, eller öppna licensraden längst ned i Kontroll. Välj "Ange licensnyckel", klistra in nyckeln och välj "Spara".
  Godkänns nyckeln säger raden det och visar vem den är utfärdad till. Annars ändras ingenting.
- **I Android-appen.** Öppna Inställningar, gå till licensraden längst ned, välj "Ange licensnyckel", klistra in nyckeln och spara.
  Appen skickar den till din server över den parade anslutningen (`PUT /companion/v1/license`).
- **På servern.** Instansens driftansvarige kan spara nyckeln från kommandoraden. Nyckeln läses från standard in, och exemplet nedan läser den med en tyst fråga så att den aldrig skrivs
  på en kommandorad som skalet sparar i sin historik. De andra kommandona är `show`, `clear` och `reset-clock`.

```bash
cd deploy/selfhost                      # i repositoryt, där selfhost.env finns
read -rs LICENSE_KEY                    # Bash: klistra in nyckeln, den visas inte; tryck Enter
printf '%s' "$LICENSE_KEY" | docker compose --env-file selfhost.env run --rm -T api python -m sidekick.license.cli set
unset LICENSE_KEY
```
