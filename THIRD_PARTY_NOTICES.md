# AniRSS third-party notices

This notice applies to the AniRSS 0.1.5 Windows x64 binary distribution built
on 2026-08-10. AniRSS itself is licensed under the MIT License; third-party
components remain subject to their own licenses.

The versions below were determined from the packaged PE version resources,
Python package metadata, runtime version APIs, the PyInstaller analysis, and
printable version strings in statically linked binaries. License files are in
[`resources/licenses`](resources/licenses/).

## Components included in the Windows distribution

| Component | Version in the package | License | Upstream | Included license text |
| --- | --- | --- | --- | --- |
| CPython | 3.12.13 | Python Software Foundation License Version 2 and the additional notices reproduced by CPython | [CPython v3.12.13](https://github.com/python/cpython/tree/v3.12.13) | `Python-3.12.13-LICENSE.txt` |
| PySide6 and PySide6 Essentials Python bindings | 6.11.1 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; a valid Qt commercial license is an alternative | [Qt for Python source](https://code.qt.io/cgit/pyside/pyside-setup.git/?h=6.11.1) | `GNU-LGPL-3.0-only.txt`, `GNU-GPL-3.0-only.txt`, `Qt-Commercial-Reference.txt` |
| shiboken6 runtime | 6.11.1 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`; a valid Qt commercial license is an alternative | [Qt for Python source](https://code.qt.io/cgit/pyside/pyside-setup.git/?h=6.11.1) | same files as PySide6 |
| Qt shared libraries and plugins used by AniRSS | 6.11.1 | The open-source distribution relies on `LGPL-3.0-only` for the included Core, Gui, Network, OpenGL, Widgets and SVG modules; GPL and commercial alternatives are available as stated by Qt | [Qt 6.11 licensing](https://doc.qt.io/qt-6/licensing.html) | `GNU-LGPL-3.0-only.txt`, `GNU-GPL-3.0-only.txt`, `Qt-Commercial-Reference.txt` |
| libtorrent and its Python binding | 2.0.13 / runtime `2.0.13.0` | BSD 3-Clause | [PyPI package 2.0.13](https://pypi.org/project/libtorrent/2.0.13/), [upstream 2.0 branch](https://github.com/arvidn/libtorrent/tree/RC_2_0), and [project license page](https://libtorrent.org/) | `libtorrent-BSD-3-Clause.txt` |
| OpenSSL, statically linked into the libtorrent Python extension | 3.6.1 (version string: `OpenSSL 3.6.1 27 Jan 2026`) | Apache License 2.0 | [OpenSSL 3.6.1 source](https://github.com/openssl/openssl/tree/openssl-3.6.1) | `OpenSSL-Apache-2.0.txt` |
| OpenSSL shared libraries used by the packaged Python/Qt network stack | 3.6.3 | Apache License 2.0 | [OpenSSL 3.6.3 source](https://github.com/openssl/openssl/tree/openssl-3.6.3) | `OpenSSL-Apache-2.0.txt` |
| libffi | 3.4.4 (the CPython 3.12.13 Windows external dependency) | MIT-style libffi license | [libffi v3.4.4](https://github.com/libffi/libffi/tree/v3.4.4) | `libffi-3.4.4-LICENSE.txt` |
| SQLite | 3.50.4 | Public Domain | [SQLite 3.50.4](https://www.sqlite.org/releaselog/3_50_4.html) | `SQLite-Public-Domain.txt` |
| PyInstaller bootloader and related embedded files | 6.21.0 | `GPL-2.0-or-later WITH Bootloader-exception`; bundled runtime hooks are Apache-2.0 | [PyInstaller v6.21.0](https://github.com/pyinstaller/pyinstaller/tree/v6.21.0) | `PyInstaller-6.21.0-COPYING.txt` |
| zlib incorporated into Qt Core | 1.3.2 | zlib License | [Qt 6.11.1 attribution](https://doc.qt.io/qt-6/qtcore-attribution-zlib.html) and [zlib](https://zlib.net/) | `zlib-1.3.2-LICENSE.txt` |
| Mesa llvmpipe software OpenGL renderer (`opengl32sw.dll`) | Version is not encoded in the distributed DLL; it is the build shipped by Qt 6.11.1 | MIT and Boost Software License 1.0 notices documented by Qt | [Qt's llvmpipe attribution](https://doc.qt.io/qt-6/qt-attribution-llvmpipe.html) | `Qt-Mesa-llvmpipe-NOTICE.txt`, `Boost-1.0-LICENSE.txt` |
| Boost libraries statically linked into the libtorrent Python extension | Exact Boost release is not encoded in the wheel binary | Boost Software License 1.0 | [Boost license](https://www.boost.org/LICENSE_1_0.txt) | `Boost-1.0-LICENSE.txt` |
| Microsoft Visual C++ Runtime DLLs | 14.44.35211.0 | Microsoft Visual Studio 2022 redistributable terms | [Microsoft redistribution documentation](https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files) | Not reproduced; see the release-review item below |

The CPython license file also reproduces the notices for third-party code
incorporated into the Python standard library. Qt maintains the authoritative
list of code incorporated into its modules at [Third-Party Code Used in
Qt](https://doc.qt.io/qt-6/licenses-used-in-qt.html).

The audited Qt plugin payload is limited to:

- `generic/qtuiotouchplugin.dll`
- `iconengines/qsvgicon.dll`
- `imageformats/qgif.dll`, `qicns.dll`, `qico.dll`, `qjpeg.dll`, `qsvg.dll`,
  `qtga.dll`, `qtiff.dll`, `qwbmp.dll`, and `qwebp.dll`
- `networkinformation/qnetworklistmanager.dll`
- `platforms/qdirect2d.dll`, `qminimal.dll`, `qoffscreen.dll`, and
  `qwindows.dll`
- `styles/qmodernwindowsstyle.dll`
- `tls/qcertonlybackend.dll`, `qopensslbackend.dll`, and
  `qschannelbackend.dll`

## Qt open-source distribution notice

AniRSS uses the Qt/PySide shared libraries dynamically. Recipients may replace
those shared libraries with compatible modified versions. Nothing in the AniRSS
license is intended to prohibit reverse engineering for debugging modifications
to the LGPL-covered libraries. The corresponding upstream source is available
at the exact-version links above.

`GNU-GPL-3.0-only.txt` is intentionally retained even though the final package
contains no GPL-only Qt module: LGPLv3 incorporates GPLv3, and LGPLv3 section 4
requires a Combined Work to be accompanied by both the GNU GPL and LGPL texts.

A valid commercial Qt license changes which Qt terms apply. Merely including
`Qt-Commercial-Reference.txt` does not grant a commercial Qt license.

## Release-review boundaries

The following items still require a human release/legal review before publishing
the Windows archive:

1. The final audited build contains no filename matching `qml`, `quick`,
   `virtualkeyboard`, or `pdf`. Keep that exclusion as a release gate. An earlier
   pre-release build included Qt Virtual Keyboard, which is GPL-3.0-only for
   open-source users and must not return to the intended LGPL/MIT package unless
   the whole distribution is intentionally made GPLv3-compliant or a commercial
   Qt license is held.
2. Preserve PySide6, shiboken6, and Qt as replaceable shared components and
   confirm that the PyInstaller layout meets LGPL section 4 requirements. For a
   durable source offer, mirror the exact Qt for Python and Qt 6.11.1 sources
   with the release instead of relying only on upstream URLs.
3. Generate or obtain the Qt 6.11.1 SPDX SBOM for the exact DLL/plugin subset and
   reproduce all applicable embedded third-party notices. The links above are
   authoritative, but this repository does not yet mirror every Qt-internal
   attribution (for example image codecs, PCRE2, Unicode data and compression
   code).
4. The libtorrent 2.0.13 PyPI wheel does not install its `COPYING` file. Its
   metadata declares `BSD`, and the included text is the upstream libtorrent
   2.0-series BSD notice (verified against the `RC_2_0` branch and v2.0.12).
   Upstream had no published `v2.0.13` source tag during this audit; obtain and
   re-check the exact source corresponding to the PyPI wheel before release.
5. The libtorrent wheel statically contains Boost, OpenSSL and compression code,
   but does not expose a complete machine-readable build SBOM. OpenSSL 3.6.1 was
   identified from its embedded version string; the exact Boost and compression
   library versions require confirmation from the wheel publisher/build recipe.
6. Confirm that the project owner has the right to redistribute the Microsoft
   Visual C++ 14.44.35211 runtime files under the applicable Visual Studio terms.

This file is an attribution record, not legal advice.
