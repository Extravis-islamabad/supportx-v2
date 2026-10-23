# Area 7: Assets, CMDB and Purchase

The file `docs/specs/reference/sdp-asset-detail-reference.md` does not exist in my workspace, so I could not compare against it. I documented the asset detail page in full instead (see Screens).

## Navigation path
- **Assets:** left rail Assets (`/ui/assets`). The left tree holds Favorites, My Assets, All Assets, Scan Failures, Consumables, Software & Licenses, Asset Loan, Barcode/QR code, Replenishment, Acknowledgements, Asset Audit and Groups (the + creates a group). An "Asset Allocation Details" button searches by user or department.
- **CMDB:** left rail CMDB (`/ui/cmdb`).
- **Contracts:** `/ui/contracts`. **Purchase orders:** `/ui/purchaseOrders`. **Vendors:** only under Setup > Customization > Asset Management > Vendor, and inline via "New Vendor" on the contract and PO forms.
- **Setup:** Customization > Asset Management, CMDB, Purchase Management, Contract Management; Automation > Life Cycles > Asset, Asset Auto Assign, Workflows > Asset; Users & Permissions > Fine-Grained Access (Asset, CMDB); Probes & Discovery; Data Administration > Import Data.

## Screens and what they do
- **Asset tree and list.**
  - The tree is All Assets > IT (Access Points; Computers [Servers, Virtual Hosts, Virtual Machines, Workstations]; Mobile devices [Smartphones, Tablets]; Printers; Routers; Switches), Non-IT (Projector, Scanner) and Components (Keyboard).
  - List columns: Name, User, Department, Associated To, Product, Product Type, State, AssetTag, Asset Type, Asset Category.
  - Toolbar: New, Edit, Delete, Actions, Import from CSV, Assign Users. The Actions menu holds Add to Group, Configure Depreciation, Assign to Department/Site, Modify State, Modify Product, Reconcile, Mark as Loanable and Reprint Barcode.
- **New Asset form.** The form changes with the product type. The Workstation form has Computer, OS, Memory, Processors, Disks, Keyboard, Mouse, Monitors, Asset Details, Asset State and Network Details sections.
- **Asset detail page.**
  - Toolbar: Edit, Remote Control, Scan Now (not clicked), Assign, Print.
  - Actions menu: Update Credentials, Copy Asset, Modify Product, Mark as Loanable, Configure Depreciation, Raise Request > Create Incident / Create Service Request.
  - Tabs: Details, Hardware, Software, Relationships, Contracts, Financials, History, plus a State History view.
  - Relationships tab: a diagram with an Assigned To user node and Connected groups (Assets, Business Services, Components...), each with a + to add. An "Add Relationship" dropdown sits above it.
  - Right panel: last scan status and time, Product, State, Life cycle, Workflow, Purchase Order link, Age, Attachments, Assigned to User card, Loaned To card, and an Associated Requests counter (Pending and Total).
- **Scan Failures** (`/ui/failedWS`): empty. It has filters (All Computer, All) and an Actions menu.
- **Consumables:** list by consumable type. The New Consumable form is described under Fields.
- **Software and Licenses:** software list, licence list and agreements, covered under Software below.
- **Asset Loan.**
  - Loan Registry: Loan ID, Loaned Assets, user, department, site, start, expiry, status (On Loan, Expired, Closed), created by, created time. Filters: All Status, All Sites. Buttons: New Loan, Return Assets.
  - Loanable Assets: filters on Product Types, Products and Sites. Buttons: Mark Loanable Assets (search by name or barcode), Remove Loanable Assets, New Loan.
- **Barcode / QR code:** Generate Code and History. Generate Code offers cards for vendor codes, new assets and existing assets (Code 128).
- **Replenishment:** an intro page with "Configure Replenishment" (site and product-type stock thresholds with email alerts). I left it unconfigured.
- **Acknowledgements:** empty. Buttons Send Reminder and Download Details; filters on status, product and site.
- **Asset Audit:** empty. The New Asset Audit form is described under Fields.
- **Groups:** the New Group dialog offers Static or Dynamic groups (see Fields).
- **CMDB home.**
  - Left panel: Business Views, Baseline Configurations and a CI-type tree. The Business Service list has New, Modify CI Type, Modify State, Delete and Mark as CIs.
  - CI detail toolbar: Edit, Add Relationship, Relationship Map, Actions (Copy CI, Modify CI Type, Associations > Create Incident / Service Request / Change). Tabs: Details, Associations, Downtimes, Relationships, and an overflow with Baselines and History.
  - CI right panel: State, attached documents, "Link this CI", association counters (Requests, Problems, Changes, Releases, Contracts) and downtime counts (Scheduled, Active, Completed).
