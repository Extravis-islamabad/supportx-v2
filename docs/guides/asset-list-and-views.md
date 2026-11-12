# The asset list, views and linked records

What asset managers and technicians use since WP-049b session 4a (parity 07 REQ-AST-044, 045,
046 and 047).

## The product type tree

- Beside the asset list, the **Product types** tree shows every type with how many assets it
  holds, counting the types below it. Choose a type to list it and every type below it: choosing
  **Computer** lists workstations, laptops and servers; choosing **Workstation** lists only
  workstations. **All types** clears the choice.
- The counts follow the view you picked (for example, only the assets in stock) and only count
  assets you are allowed to see.
- The tree works from the keyboard: Tab moves into it, the Up and Down arrows move between rows,
  Right opens a type or moves to its first type below, Left closes it or moves up to its parent
  (the other way round in Arabic and Urdu), Home and End go to the first and last row, and Enter
  or Space choose the row.
- On a phone the tree sits above the list.

## Views

- The **View** box on the toolbar offers the built-in views: all assets, my assets (those you
  hold), assets in stock, loanable assets, warranty ending soon (within the days set in the asset
  settings), scan failures (assets whose latest scan failed) and recently discovered (assets
  discovery found in the last 30 days). Recently discovered stays empty until discovery is set
  up; the list says so.
- **Views** opens the views drawer. There you can:
  - **star a view** to make it a favourite: favourites come first in the View box;
  - **save the list as it is filtered now** (the type chosen in the tree and the search) as a
    view of your own, with a name;
  - **remove** a view you saved.
- Your views, stars and column widths are yours only. They follow you to your other windows at
  once.
- The list's link keeps the view and the type, so you can bookmark or share it. Whoever opens it
  still sees only the assets they are allowed to see.

## Columns

- The list shows the asset tag, name, user, department, parent asset, product, product type,
  state, site and serial number.
- Drag a column's edge, or focus it and use the arrow keys, to make it wider or narrower. The
  widths are kept for you, per view. **Reset widths** puts them back.

## Picking an asset on a record

- The asset picker on incidents and service requests finds an asset by part of its name, tag,
  barcode, serial number or the serial discovery found. The API behind it can also narrow to a
  product type (with the types below it) and a site, and page through long results; the forms'
  pickers gain those controls when the record screens adopt them.
- It only offers assets you are allowed to see; someone without asset access sees only the
  assets they hold.

## Linked records

- Once work items offer it, the asset page shows **Linked records**: per kind (incidents,
  service requests, problems, changes, releases), how many are still worked (open, paused, or
  resolved and not yet closed) and how many in all. Choose a kind to list them.
- The counters count only the records you are allowed to see (D-158), and list the same ones.
- Until work items offer the links, the panel does not show.

## Raising a work item from an asset

- On the asset page, **Raise an incident**, **Raise a service request** or **Raise a change**
  (in the actions, for those who may create them) asks for a template, or a catalogue item for a
  request. Only templates you may use are offered.
- The normal form then opens with the asset and the person who holds it filled in; everything
  stays editable. A change's form takes no asset yet, so only the person is filled in.
- Once work items report it, the asset's history shows "INC-n raised from this asset".

## Changing many assets at once

- Pick rows (up to 1,000) and choose **Change selected**: edit a few shared fields (site,
  location, cost centre, GL code), change their state, assign them to a person or a department
  (or to no one), or move them to the trash.
- The change runs in the background, as you. You can keep working; the dialog shows how far it
  got, then lists every asset it skipped and why (an asset at a site you do not manage, a move
  its life cycle does not allow, a change someone else made first). Nothing is changed silently.
- Costs and identifiers (tag, serial number, barcode) are changed one asset at a time.
- Moving to the trash never deletes: the assets can be restored from the trash.

## Merging duplicates

- Pick exactly two assets and choose **Merge**. The asset to keep comes first: the one
  discovery found, or the one scanned most recently. **Keep the other one** swaps them.
- For each field, choose whose value stays. Costs show only if you may see them.
- You need to manage both assets. Assets at two sites can be merged only by someone who
  manages both sites.
- After the merge, the duplicate is in the trash. Its tag, serial number and barcode still find
  the asset you kept, and opening the duplicate opens the asset you kept. Its linked records,
  costs, notes, fitted parts, groups and relationships move to the asset you kept.
- Restoring the duplicate from the trash asks first: it comes back on its own, and what moved
  stays with the asset you kept.

## Importing from a file

- **Import** in the list's header takes a CSV (UTF-8) or Excel file of assets, consumables or
  vendors, up to 5 MB and 20,000 rows. The first row names the columns (for assets: Name,
  Product, Asset tag, Serial number, Barcode, Site, Location, Vendor, Acquired on, Warranty
  expires on, Expires on, Description, Cost centre, GL code, Purchase price, Purchase tax,
  Currency).
- Choose whether rows only add, only update, or both, and how an existing record is found
  (asset tag or serial number; a consumable by its product; a vendor by its name).
- **Check the file** first: nothing changes. You see how many records would be added and
  updated and every row with a problem; **Download the rows with problems** saves them as a
  file. **Import now** then applies the same file.

## Exporting the list

- **Export** saves the list as you see it (the type tree node, your search, a saved view) as an
  Excel or CSV file; it is prepared in the background and appears under **My exports**.
- Costs (purchase price, tax, book value, total cost) are included only for people who may see
  asset costs. A built-in view other than All assets cannot be exported; the button says so.
