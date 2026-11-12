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

## Så kontrolleras nyckeln

Nycklar verifieras offline mot en **publik** nyckel (base64, rå Ed25519) som licensgivaren håller. Instansen läser den från `SIDEKICK_LICENSE_PUBLIC_KEY`, som har företräde, och annars från standardvärdet i `backend/src/sidekick/license/public_key.py`. Standardvärdet är licensgivarens publika nyckel, så ett bygge från det här repot med inställningen osatt godtar nycklar som licensgivaren har utfärdat.

Bara om den gällande publika nyckeln är platshållaren eller inte är en giltig nyckel loggar start `license_public_key_unusable` (orsak `placeholder` eller `invalid`); varje nyckel behandlas då som olicensierad och obetald-notisen visas. Giltiga nycklar utfärdas bara av licensgivaren (se [LICENSE.md](../../LICENSE.md)); leta inte efter, skapa eller dela någon.

Releaseflödet vägrar bygga en avbild så länge standardvärdet är platshållaren (`tools/check-license-public-key.py`). Lämna `SIDEKICK_LICENSE_PUBLIC_KEY` osatt om du inte medvetet använder en annan publik nyckel, till exempel en du själv har publicerat för din egen fork; det är ett publikt värde, ingen hemlighet.

Kontrollera genom att starta instansen och se att loggen saknar posten `license_public_key_unusable`, och kör sedan `python -m sidekick.license.cli show`.