- **Relationship Map.**
  - It is full screen, with a Business View dropdown (Default View), three layouts (radial, hierarchical, tree), zoom, and a kebab menu (Export CSV, Export PNG, Show EOL CIs). Save and Close buttons are at the top.
  - Hovering a node shows a + to expand its neighbours.
  - Pressing Escape closes the whole map.
- **Business Views list:** Business View, Base CI, Last Modified Date. It has list and grid toggles and a Delete button.
- **Baseline Configurations list:** Name, Baseline Type, Created Time, Created By, Baseline Count, Baseline Creation.
- **Contracts list and detail.**
  - List views: All, Open, Expired, All (including renewed), Expired in the last 7 days, Trashed.
  - Detail toolbar: Edit, Print, Actions. Tabs: Details, Associations (Assets, Software Licenses, Purchase Orders), Renewals, and an overflow with Contract Relationship, Conversations, Contract Usage and History.
  - The right panel shows ID, owner, template, type, status, dates, cost, days to expire, attachments and vendor details.
- **Purchase order list.** Columns: PO #, Name, Requested by, Vendor, Created Date, Required By, Status, Total Cost. There are 16 views (All, Canceled, Approval Pending, Approved, Rejected, Partially Received, Closed, Overdue, Due in 7 days, Due in 30 days, Invoice Received, Open, Ordered, Payment Done, Received, Trashed).
- **PO detail.**
  - Toolbar: Edit, Delete, Print, Actions.
  - Tabs: Purchase Order, Approvals (with Edit Stage(s)), Invoice, Payment, and an overflow with Conversations and History.
  - Right panel: PO #, name, status, requester, vendor details, "Associate Service Requests: Attach" and "Associate Contracts: New | Attach".
- **Import:** Assets > Import from CSV opens Setup > Data Administration > Import Data > Import Wizard, with an Import History tab. I did not import anything.
- **Probes & Discovery** (no scan started): Probe, Credential Library, Domain Scan, Network Scan, SCCM Integration and Settings. All lists are empty.

## Fields

**New Business Service CI**

| Field | Type | Required | Options | Notes |
|---|---|---|---|---|
| Name | text | Yes | | |
| Description | text | No | | |
| State | select | No | Maintenance, Non-Operational, Operational (default); Decommissioned (End-of-Life) | Grouped Active / EOL |
| Location | text | No | | CMDB section |
| Managed By / Owned By | user pick | No | | |
| Business Impact | select | No | Affects Business, Affects Department, Affects Group, Affects User, High, Low, Medium | |
| Status | select | No | Operational, Non Operational, Ready, Repair In Progress, Retired, Standby | Service section |
| Service Support Hours | text | No | | |

**Add Relationship dialog:** Source CI; Relationship Type (Suggested, or Custom with an inverse column such as Connected to / Connected to); Destination CIs (multi-select picker with type tree and search).

**New CI Type (Setup):** CI Type Name*, API Name* (prefix `ci_`), Parent CI Type*, Icon, Description. Further tabs (Fields, Relationships, Sync Rules, Data Quality) unlock after saving.

**New Business View:** Base CI*, Business View Name*, Description; then the map editor with Save / Save as New.

**New Baseline Configuration:** Name*, Description, Baseline Type (Configuration Based or Business View Based), Applies to (CI type plus criteria), Preview CIs.

**New Contract**

| Field | Type | Required | Options | Notes |
|---|---|---|---|---|
| Template | select | No | General Contract Template | |
| Name | text | Yes | | |
| Contract Vendor | select | Yes | Apple, DELL, HP, Lenovo, or New Vendor | |
| Contract Term | select | Yes | Definite / Indefinite | |
| Parent Contract | picker | No | | |
| Contract Cost | number | No | | Currency is read-only |
| Contract Owner | user | Yes | Defaults to me | |
| Contract Type | select | No | Lease, Maintenance, Standard (Sample), Support, Warranty | |
| Active Period | date range | Yes | | Pick start, then end |
| Sites | select | No | | |
| Comments, Support Details | text | No | | |
| Associated Assets | picker | No | | Max 100 |
| Software Licenses | picker | No | | Max 100 |
| Attachments | file | No | | |

- **Expiry Notification:** a checkbox that reveals Users to be Notified*, Emails (max 10) and "Notify before" N days (up to 10 rows). "Create Request Before Expiry" is greyed out while it is ticked.
- **Auto-renewal:** a checkbox with Users to be Notified and a Prolongation number plus unit.
- **Buttons:** Save, Save Draft, Cancel.

