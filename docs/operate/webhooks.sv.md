# Webhooks för Home Assistant, Tasker och liknande verktyg

[English](webhooks.md)

<!-- description: Låt hem- eller telefonautomation lägga till en vara eller en uppgift genom en tokenskyddad adress, med en token per integration. -->

Låt hem- eller telefonautomation skicka in en liten sak till Sidekick: en röstassistent i köket lägger mjölk på inköpslistan, eller Tasker lägger till en uppgift när du lämnar jobbet. Webhook-ingången är smal med flit. Den har två fasta åtgärder, en token per integration och ingen väg att läsa något tillbaka.

| Anrop | Vad det gör | Behörighet som token behöver |
| --- | --- | --- |
| `POST /webhooks/v1/shopping-items` | Lägger till en vara på en inköpslista. Utan `list_id` hamnar varan på din äldsta aktiva lista. | `webhook:shopping:add` |
| `POST /webhooks/v1/tasks` | Skapar en uppgift med titel och eventuellt förfallodatum. | `webhook:tasks:create` |

## Slå på

Ingången är avstängd tills du sätter `SIDEKICK_WEBHOOKS_ENABLED=true` (i `selfhost.env` på en självhostad server, annars i miljön eller `.env`) och startar om API:et. Så länge den är `false` är rutterna inte registrerade alls och svarar 404.

API:et svarar på de här sökvägarna själv, så Home Assistant på samma nät kan anropa det direkt. För en telefon utanför hemmet vidarebefordrar exempelfilen `deploy/selfhost/Caddyfile.example` precis de här två sökvägarna och inget annat under `/webhooks/`.

## Skapa en token

En token per integration, så att du kan återkalla en utan att röra de andra. Från en utcheckning:

```bash
uv run --project backend python -m sidekick.webhooks.cli create --label "Home Assistant" --scope webhook:shopping:add
```

Självhostat, från `deploy/selfhost`:

```bash
docker compose --env-file selfhost.env exec -T api python -m sidekick.webhooks.cli create --label "Tasker" --scope webhook:tasks:create
```

- `--scope` är obligatorisk och kan upprepas. Ingen behörighet följer med av sig själv.
- `--expires-in-days` anger livslängden (förval 365, högst 730). En token går alltid ut.
- `--rate-limit` anger antal anrop per minut för just den här token (förval 30, högst 600).
- Utan `--user-id` använder kommandot den enda aktiva ägaren och stannar om det finns fler.

Kommandot skriver ut token (`rsw_...`) en gång, som JSON. Bara en digest som beräknas med serverns hemliga nyckel och de första tio tecknen sparas, så ingen kan visa den för dig igen. Skapa en ny token om du tappar den. Behandla den som ett lösenord.

Lista token (aldrig själva token) och återkalla en:

```bash
uv run --project backend python -m sidekick.webhooks.cli list
uv run --project backend python -m sidekick.webhooks.cli revoke --token-id <id>
```

En återkallad eller utgången token slutar fungera vid nästa anrop, och det gör också alla token som tillhör en användare som stängts av.

## Anropet

```http
POST /webhooks/v1/shopping-items
Authorization: Bearer <token>
Idempotency-Key: <8 till 128 tecken, ny för varje åtgärd>
Content-Type: application/json

{"name": "Milk", "quantity": 2, "unit": "l", "note": "organic", "list_id": "<valfritt list-id>"}
```

```http
POST /webhooks/v1/tasks
Authorization: Bearer <token>
Idempotency-Key: <8 till 128 tecken, ny för varje åtgärd>
Content-Type: application/json

{"title": "Call the dentist", "due": "2030-05-17"}
```

