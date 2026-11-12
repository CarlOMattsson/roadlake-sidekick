# Publishing the website on roadlake.com

[Svenska](website-domain.sv.md)

<!-- description: One-time setup for serving the Sidekick website from roadlake.com with GitHub Pages: DNS records, domain verification, custom domain and HTTPS. -->

One-time setup for serving the website (`website/`) from `https://roadlake.com` with GitHub Pages. Only the repository
owner can do it. The `pages` workflow (`.github/workflows/pages.yml`) builds and deploys the site on a published release or by
hand; it needs no secrets.

## 1. Pages source

In the repository: **Settings > Pages > Build and deployment > Source: GitHub Actions**. Restrict the `github-pages`
environment to `main` and tags (Settings > Environments).

## 2. Verify the domain (do this first)

Verifying the domain stops anyone else from taking it over through a dangling DNS record.

1. Open your account settings: **Settings > Pages > Add a domain**, enter `roadlake.com`.
2. GitHub shows a TXT record. Create it at the domain registrar: name `_github-pages-challenge-carlomattsson`
   (under `roadlake.com`), value as shown by GitHub.
3. Wait for DNS to propagate, then press **Verify**. Keep the TXT record afterwards.

## 3. DNS records at the registrar

| Type | Name | Value |
| --- | --- | --- |
| A | `@` | `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` (four records) |
| AAAA | `@` | `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153` (four records) |
| CNAME | `www` | `carlomattsson.github.io` (no repository name) |
| TXT | `_github-pages-challenge-carlomattsson` | the value GitHub shows (step 2) |

Remove any other A, AAAA or CNAME record for `@` and `www`. The addresses are the ones in
[GitHub's documentation](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site);
check it before you enter them, since GitHub can change them.

## 4. Custom domain and HTTPS

1. **Settings > Pages > Custom domain**: enter `roadlake.com` and save. With a GitHub Actions source GitHub does not
   need a `CNAME` file in the site, and the build does not create one.
2. Wait for the DNS check to pass (up to 24 hours), then tick **Enforce HTTPS**. The certificate is issued by GitHub;
   the option can take up to 24 hours to appear.
3. `www.roadlake.com` redirects to `roadlake.com` automatically.

## 5. Leave the site variables empty

Leave the repository variables `SITE_URL` and `SITE_BASE` (Settings > Secrets and variables > Actions > Variables)
**empty**. Empty values fall back to `https://roadlake.com` with no base path (`website/site-config.mjs`), which is what a
custom domain at the root needs. Set them only to publish somewhere else, for example a project site at
`https://<owner>.github.io/<repo>` (`SITE_BASE=/<repo>`).

## Check

```sh
dig +short roadlake.com A
dig +short www.roadlake.com CNAME
curl -sI https://roadlake.com/ | head -n 1
```

Then run the `pages` workflow by hand (Actions > pages > Run workflow) and open `https://roadlake.com`. Related:
[Release a version](release.md).