**New Vendor:** Vendor Name*, Currency*, Description, First Name, Address (door, street, landmark, city, ZIP, state, country), Contact Info (email, phone, fax, web URL). Vendors can be switched on and off from the list.

**New Purchase Order**

| Field | Type | Required | Options | Notes |
|---|---|---|---|---|
| Template | select | No | Purchase Order Template | |
| PO # | auto | No | | Prefix PO |
| Name | text | Yes | | |
| Required By | date | No | | |
| Sites | select | No | | |
| Vendor Details | selector | Yes | | Shows address, phone, email, contact |
| Shipping Address | selector | Yes (not enforced) | | See Weak spots |
| Billing Address | selector | No | | |
| Currency | read-only | No | | |
| Item Level Cost Center, Item Level GL Code | checkbox | No | | |
| Item adder | selects | No | Category (Products / Services / Others), Product Type (Mouse Pad, Printer, Router, Server, Workstation), Product (+ to add) | |
| Requested by | user | Yes | | |
| Owner | user | No | | |
| Cost Center | select | No | PU01 Purchase Code, PU02 Pickup Code | |
| GL Code | select | No | GL-533298, GL-558776 | |
| Remarks, Terms, Attachments, Place, Signing Authority | text/file | No | | |

- **Item grid:** S.No, Items, Part No, Price (prefilled from the product), Tax Rate % (prefilled 5), Quantity, Amount.
- **Totals:** Sub Total, Discount (% and amount), Total (Net), Shipping Cost, Sales Tax, Additional Tax, Cost Adjustment, Total Cost.

**Invoice and Payment (on PO)**
- **Add Invoice:** Invoice ID*, Received Date, Payment Due Date, Comments, Attachments, Enable Payment Notification.
- **Add Payment:** Amount Paid*, Payment Date, Comments, Attachments, Enable Payment Notification.

**Receive items dialog:** per item a checkbox, a Site and a Quantity row. A "Receive with barcode / QR code" option also exists.

**New Consumable:** Product*, Track Consumables* (Without Batch/Lot, or With Batch/Lot; this choice cannot be changed later), Quantity (Units)*, Vendor, Location, Comments, Purchase Cost, Barcode/QR code, Site. The batch option adds Reference Name*, Batch/Lot Number, Manufactured Date and Expiry Date.

**New Loan:** Assets* (search by name or barcode), Loan Start* (default today), Loan Expiry*, Loaned to User* or Department*, Site, Asset Received By, Comments. **Return Assets:** Assets*, Return On*, Return By*, Comments, and a "Move to In Repair state" checkbox.

**New Asset Audit:** Audit Name*, Audit Type* (Technician-Conducted Audit, User Self Audit), Description, Planned Start Date, Planned End Date.

**New Group:** Group Name*, Description, Group Type* (Static: assets are added after saving; Dynamic: criteria rows of criteria, condition and value with add/remove).

**New Incident from an asset:** the form opens with the Assets field and the Requester already filled in.

**Asset Auto Assign (Setup):** Enable Auto Assign checkbox; "consecutive scans with the same last-login email" count (default 2); a fallback field to use when scans give no email; an "Exclude assets from Auto Assign" checkbox.

**New FGA for Asset (Setup):** Name*, Description, Technicians*, Product Type (selected types or all) and an Advanced Criteria checkbox. The FGA list is empty. The module switcher offers Asset and CMDB.

**New asset life cycle (Setup):** Name*, Description, Applies to (sub-module select), then Next.

## Actions and menus
- **Asset states:** Disposed, Expired, In Repair, In Use, In Store. Assigning a user flips In Store to In Use.
- **Asset actions:** listed above. Raise Request > Create Incident asks for a template (Default Request, Maintenance, MIM, New Joinee, etc.), then opens a New Incident form with the asset attached.
- **CMDB:** Copy CI, Modify CI Type, Modify State, Add Relationship, Relationship Map, Create Incident / Service Request / Change from a CI.
- **Contract Actions:** Delete, Cancel, Renew, Select Parent, Associate Child, Add Note, Email the Owner, Email the Vendor.
- **PO Actions (vary by status):** Duplicate, Submit for Approval, Approve, Reject, Add Note, Cancel, Order, Add Invoice, Add Payment, Email the Owner, Email the Vendor, Receive items, Receive with barcode / QR code.

## Configuration options
- **Setup > Asset Management:** product types, products, vendors and other tabs (documented in earlier contexts).
- **Setup > CMDB (5 tabs):**
  - CI Types: 53 in a tree.
  - CI States: 4 (Maintenance, Non-Operational, Operational [default], Decommissioned [EOL]).
  - Relationship Types: each has an inverse name, e.g. Virtualizes / Virtualized by, Contains / Member of, Managed by / Manages, Backed up by, Located In / Houses. A New Relationship Type button exists.
  - Sync Rules: empty.
  - Configurations: a checkbox excluding EOL CIs from system CI fields in all modules (on).
