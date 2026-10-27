# Fonts for PDF exports (WP-035, D-100 D8)

Bundled so PDF exports work offline and air-gapped; WeasyPrint loads them only through the
report URL fetcher (app/modules/analytics/infra/pdf.py), never from the network.

| File | Font | Licence |
|---|---|---|
| NotoSans-Regular.ttf, NotoSans-Bold.ttf | Noto Sans (Latin) | SIL Open Font License 1.1, OFL-NotoSans.txt |
| NotoNaskhArabic-Regular.ttf, NotoNaskhArabic-Bold.ttf | Noto Naskh Arabic (Arabic, Urdu) | SIL Open Font License 1.1, OFL-NotoNaskhArabic.txt |

Source: https://github.com/notofonts (hinted TTF, downloaded 2026-10-28), unmodified.
