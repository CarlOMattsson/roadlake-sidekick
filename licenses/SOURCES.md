# Where to get the source of the copyleft parts of this image

Roadlake Sidekick is source available under [LICENSE.md](../LICENSE.md). This image also carries
components under other licenses; [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) lists all of them. Some
of those licenses (LGPL, GPL) ask that the source of the component can be obtained. This file says where.
Third-party components are governed solely by their own licenses. Nothing in LICENSE.md, including Additional Terms
section 2, restricts any right those licenses give you. In particular you may modify, replace or relink `psycopg`,
`psycopg-binary` and the libraries they load, and reverse engineer Sidekick as far as needed to debug such modifications.
The license key functionality is part of Sidekick's own code, not of these components. Libraries offered under
"LGPL-2.1 or later" are conveyed here under the LGPL version 3.
The license texts are in this directory:
[LGPL-3.0.txt](LGPL-3.0.txt), [LGPL-2.1.txt](LGPL-2.1.txt), [GPL-3.0.txt](GPL-3.0.txt), [Apache-2.0.txt](Apache-2.0.txt).

## Python: psycopg, psycopg-binary (LGPL-3.0-only)

psycopg is imported by the API process as an ordinary library and is not modified. The installed copy is in
`/app/backend/.venv/lib/python3.13/site-packages/psycopg*` and can be replaced by installing another version
into that directory (or by mounting one over it).

To replace psycopg with your own build, derive an image (the layout is plain files in the venv; there is no zipapp,
freezing or hash check):

```dockerfile
FROM <image>
USER root
RUN pip install --no-deps --upgrade --target /app/backend/.venv/lib/python3.13/site-packages ./my-psycopg
USER sidekick
```

- Source of `psycopg` and `psycopg-binary`: https://github.com/psycopg/psycopg at tag `3.3.4`
  (directories `psycopg/` and `psycopg_binary/`), and the PyPI release page https://pypi.org/project/psycopg/3.3.4/
  (which has the source distribution).
- Build scripts for the binary wheel: https://github.com/psycopg/psycopg/tree/3.3.4/tools/build
- Exact versions in this image: `uv.lock` in the repository (backend/uv.lock), and the `sboms/` directory in
  `psycopg_binary-3.3.4.dist-info/` inside the image lists the bundled libraries with their package versions.

## Python: libraries bundled inside the psycopg-binary wheel

The wheel carries its own copies of these shared libraries in `psycopg_binary.libs/`. They were built
by the psycopg project on CentOS 7 (manylinux2014) and are listed with versions in the SBOM named above.

| Library | License | Source |
| --- | --- | --- |
| libpq | PostgreSQL | https://www.postgresql.org/ftp/source/ |
| OpenSSL 3 (libssl, libcrypto) | Apache-2.0 | https://www.openssl.org/source/ |
| MIT Kerberos (krb5, gssapi, k5crypto, com_err) | MIT | https://vault.centos.org/7.9.2009/updates/Source/SPackages/ (`krb5-1.15.1-55.el7_9.src.rpm`) |
| Cyrus SASL (libsasl2) | BSD-style (CMU) | https://vault.centos.org/7.9.2009/ (`cyrus-sasl-2.1.26-24.el7_9`) |
| OpenLDAP (libldap, liblber) | OpenLDAP Public License | https://www.openldap.org/software/download/ |
| PCRE (libpcre) | BSD-3-Clause | https://vault.centos.org/7.9.2009/os/Source/SPackages/ (`pcre-8.32-17.el7.src.rpm`) |
| libselinux | public domain | https://vault.centos.org/7.9.2009/ (`libselinux-2.5-15.el7`) |
| **libkeyutils** | **LGPL-2.1-or-later** | https://vault.centos.org/7.9.2009/os/Source/SPackages/ (`keyutils-1.5.8-3.el7.src.rpm`) |
| **libcrypt** (glibc / libxcrypt of the build host) | **LGPL-2.1-or-later** | https://vault.centos.org/7.9.2009/ (the `glibc` source RPM of CentOS 7.9) |

The CentOS 7 source packages are kept at https://vault.centos.org/7.9.2009/ (`os/Source/SPackages/` and
`updates/Source/SPackages/`). The two LGPL libraries (bold) can be replaced by placing another build with the
same soname next to the others, or by installing `psycopg[c]` / `psycopg[binary]` builds against your own
system libraries instead.

## Python: certifi (MPL-2.0)

Shipped unmodified, as source files. Source: https://github.com/certifi/python-certifi and the PyPI release.

## Base image: Debian (python:3.13-slim)

The runtime image is `python:3.13.13-slim` (Debian 13 "trixie"), pinned by digest in `backend/Dockerfile` and unmodified apart from
the files we add under `/app` and `/usr/share/doc/sidekick`. It contains Debian packages under GPL, LGPL and
other licenses (bash, coreutils, glibc, dpkg, and others). Their license texts are in `/usr/share/doc/<package>/copyright`
inside the image, and their source is the Debian source package of the same name and version:

- List what is installed: `docker run --rm --entrypoint dpkg-query <image> -W -f '${Package} ${Version} ${source:Package} ${source:Version}\n'`
- Get the source of one package at the exact version: https://snapshot.debian.org/ or https://sources.debian.org/
  (or `apt-get source <package>=<version>` with a `deb-src` line for the Debian release the base image is built on;
  `/etc/os-release` in the image names the release).
- The Docker Official Image recipe for `python`: https://github.com/docker-library/python
- Each release has an SBOM (the release bundle) that lists the packages of the image.

CPython itself is under the PSF license (https://github.com/python/cpython).

## Written offer

The links above are the quickest way to the source. In addition, for three years after we last distributed a release,
the licensor will give anyone, on request, the complete corresponding source of every GPL- or LGPL-licensed component
in that release's image, for no more than the cost of the transfer. Ask through an issue at
https://github.com/CarlOMattsson/roadlake-sidekick and name the release version or image digest.
