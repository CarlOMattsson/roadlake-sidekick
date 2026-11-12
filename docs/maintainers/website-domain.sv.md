# Publicera webbplatsen på roadlake.com

[English](website-domain.md)

<!-- description: Engångsuppsättning för att servera Sidekicks webbplats från roadlake.com med GitHub Pages: DNS-poster, domänverifiering, egen domän och HTTPS. -->

Engångsuppsättning för att servera webbplatsen (`website/`) från `https://roadlake.com` med GitHub Pages. Bara
repots ägare kan göra den. Arbetsflödet `pages` (`.github/workflows/pages.yml`) bygger och publicerar webbplatsen vid en
publicerad release eller för hand; det behöver inga hemligheter.

## 1. Pages-källa

I repot: **Settings > Pages > Build and deployment > Source: GitHub Actions**. Begränsa miljön `github-pages` till
`main` och taggar (Settings > Environments).

## 2. Verifiera domänen (gör det först)

Verifieringen hindrar att någon annan tar över domänen via en hängande DNS-post.

1. Öppna kontoinställningarna: **Settings > Pages > Add a domain**, ange `roadlake.com`.
2. GitHub visar en TXT-post. Skapa den hos domänregistratorn: namn `_github-pages-challenge-carlomattsson`
   (under `roadlake.com`), värde enligt GitHub.
3. Vänta tills DNS har spridits och tryck på **Verify**. Behåll TXT-posten efteråt.

## 3. DNS-poster hos registratorn

| Typ | Namn | Värde |
| --- | --- | --- |
| A | `@` | `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` (fyra poster) |
| AAAA | `@` | `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153` (fyra poster) |
| CNAME | `www` | `carlomattsson.github.io` (utan repots namn) |
| TXT | `_github-pages-challenge-carlomattsson` | värdet GitHub visar (steg 2) |

Ta bort andra A-, AAAA- eller CNAME-poster för `@` och `www`. Adresserna är de som står i
[GitHubs dokumentation](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site);
kontrollera den innan du anger dem, eftersom GitHub kan ändra dem.

## 4. Egen domän och HTTPS

1. **Settings > Pages > Custom domain**: ange `roadlake.com` och spara. Med GitHub Actions som källa behöver GitHub
   ingen `CNAME`-fil i webbplatsen, och bygget skapar ingen.
2. Vänta tills DNS-kontrollen går igenom (upp till 24 timmar) och kryssa sedan i **Enforce HTTPS**. Certifikatet
   utfärdas av GitHub; alternativet kan ta upp till 24 timmar på sig att dyka upp.
3. `www.roadlake.com` omdirigeras automatiskt till `roadlake.com`.

## 5. Lämna webbplatsvariablerna tomma

Lämna repovariablerna `SITE_URL` och `SITE_BASE` (Settings > Secrets and variables > Actions > Variables)
**tomma**. Tomma värden faller tillbaka på `https://roadlake.com` utan baskatalog (`website/site-config.mjs`), vilket en
egen domän i roten kräver. Sätt dem bara för att publicera någon annanstans, till exempel en projektsida på
`https://<ägare>.github.io/<repo>` (`SITE_BASE=/<repo>`).

## Kontroll

```sh
dig +short roadlake.com A
dig +short www.roadlake.com CNAME
curl -sI https://roadlake.com/ | head -n 1
```

Kör sedan arbetsflödet `pages` för hand (Actions > pages > Run workflow) och öppna `https://roadlake.com`. Se också:
[Släpp en version](release.sv.md).