- **Setup > Contract Management:** Contract ID Prefix (CON), Starts From, Contract Expiry Request Template; and a Contract Type list with colours (Lease, Maintenance, Standard (Sample), Support, Warranty).
- **Setup > Purchase Management:** Default Values (default sales tax %, signing authority, tax-on-shipping toggle, default shipping and billing address, cost center, approvers, terms, remarks, PO # start, PO prefix, "PO Owner as Approver" ON, "Enable PO Approver Limit" ON), a Cost Center tab and a GL Code tab.
- **Discovery Settings:**
  - General: invalid service-tag list, MAC identification on or off, computer name format, overdue-scan handling (applies to product types; action Delete Asset or Move to State), scan history cleanup (1/3/6/9/12 months), create custom product types during SNMP discovery, create monitors as assets.
  - Other tabs: Exclude Devices, Unknown OID, Scan Script.
- **Network Scan form:** network (entire network or a range), probe, description, credentials for Windows, Linux/Mac/Solaris/AIX, SNMP and VMware, plus a software-scan option.
- **Probe columns:** name, host, site, last contact, key, .NET version. **Domain Scan columns:** domain name, controller, status, login, description. **SCCM Integration columns:** DB host, DB name, connection status, discovery status, probe. **Credential Library columns:** name, protocol, description.
- **Import wizard:** asset type, import mode (default "Add records and update if already exists"; I could not read the other options because the native select does not render), CSV, UTF-8, max 3000 records, sample file download.

## Automation / triggers / rules in this area
- **Asset Auto Assign:** disabled by default (see Fields).
- **Asset Life Cycles:** one "Sample Asset lifecycle", published but switched off, applying to nothing. New life cycles are created by name and sub-module. Detail and Workflow (Asset) setup are only noted from the Setup menu map, not opened.
- **Asset workflow and life cycle fields:** on the asset right panel both show "Not Assigned".
- **Contracts:** expiry notification emails, an auto-created request before expiry, and auto-renewal with a prolongation period.
- **Purchase orders:**
  - Approvals use stages, with a "PO Owner as Approver" default and a per-approver limit setting.
  - Receiving items automatically creates assets (see Behaviour).
  - Mail notification checkboxes in approve and order dialogs were disabled because no mail server is configured.
- **Loans:** loaning an asset sets it In Use and writes a state comment; closing the loan ends it.
- **Replenishment:** threshold alerts, not configured.

## Behaviour observed in tests
- **Software and licences** (earlier contexts):
  - An Individual licence with a manually added install shows "Under Licensed".
  - "Auto Allocate License" turns it Compliant.
- **CMDB:** I created two CIs and linked them with "Connected to". The history logged "Relationship Added". The map displayed the link and I saved a business view.
- **Impact analysis:** there is no dedicated impact-analysis page or button. The practical equivalent is the Relationship Map plus the CI's Associations counters (requests, problems, changes, releases, contracts) and its Downtimes tab.
- **Contract:** CON-7 saved as Active with 8 days to expire and was linked to my asset.
- **Purchase flow:**
  1. PO #5 was created (2 × Precision 3570 at 3000 plus 5% tax, total 6300) in status Open.
  2. "Approve this PO" worked immediately because the owner can approve their own PO. The Approvals tab showed a system-created stage 1 as Approved.
  3. "Submit for Approval" is blocked by the missing mail server.
  4. "Order this PO" moved it to Ordered.
  5. Receiving 1 of 2 items at Base Site gave Partially Received. The Delete button then disappeared.
  6. Receiving created an asset "Precision 3570 - PO# 5[1]": Workstation, In Store, vendor DELL, purchase cost 3000 (without tax), acquisition date today, with a Purchase Order link in the right panel.
- **Loan:** I marked that asset loanable, loaned it to myself (Oct 23 to Oct 30) and the asset became In Use with a "Loaned To" card. After I returned it the loan became Closed. I did not re-check the asset's state after the return.
- **Links to requests:** Raise Request > Create Incident on my asset created request #42 with the asset and requester prefilled. The asset's right panel then showed Associated Requests as 1 pending and 1 total. Request #42's Associations section has Linked Requests, Associated Problem, Changes, Projects, Releases and Invoked Contracts.
- **Links to CIs:** the CI Create Incident dialog earlier showed no templates. This was a one-off observation; it needs a template containing the CIs field.
- **Links to problems and changes:** I did not test the asset pickers on problems and changes in this area. The CI Actions menu offers Create Change, and a PO has "Associate Service Requests: Attach".
- **Not covered:** the Asset Actions dialogs Copy Asset, Modify Product and Reconcile (I only saw them in the menu), consumable creation (I viewed the form without saving), Purchase Order and Contract template editors (Setup links exist), and the Asset Workflow setup page.

## Edition notes
This is the Enterprise trial. Asset, CMDB (53 CI types, business views, baselines, sync rules, data quality), purchase, contract, loan, audit and discovery features were all present. Discovery is available but nothing is set up (no probes, credentials or scans).

## Weak spots / confusing UX
- The PO form marks Shipping Address as required but let me save without one.
- The History sub-tab on the asset detail was stale, while State History was accurate.
- The page layout compresses badly in a narrow window (vertical text on detail pages).
- The left Assets tree scrolls oddly and only responds to real clicks.
- The same-user approval shortcut lets a PO owner approve their own PO.
- Purchase cost on the auto-created asset excludes tax.
- There is no dedicated impact-analysis view.
- Several selects (for example the import mode) use native popups that are hard to read in automation.

## Test records created (all ZZ-CLAUDE-TEST unless noted)
- Asset "ZZ-CLAUDE-TEST asset 1" (Workstation, In Use, assigned to me).
- Software "ZZ-CLAUDE-TEST software 1" and licence "ZZ-CLAUDE-TEST license 1".
- CIs "ZZ-CLAUDE-TEST CI 1" and "ZZ-CLAUDE-TEST CI 2" (Connected to), and business view "ZZ-CLAUDE-TEST view 1".
- Contract CON-7 "ZZ-CLAUDE-TEST contract 1".
- PO #5 "ZZ-CLAUDE-TEST PO 1" (Partially Received).
- Asset "Precision 3570 - PO# 5[1]", auto-created from my PO and not prefixed ZZ-CLAUDE-TEST (marked loanable; Loan 1 closed).
- Request #42 "ZZ-CLAUDE-TEST incident from asset 1".
- No vendors, groups, audits or consumables were saved. Earlier-area records are unchanged and PB-6 is still in trash.

# Area 7, follow-up 7b (append to the end of the Area 7 report)

Everything below was viewed only, except where a test record is noted.

## 7b.1 Setup > Customization > Asset Management

**Navigation path:** Setup (gear) > Customization > Asset Management. Tabs: Product Type, Product, Service Type, Service, Vendor, Software Type, Software Category, Software License Types, Software Manufacturers, Asset State, Asset Acknowledgement, Configurations. The tab strip shifts and overflows into a "..." menu.

**Product Type.** A tree of 39 types under "All Assets". Columns: Name, Type, Category, Description, Workflow/Life Cycle. Buttons: New Product Type, Expand/Collapse Tree.
- Asset-class types: Access Point, Computer, Keyboard (Component, Non-IT), Mobile, Printer, Projector (Non-IT), Router, Scanner (Non-IT), Switch.
- Consumable types (IT, workflow "Not applicable"): Blank Plastic Cards, Cable Tie, Cleaning Sheets, Cooling Pad, Fax Paper Roll, HDMI Cable, Inkjet Cartridge, Laptop Bag, Laptop Stickers, Motherboard Battery, Mouse Pad, Network Cable, Printer Ribbon for Plastic Cards, Ribbon, Sleeve, Stand, Toner Cartridge, USB Extension Cable, VGA Cable.
- Software type (IT, bound to the "Commercial Software License" workflow).

New Product Type form (two tabs: Details, and Fields, which is disabled until the first save):

| Field | Type | Required | Options | Notes |
|---|---|---|---|---|
| Product Type | text | yes | | |
| Icon | icon picker | no | Select Icon | |
| API Name | text | yes | | Fixed prefix `custom_asset_` |
| Parent Product Type | tree select | yes | existing types | |
| Category | select | yes | IT, Non-IT | |
| Type | select | yes | Asset, Component, Consumable | |
| Description | text area | no | | |

**Product.** Columns: Product Name, Type, Product Type, Manufacturer. Buttons: New Product, Configure Depreciation, Delete; a gear per row; paged.

| Field (New Product) | Type | Required | Notes |
|---|---|---|---|
| Product Type | select | yes | |
| Product Name | text | yes | |
| Manufacturer | text/select | no | |
| Part No. | text | no | |
| Cost | money (default 0.00 $) | no | Has an info icon |
| GL Code | select | no | |
| Product Visibility | checkbox | no | "Do not show in purchase order" |
| Description | rich text | no | |

The list includes ZZ-CLAUDE-TEST software 1 (Software / Others), plus network gear and phones such as the Cisco, TP-Link, HP, Aruba, NETGEAR, One Plus and iPhone entries.

**Service Type.** Five types: Others, Training/Consultancy, Labour, Infrastructure, Annual Maintenance Service. Columns: Name, Description. Button: Add Service Type.

**Service.** One service, "Training Service" (type Training/Consultancy). Columns: Name, Description, Part No, Service Type, GL Code.
- Add Service form: Name*, Service Type*, Part No, GL Code, Description, Disable (checkbox).

**Vendor.** Covered in the Area 7 report. Existing vendors: Lenovo, Apple, HP, DELL.

**Software Type.** Six: Excluded (not managed), Freeware, Managed, Prohibited, Shareware, Unidentified. Button: New Software Type. Each row has edit and delete icons.

**Software Category.** Nine: Accounting, Database, Development, Game, Graphics, Internet, Multimedia, Operating System, Others. Button: New Software Category.

**Software License Types.** The list is filtered by manufacturer (Adobe Systems, Inc. by default).

| License type | Track by | Installations allowed | Perpetual |
|---|---|---|---|
| Individual | Computer | Single | no |
| Volume | Computer | Volume | no |
| Enterprise (Perpetual) | Computer | Unlimited | yes |
| Enterprise Subscription | Computer | Unlimited | no |
| OEM | Computer | OEM | no |
| Client Access License | CAL | | |
| Concurrent License | User | Single | |
| Node Locked | Computer | Single | |
| Named User License | User | Single | |
| Trial License | Computer | Volume | |

New License Type dialog:
- License Type*
- Manufacturer* (select, with an add button)
- Track By* (Computer, User)
- Installations Allowed* (Multiple, OEM, Single, Unlimited)
- Is Perpetual (checkbox)
- Is Free License (checkbox)
- License Option* (an add/remove list of options)

**Software Manufacturers.** Four: Others, Symantec Corporation, Adobe Systems, Inc., Microsoft Corporation. Columns: Display Name, Name, Description. Buttons: New Manufacturer, Reconcile, Delete.

**Asset State.** Five: Disposed, Expired, In Repair, In Use, In Store. Columns: Asset State, Description. Button: New Asset State.

**Asset Acknowledgement.** One checkbox, "Enable Asset Acknowledgement" (currently off). The help text says acknowledgements are set for specific product types, assigned users confirm receipt, and asset notifications must also be enabled.

**Configurations.**
- "Calculate Asset Age based on" (select; currently Acquisition Date).
- An Asset Age Format table with Years, Months and Days checkboxes, each with a display-word select, and a live preview ("1 years 10 months 16 days").

**Related Setup pages viewed:**
- **Asset Auto Assign:** an enable switch, the number of consecutive scans with the same last-login email before auto-assigning (default 2), a fallback field to use when no email is collected, and an exclusion list.
- **Fine-Grained Access** (Asset/CMDB switcher): currently empty. The New form has Name*, Description, Technicians*, Product Type (specific or all) and an Advanced Criteria checkbox.
- **Asset Life Cycles:** one entry, "Sample Asset lifecycle" (published, status off, applies to nothing). The New form has Name*, Description, Applies to (sub-module), then Next.

## 7b.2 Software "ZZ-CLAUDE-TEST software 1" and its licence

**Software list** (`/ui/software`, under Assets). Views: Zero Installation Software, All Software, Software Suite. Columns: Name, Type, Is Software Suite, Category, Manufacturer. Toolbar: New (New Software, New Software Suite), Delete, Actions (Modify Category, Modify Manufacturer), Move To (site). Sub-lists: Software, Agreements, Licenses, Service Packs.

**Header.** A Site selector (All Sites) and a "Compliance Type" dropdown. It currently shows Compliant, with a popover reading Installations Allowed 1, Installations 1, Licensed Installations 1.

**Tabs:** Details, License Agreements, Installations, then an overflow (Licenses, Usages, History). The strip reorders itself around the last tab opened.

**Details tab.**
- Fields: Product, Cost, Version, Manufacturer (Others), Category (Development), Description (editable), Software images (Add), Software Type (Managed).
- Right panel, Installations Summary: Licensed 1, Unlicensed 0, All 1.
- Right panel, Licenses Summary: Purchased 1, Installations Allowed 1, Downgrade 0, Allocated 1, Allocated to Downgrades 0, Available 0.
- Actions menu: Modify Software Type, Convert as Software Suite, New License Agreement, New Software License (Standard or Upgrade), Notification > Email users. I did not click Email users.

**License Agreements tab.** Filter "All Agreements". Columns: Agreement Number, Manufacturer, Acquisition Date, Expiry Date, Expire In, PO #, Status. Empty.

**Installations tab.** Sub-tabs: All, Licensed Installations, Unlicensed Installations. Buttons: Add Software Installations, Remove Software Installations. Columns: Computer, Version, User, License. One row: ZZ-CLAUDE-TEST asset 1, user the trial admin.

**Licenses tab.**
- Buttons: Auto Allocate License; under Purchased Licenses (sub-tabs All, Individual): New Standard License, New Upgrade License, Delete, Move License to Site.
- Columns: License Name, License Type, License Option, Installations Allowed, Allocated, License Key, Site, Region, Status, Organization License.
- The one row: ZZ-CLAUDE-TEST license 1, Individual, Full Packaged Product (FPP), allowed 1, allocated 1, Base Site, Active, Organization License = No.
- Below it, "Available for allocation / Downgrade Licenses" shows 0 and 0.

**Usages tab.** Sub-tabs: All, Users, Departments. Columns: User, Department, Computer, Email Id, Phone. One row: me, on ZZ-CLAUDE-TEST asset 1.

**History tab.** Filters: All, Installed, Updated, Uninstalled ("this week" by default). Columns: Discovered Date, Computer, User, Department, Operation. Entries: Installed (08:23 PM), License Allocated (08:24 PM).

**New Standard License form** (opened, not saved):

| Field | Type | Required | Options / default |
|---|---|---|---|
| Manufacturer | select + add | yes | default Others |
| License Name | text | no | |
| License Type | select | yes | default Individual (list above) |
| License Option | select + add | yes | Full Packaged Product (FPP), Others |
| Vendor | select + add | no | |
| License Key(s) | text | no | |
| Organization License | Yes/No | no | default No |
| Allocated To Site | select | no | Base Site |
| Renewal Type | select | no | Monthly, Quarterly, Biannual, Annual, Custom |
| Acquisition Date | date | no | |
| Expiry Date | date | no | |
| Purchase Cost | money | no | default 0.0 |
| Purchased For | text | no | |
| Description | text | no | |

There is also a "Downgrade Rights" section: a table of Software and License Key rows naming installations this licence may be used for.

**Compliance.** There is no standalone compliance screen. Compliance shows as the header dropdown (Compliant, Under Licensed and so on) plus the Installations and Licenses summaries. The Under Licensed to Compliant flip on Auto Allocate License is in the Area 7 report.

## 7b.3 Asset detail page of "ZZ-CLAUDE-TEST asset 1"

Tabs: Details, Hardware, Software, Relationships, Financials, Contracts, History, plus overflow.

**Details tab.**
- Name, Product (Precision 5560).
- Computer: Model, Manufacturer, Last Logged In User, Domain, Service Tag, BIOS Version, BIOS Date, BIOS Manufacturer, SMBIOS Version.
- Operating System: OS, Version, Build Number, Service Pack, Product ID.
- Memory: Physical, Virtual.
- Keyboard: Type, Manufacturer, Serial.
- Mouse: Type, Serial, Buttons, Manufacturer.
- Asset Details: Serial Number (ZZ-SN-0001), Asset Tag (ZZ-TAG-0001), Product Manufacturer, Barcode/QR, Vendor, Discovered Serial, Purchase Cost (1200.00 $), Part No., Expiry Date, Acquisition Date, Location, Warranty Expiry Date, Last Updated By/Time, Region, Created By/Time.
- Asset State block: State (In Use), User, Associated to Asset, Department, Site (Base Site), "Retain associated asset/user/department's site" (Yes), State Comments.

**Hardware tab.** Every section is empty for this manual asset.
- **Computer Details:** Computer System; Operating System (this adds Language and License Type); Memory.
- **Processor table:** S.No, Processor, CPU Stepping, Manufacturer, Number of cores, Clock Speed (MHz), with a Total Processors count.
- **Installed Memory Modules:** Socket, Capacity, Module Tag, Bank Label.
- **Network Details > Network Adapters:** IP Address, MAC Address, NIC Name, DHCP, DHCP Server, DNS Hostname, Type.
- **Disks and Drives:**
  - Hard Disks: Model, Serial Number, Manufacturer, Capacity.
  - Logical Drives: Drive, Drive Type, File Type, Serial Number, Capacity, Free Space, Drive Usage.
  - Physical Drives: Drive Name, Drive Type, Manufacturer, Driver Version, Driver Provider.
- **Printer Details > Printers:** Name, Server, Model, Type, Default, Location.
- **Other Details:** Keyboard, Mouse, Sound Card, Monitors (Monitor Type, Serial Number, Manufacturer, Max Resolution), Video Cards (Chipset, Video Card Memory, Video Card), Ports (Port Name, Port Status), USB Controllers (Name).

**Software tab.**
- Type filter: All Software Types, Excluded, Freeware, Managed, Prohibited, Shareware, UnIdentified, Suite Software.
- Buttons: Add Software Installations, Delete.
- Columns: Software, Version, License Key, Product ID, Type, Category, Installed On, Added By.
- One row: ZZ-CLAUDE-TEST software 1, Managed, Development, added by me.

**Relationships tab.** A diagram with the asset in the centre, an "Assigned To" user node, and connected groups (Assets, Business Services, Components and so on), each with a "+". An Add Relationship dropdown sits above it.

**Financials tab.**
- **Costs sub-tab:** summary cards for Purchase Cost 1200.00 $, Current Book Value 0.00 $, Operational Cost 0.00 $, Total Cost of Ownership 1200.00 $. Below is a cost table (Date, Cost Factor, Description, Cost, with edit and delete icons) and Total and TCO lines. The first row is the purchase cost dated Oct 23, 2026.
  - **Add Cost dialog:** Cost Factor* (grouped: Purchase Cost; Operational Cost with Move/Change Cost, Others, Service Cost, Contract Cost; Disposal Cost), Amount*, Date*, Description.
- **Depreciation sub-tab:** shows Purchase Cost 1200.00 and Acquisition Date "-", with a prompt to configure depreciation.
  - **Configure Depreciation dialog (not saved):** Purchase Cost*, Acquisition Date*, a radio between "use data configured for product Precision 5560" and "for this asset", and Depreciation Method* (Declining Balance, Double Declining Balance, Straight Line, Sum Of The Years Digit).

**History tab.** Sub-tabs: History, State History, Assignment History, with a text filter, date picker and an "All" filter. Newest first:
1. 08:24 PM, Software License Allocated.
2. 08:23 PM, Updated "Installed Software [ZZ-CLAUDE-TEST software 1]".
3. 08:18 PM, Updated "State from In Store to In Use; User from None to the trial admin".
4. 08:16 PM, Created.

The creation of request #42 from this asset did not appear in the history.

## 7b.4 "Precision 3570 - PO# 5[1]" after loan return

State is In Store. It links to Purchase Order 5 (ZZ-CLAUDE-TEST PO 1). Age is 0 years 0 months 0 days. Life cycle and Workflow are both "Not Assigned".

## 7b.5 Linking assets to a problem and a change

- **PB-5:** Edit > Assets Involved > "More Assets" opens a "Select Assets Involved" picker. After Save, the problem shows "Assets Involved: ZZ-CLAUDE-TEST asset 1". The picker has:
  - a Product Type filter (All Assets) and a Site filter (All Sites);
  - a search icon that opens per-column filters (type in the Name filter, press Enter);
  - columns Name, Product Type, Product, AssetTag, Barcode/QR code, Serial Number, Discovered Serial Number;
  - paging (22 assets) and Select/Cancel.
- **CH-8:** the same picker and the same result on the Details page. CH-8 also showed a workflow popup, "General Change Workflow, Execution Status Violated, Change is not following workflow now". I closed it.
- **Asset side:** the right panel now has "Associated Requests" (1 pending, 1 total) and "Associated Problems" (1 pending, 1 total). **No Changes counter appeared**, so the change link is not visible from the asset's right panel. This looks like a gap or inconsistency.

## 7b.6 Dialogs on ZZ-CLAUDE-TEST asset 1

- **Copy Asset:** a single field, "Number of Copies*", with Copy/Cancel. I made one copy, "Copy of ZZ-CLAUDE-TEST asset 1 - 22" (Workstation, In Store, same product and serial). It remains in the instance.
- **Modify Product:** Product Type (Workstation, clearable) and Product* (Precision 5560), with Save/Cancel. Cancelled.
- **Modify State** (opened by mistake on the list, cancelled): State* (default In Store), Site (Base Site), State Comments.
- **Reconcile** (list Actions menu):
  - With one asset selected it alerts "Please select two assets to reconcile".
  - With two selected, a "Reconcile Confirm" dialog says it merges duplicates, keeps one and deletes the other. A discovered asset wins over a PO-created one; otherwise the latest wins. I clicked No, so nothing merged.

The workstation list Actions menu is longer than the All Assets one: Scan Now (not clicked) comes first, then Add to Group, Configure Depreciation, Assign to Department, Assign to Site, Modify State, Modify Product, Reconcile, Mark as Loanable and more.

**New test record in 7b:** "Copy of ZZ-CLAUDE-TEST asset 1 - 22".

=== END OF AREA 7 (including 7b) ===
