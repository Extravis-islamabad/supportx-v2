# CMDB: configuration items

The CMDB holds the configuration items (CIs) your services depend on: servers, applications,
network devices and anything else you choose to track.

## Types

Every CI has a type. Types form a tree: a *Server* is a kind of *Hardware*. An administrator with
the **Configure CMDB** right adds types under **Admin → CMDB**. Your own fields on CIs (custom
fields per type, inherited by the types below) come in a later release through the same custom
fields as the rest of SupportX.

A type cannot be removed while CIs or other types use it; the message says how many.

## States

Each state is either *active* or *end of life*. Pickers leave end-of-life CIs out, unless an
administrator turns that off.

## Working with CIs

- **New CI**, **Edit**, **Copy** and **Move to trash** are on the CMDB pages; the trash can
  restore a CI as it was.
- **Change type** moves a CI to another type.
- Someone else saving a CI while you edit it never throws your edit away: you choose to keep
  your changes or load theirs.
- **Add from assets** makes one CI per asset you can see, named after it; an asset that already
  has a CI is skipped.
- Every save is kept: the history lists who changed what, and a snapshot of the CI is stored.

## Who sees what

**View CIs** is granted for all CIs, the CIs at a person's own sites, those owned or managed by
their own groups, or the CIs they own. **Add**, **Edit** and **Remove CIs** are separate rights;
the older **Manage CMDB** right still covers all three.
