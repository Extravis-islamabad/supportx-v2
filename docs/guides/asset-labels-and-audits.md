# Asset labels, audits and scan history

What asset managers, technicians and auditors use since WP-049b session 3 (parity 07
REQ-AST-039, 042, 043, 054 and 056).

## Labels

- **Print labels:** pick assets in the asset list (anyone who may see assets can) or open an
  asset, then **Print labels**. Choose the layout (a small cable label or a laptop label), the
  code (a QR code or a Code 128 barcode) and the language. Up to 500 labels go in one PDF, one
  label per page, so a label printer cuts them apart.
- **What the code holds:** a QR code holds only the link to the asset's page. Whoever scans it
  must sign in and be allowed to see the asset; anyone else learns nothing about it. A barcode
  holds the asset's tag, which is printed beside it anyway.
- **The file:** the PDF is made in the background. The dialog (and the asset's **Labels** tab)
  shows when it is ready; only the person who asked can download it, for a week.
- **Label history:** every print and reprint is kept, with who printed what and when. **Reprint**
  makes the same labels again and adds a history row.
- You can only print labels for assets you are allowed to see: if one of them is not, nothing is
  printed.

## Audits

- **Plan:** Assets › Audits › **Plan audit** (people who manage assets). Give it a name, a type
  (by technicians, or a self-audit by the people holding the assets), the scope (sites, product
  types with the types below them, asset groups; an empty part means "any"), planned dates and
  the auditors.
- **Start:** the assets in scope now become the audit's expected items, and the scope can no
  longer change. A self-audit then asks each person holding one of them to confirm it in the
  portal (My assets); each audit asks again. Confirming marks the asset found; saying something
  is wrong marks it missing, and the discrepancy list shows the person's comment.
- **Mark:** the named auditors mark items while the audit runs: scan or type a code (the label's
  link, a tag, serial or barcode) with the site where it is, or mark a row found, missing or
  damaged. An asset found at another site than expected is marked **wrong place**. An asset
  scanned that is not on the list is added as found unexpectedly. Everyone following the audit
  sees the progress (found out of expected) move without refreshing.
- **Settle discrepancies:** the **Discrepancies** tab lists what is missing, damaged, in the wrong
  place or unexpected (and, once closed, what was never marked). Select rows and choose **Move to
  site**, **Change state** or **Assign**. Each asset changes through its usual rules (its life
  cycle, your permissions) and its history says the change came from the audit. Rows that could
  not change are reported with the reason.
- **Close:** a closed audit can no longer change; questions still open to holders are withdrawn.

## Scan history

- An asset's **Scans** tab lists each scan: when, where it came from (agent, probe, import) and
  its type, whether it worked (a failed scan says why) and what changed since the previous one
  (hardware added or removed, software installed or removed).
- Scans older than the retention in Admin › Assets › Settings (6 months by default) are removed
  once a day. The asset, its history and its last scan time stay.

## Assets not scanned for too long

- Admin › Assets › Settings › **Assets not scanned for too long** (people who configure assets).
  Off by default. For the product types chosen (all when none), an asset whose last good scan is
  older than the number of days is moved to a chosen state, or to the trash, from which it can be
  restored with its history. Nothing is ever deleted. Assets never scanned and disposed assets
  are left alone.
- The rule follows the asset life cycle: only states a life cycle of the chosen types can move an
  asset to are offered. An asset whose current state has no move there is skipped, keeps its
  state, and is listed in the run with the reason.
- **Show the effect** first says how many assets it would change now; it can be saved only after
  that. The rule runs every hour; each run that changes something is listed with what it changed,
  and each asset's history names the rule.
