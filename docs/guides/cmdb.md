# CMDB: configuration items

The CMDB holds the configuration items (CIs) your services depend on: servers, applications,
network devices and anything else you choose to track.

## Types and attributes

Every CI has a type. Types form a tree: a *Server* is a kind of *Hardware*. An administrator with
the **Configure CMDB** right adds types and attributes under **Admin → CMDB**. An attribute set on
a type is held by its CIs and by the CIs of every type below it. Attribute kinds are text, long
text, number, date, yes or no, and choice. CI attributes cannot be marked sensitive yet.

A type cannot be removed while CIs or other types use it; the message says how many.

## States

Each state is either *active* or *end of life*. Pickers leave end-of-life CIs out, unless an
administrator turns that off.

## Working with CIs

- **New CI**, **Edit**, **Copy** and **Move to trash** are on the CMDB pages; the trash can
  restore a CI as it was.
- **Change type** shows first which attribute values the new type does not hold and will drop.
- **Add from assets** makes one CI per asset you can see, named after it; an asset that already
  has a CI is skipped.
- Every save is kept: the history lists who changed what, and a snapshot of the CI is stored.

## Who sees what

**View CIs** is granted for all CIs, the CIs at a person's own sites, those owned or managed by
their own groups, or the CIs they own. **Add**, **Edit** and **Remove CIs** are separate rights;
the older **Manage CMDB** right still covers all three.
