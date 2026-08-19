# Third-party license files

This directory is copied into the AniRSS Windows distribution. The authoritative
component/version mapping and release-review boundaries are in the repository
root file `THIRD_PARTY_NOTICES.md`.

| File | Covers |
| --- | --- |
| `Python-3.12.13-LICENSE.txt` | CPython 3.12.13 and the additional notices shipped by CPython |
| `GNU-LGPL-3.0-only.txt` | Qt/PySide6/shiboken6 open-source LGPL terms |
| `GNU-GPL-3.0-only.txt` | GPLv3 text incorporated by LGPLv3 and Qt's GPL alternative |
| `Qt-Commercial-Reference.txt` | Reference notice for holders of a valid commercial Qt license; it grants no license by itself |
| `libtorrent-BSD-3-Clause.txt` | libtorrent 2.0-series BSD notice |
| `OpenSSL-Apache-2.0.txt` | OpenSSL 3.x |
| `libffi-3.4.4-LICENSE.txt` | libffi 3.4.4 |
| `SQLite-Public-Domain.txt` | SQLite public-domain statement |
| `PyInstaller-6.21.0-COPYING.txt` | PyInstaller bootloader exception and applicable GPL/Apache terms |
| `zlib-1.3.2-LICENSE.txt` | zlib 1.3.2 incorporated into Qt Core |
| `Boost-1.0-LICENSE.txt` | Boost code statically incorporated by binary dependencies |
| `Qt-Mesa-llvmpipe-NOTICE.txt` | Qt's official attribution for `opengl32sw.dll` |

Before release, copy `THIRD_PARTY_NOTICES.md` beside the executable as well as
keeping this directory intact. The audited final build contains no QML, Qt
Quick, Qt Virtual Keyboard, or Qt PDF files; keep that exclusion as a release
gate for the intended LGPL/MIT licensing route.
