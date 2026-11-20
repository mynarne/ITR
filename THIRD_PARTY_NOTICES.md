# Third-party notices / 제3자 저작물 고지

The [MIT license](LICENSE) covers ITR contributors’ original software, documentation and artwork. The sample report embeds the four upstream font programs identified below. Those programs retain their own notices and licenses. Please keep the notices with copies of the report.

ITR의 원저작물에는 루트의 MIT 라이선스가 적용된다. 예제 PDF에 내장된 글꼴에는 아래 권리자의 고지와 라이선스가 각각 적용된다. ITR은 내장 글꼴 프로그램의 바이트를 변경하지 않았다.

## Embedded fonts / 내장 글꼴

The audited [sample PDF](examples/preview/report.pdf) has SHA-256 `0a452738a9530ca8ccee7b909f499b5c1d44b097379f277d4bd8c36c2329a445`. After decoding the PDF streams, each embedded program matched its corresponding resource in the upstream MuPDF 1.26.11 tag byte for byte. The file also references Helvetica (PDF font object 65) without embedding a Helvetica font program.

| PDF font object | Upstream file | Program format and revision | SHA-256 of the decoded program |
| --- | --- | --- | --- |
| 3 | `urw/NimbusSans-Bold.cff` | CFF, internal version 1.00 | `d4ea80d1d0e29a1e950808009ca8f96fe07a0670b60b556f6b2cf0705337fa9f` |
| 15 | `urw/NimbusSans-Regular.cff` | CFF, internal version 1.00 | `366720e054067fa49d030f58005c739fc787dcc9727a9327a28767777791d706` |
| 36 | `urw/NimbusMonoPS-Regular.cff` | CFF, internal version 1.00 | `2e8380cc08f257fb0b301079323a442918ec9d69582c95607da5543b362aa6d6` |
| 9 | `droid/DroidSansFallback.ttf` | TrueType, head revision approximately 2.54 | `ee38813ea00c3e32add4268fff7fff9e39417b4913cb13be2415164a47807cc2` |

### Nimbus Sans Bold, Nimbus Sans Regular and Nimbus Mono PS Regular

All three programs carry the embedded CFF notice `(URW)++,Copyright 2014 by (URW)++ Design & Development`. The upstream notice for this resource directory reads `Copyright 2016 by (URW)++ Design & Development.` and distributes the fonts under the **SIL Open Font License 1.1**. The original notice and complete license are included together. [Bundled OFL notice and license](LICENSES/URW-OFL-1.1.txt) · [Matching font resources](https://github.com/ArtifexSoftware/mupdf/tree/1.26.11/resources/fonts/urw) · [Upstream OFL notice](https://raw.githubusercontent.com/ArtifexSoftware/mupdf/1.26.11/resources/fonts/urw/OFL.txt) · [SIL guidance on embedding](https://openfontlicense.org/ofl-faq/)

### Droid Sans Fallback Regular

Copyright (c) 2005-2008, The Android Open Source Project. The font is distributed under the **Apache License, Version 2.0**. The embedded font’s name table carries family and style. Its numeric version comes from the TrueType `head` table. The complete upstream NOTICE and the Apache Software Foundation’s license text accompany this report. [Bundled Droid NOTICE](LICENSES/Droid-NOTICE.txt) · [Bundled Apache License 2.0](LICENSES/Apache-2.0.txt) · [Matching font resource](https://github.com/ArtifexSoftware/mupdf/blob/1.26.11/resources/fonts/droid/DroidSansFallback.ttf) · [Upstream Droid NOTICE](https://raw.githubusercontent.com/ArtifexSoftware/mupdf/1.26.11/resources/fonts/droid/NOTICE) · [Apache Software Foundation license text](https://www.apache.org/licenses/LICENSE-2.0.txt)

## Optional tools / 선택 도구

PyMuPDF, MuPDF, Poppler, Playwright, Chromium and Node.js are separate tools that may be installed for rendering or verification. Their executable programs and libraries are distributed by their respective projects. The font inventory above applies to this specific PDF. A report generated with a different renderer or font configuration can embed different fonts.
