# Asset financials, notes and history

What asset managers and technicians see on an asset's page since WP-049b session 2 (parity 07
REQ-AST-036 to 038 and 048 to 050).

## Who sees the money

Costs, depreciation and book value need the right **View asset costs and values**
(`assets.view_financials`). The built-in Asset manager role and administrators hold it; a custom
role can add it. Without it the asset page has no Financials tab and no value in its side panel,
and the API refuses (403). Changing cost lines or the asset's depreciation also needs the right to
manage the asset.

## Financials tab

- **Summary:** purchase cost (price plus tax, or the price alone when the asset settings say the
  cost excludes tax), current book value, operational cost and the total cost of ownership
  (purchase + operational + disposal costs).
- **Currency:** every total is in the tenant's base currency (Admin > Organisation). Nothing is
  converted: an asset bought in another currency says so above the totals.
- **Cost lines:** Add cost records a move, service, contract, other or disposal cost with its date,
  amount and a description. A disposal record's own cost counts as disposal too. Removing a line
  keeps its history.
- **Depreciation:** Configure depreciation sets the asset's own method, useful life and salvage
  value. Anything left empty comes from the product (Admin > Assets > Products); each setting shows
  where it came from. Methods:
  - Straight line: the same amount each year.
  - Declining balance: 1.5 times the straight-line rate of the value left each year.
  - Double declining balance: twice that rate.
  - Sum of the years' digits: most in the first year, less each year after.
  - No depreciation: the book value stays the purchase cost, whatever the product says.

  Both declining methods switch to straight line once that writes off more, so the book value
  reaches the salvage value at the end of the useful life. Within a year depreciation is spread by
  month: a month counts once its day of the month is reached. The schedule lists each year's
  opening value, depreciation and closing value.
- **Cost centre and GL code** are on the asset's form (free text until purchasing brings real cost
  centres). A new asset takes its product's GL code unless one is typed.

## Notes and files tab

- Anyone who may see the asset can add a note (for example a repair). Type @ to mention a
  colleague: they are told if they can see the asset; if not, the page says who was not told.
- Authors edit and delete their own notes; others' need the right to manage the asset. An edited
  note shows "edited", which opens its earlier versions. A deleted note leaves a line saying who
  deleted it and when.
- Attachments (invoices, photos) are scanned like every file; an infected file is refused. People
  who may manage the asset add and remove them.

## History tab

Every change, newest first, with who made it, when and how (in the app, through the API, by a
rule, an import ...). Narrow it with **State** (state moves only) or **Assignment** (who holds it,
including loans), or by field, how it was made, person and days. Notes and cost lines appear as
changes too, without amounts.

## Reports

Asset reports can group by cost centre and GL code. For people who may see the money they also
offer each asset's book value today and its total cost of ownership (refreshed when the asset's
money changes and once a day).