- Vara: `name` är obligatoriskt (högst 200 tecken). `quantity` (förval 1), `unit`, `note` och `list_id` är valfria. Om du inte har någon aktiv lista svarar anropet 404. Ett webhook-anrop skapar aldrig en lista.
- Uppgift: `title` är obligatoriskt (högst 200 tecken). `due` är valfritt: ett datum (`2030-05-17`) betyder slutet av den dagen i din tidszon, och en tidpunkt med tidsförskjutning (`2030-05-17T08:30:00+02:00`) används som den är.
- Andra fält avvisas med 422. Innehållet får vara högst 8 KiB.
- `Idempotency-Key` är obligatorisk. Skicka samma nyckel och samma innehåll igen så får du det första svaret och inget skrivs två gånger, så en automation kan göra om anropet efter ett förlorat svar. Samma nyckel med annat innehåll ger 409.
- Lyckat anrop är `201` med id för det som skrevs: `{"list_id", "item_id"}` eller `{"task_id"}`.
- Varje token har en egen gräns per minut. Över gränsen blir svaret `429` med `Retry-After`. Gränsen räknas per API-process.

Avslag använder en sluten problemkropp (`code`, `title`, `status`, `correlation_id`, och för 403 och 409 en `reason`) och återger aldrig det du skickade. 401 betyder att token saknas, är okänd, utgången eller återkallad, 403 `scope_missing` att token saknar behörigheten för åtgärden.

Skrivningarna är vanliga inköps- och uppgiftsskrivningar: de syns i aktivitetsloggen som allt annat du lägger till. Förfrågningsloggen innehåller bara åtgärdens namn, utfallet och token-postens id. Den innehåller aldrig token, idempotensnyckeln eller det du skickade.

## Home Assistant

Lägg till ett `rest_command` i Home Assistants konfiguration, med token i dess hemlighetsfil (till exempel `sidekick_webhook_token: "Bearer <token>"`):

```yaml
rest_command:
  sidekick_add_shopping_item:
    url: "https://<din-domän>/webhooks/v1/shopping-items"
    method: post
    headers:
      Authorization: !secret sidekick_webhook_token
      Idempotency-Key: "ha-{{ now().timestamp() }}-{{ name | slugify }}"
      Content-Type: application/json
    payload: '{"name": {{ name | tojson }} }'
    timeout: 10
```

Anropa det från en automation eller ett skript med `action: rest_command.sidekick_add_shopping_item` och `data: {name: "Milk"}`. En uppgift fungerar likadant mot `/webhooks/v1/tasks` med `{"title": ...}`.

## Tasker

Lägg till åtgärden Net, HTTP Request:

- Metod `POST`, URL `https://<din-domän>/webhooks/v1/tasks`
- Rubriker (en per rad): `Authorization: Bearer <token>`, `Idempotency-Key: tasker-%TIMES` och `Content-Type: application/json`
- Innehåll: `{"title": "Kolla posten", "due": "2030-05-17"}`

`%TIMES` är aktuell tid i sekunder, så varje körning får en ny nyckel. Spara token i en Tasker-variabel som inte delas när du exporterar en profil.

## Om det inte fungerar

| Du ser | Trolig orsak |
| --- | --- |
| `404` på sökvägen | `SIDEKICK_WEBHOOKS_ENABLED` är inte `true` (eller så startades inte API:et om), eller så vidarebefordrar proxyn inte sökvägen. Ett `404` med `not_found` och utan `reason` kan också betyda att du inte har någon aktiv inköpslista. |
| `401` | Token är fel, återkallad eller utgången, eller rubriken är inte `Authorization: Bearer <token>`. |
| `403` `scope_missing` | Token skapades utan behörigheten för åtgärden. Skapa en ny token med behörigheten. |
| `409` `idempotency_key_reused` | Samma `Idempotency-Key` användes med annat innehåll. Använd en ny nyckel för varje åtgärd. |
| `422` | Innehållet saknar ett fält eller har ett okänt fält, ett för långt värde, eller `Idempotency-Key` saknas. |
| `429` | Token har använt upp sin gräns. Vänta så många sekunder som `Retry-After` anger, eller skapa en token med högre `--rate-limit`. |
