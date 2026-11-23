# Workflows: a guide for admins and the people who run them

A **workflow** is a set of steps that runs on one record (an incident, a service request, a
problem, a change or a release):
- **logic:** if and switch;
- **waiting:** wait for a change, and timers;
- **people:** approvals, tasks, notifications;
- **actions:** updating fields, notes, webhooks, custom functions;
- **structure:** parallel branches and sub-flows.

Admins build workflows in the designer; the steps run by themselves, and every run can be seen
on its record. The design is in ADR-043. The requirements are REQ-WF-008 to REQ-WF-029 in file
03 of the parity specs.

Who may do what:
- **workflows.manage:** build, test, publish and switch workflows on or off; see every run;
  retry, cancel and move runs in bulk.
- **workflows.run:** see a record's workflows and act on one run (retry, skip, run again,
  stop). Acting on a run also needs the right to edit its record.
- **Requesters:** never see workflows; the portal shows only the record's status.

## The workflows list (Admin › Workflows)

- Choose a **record type** to see its workflows. Each shows:
  - its state: *Draft* (never published), *On* or *Off*;
  - its published version;
  - how many runs are live.
- **Add workflow** asks for a name and a record type, then opens the designer.
- A row's **…** menu:
  - **Copy:** an independent draft under a new name.
  - **Export:** a file for importing elsewhere in the same organisation.
  - **Delete:** only when no runs are live; switch the workflow off instead.
- **Import** reads a file exported here. Files from another organisation are refused, because
  their people, groups and templates mean nothing here.

## The designer

The page has a header, then three panes: the palette, the canvas, and the details.
- **Header:** the workflow's name, its state, its version, *Unsaved changes* and its problems,
  with **Save**, **Publish** and **More**. More switches the workflow on or off.
- **Palette:** steps grouped by kind. A step the record type cannot use now is greyed out and
  says why, for example a custom function when no runner is set up.

Building:
- **Adding a step:** drag it from the palette onto the canvas. Or press its button: the step is
  placed below the selected one, so no mouse is needed.
- **Linking:** each output has its own labelled handle (*Next*, *Yes*, *Approved*, *Timed out*
  …). Drag from an output to the next step's input. One output leads to one step; a new link
  replaces the old.
- **Deleting a link:** select it, then press **Delete link** in the details, or the Delete key.
- **The outline** (side tab) lists every step and where each output goes. Choosing a target
  links the output; *Not linked* removes the link. The whole diagram can be built and read by
  keyboard or screen reader there.
- **Undo and redo** keep the last 100 edits: Ctrl/⌘+Z, Shift+Ctrl/⌘+Z or Ctrl+Y.
- **Tidy layout** arranges the steps top to bottom. In Arabic and Urdu the canvas reads right to
  left.

Settings and saving:
- **Settings:** the step's own form, for if, switch, notify, timer, wait and set status. *Advanced*
  shows the settings as stored, for every step. Changes apply with **Apply**, as one undo step.
- **Problems:**
  - Saving keeps the draft whatever its problems.
  - The problems come back marked on their steps and listed in the *Problems* tab; choosing one
    selects its step.
  - **Publish** is possible only without problems and with nothing unsaved.
- **Someone else saves:** you see their version at once. If you have unsaved changes, a notice
  offers to reload instead.

## Test mode (the Test tab)

A test runs the **saved draft** without changing anything: nothing is sent and nothing is
written to the record.
- **What it runs on:** a record (type its ID, e.g. INC-12) or sample values (field names and
  values).
- **Answering:** each step the workflow asks for waits for you:
  - *Approved* or *Rejected* for an approval;
  - *Done* or *Failed* for the rest.
- **Changes and timers:** *Something happened on the record* wakes a waiting step. *Move the
  clock on* fires timers.
- **What you see:** the path taken and where the test is now are marked on the canvas;
  variables and the steps are listed.
- **One live call:** a webhook or notification step, on a real record, can be made for real
  **once** per test. A confirm says so first, and the call is recorded in the audit trail with
  your name. A custom function is never run from a test.

## A record's Workflows tab

On an incident, service request, problem, change or release, the **Workflows** tab shows each
run of a workflow on that record:
- **The diagram:** the path taken and the current step, read-only.
- **The log:** each step with its result, its time to the second and how long it took.
- **Failures:** a failed run names the step and why it stopped, in words. Then:
  - **Retry the step:** run it again.
  - **Skip this step:** go on to the step after it, as if it had worked. This is possible only
    where the step has a single *Next*. A step that decides its own path, such as an approval or
    an if, is never skipped. Recorded with your name.
  - **Run again** from the start, or **Stop** with a reason.
- **Updates:** the tab updates live; approving a step moves the marker at once.

## Runs (Admin › Workflows › Runs)

Every run of every workflow, newest first:
- **Filters:**
  - by state and by workflow;
  - in **Filters**, by step and by *not moved for more than (hours)*, which shows runs stuck
    waiting.
- **Records:** a run's record is named and linked only if you may see that record; otherwise it
  shows *A record you can't see*.
- **Bulk actions:** select runs, then **Retry** (failed runs only) or **Cancel runs** (asks why;
  the reason goes in the audit trail).
- **Jobs:** each becomes a background job per workflow, at most 1,000 runs, whose progress
  shows live.

## Versions (the designer's Versions tab)

- **Publishing** makes a new version. Runs already going stay on the version they started on.
- **The tab** lists every version with who published it, when, and its live runs.
- **Move runs to version N** (on an older version with live runs):
  1. **Map the steps.** For each step that has runs on it, choose where those runs go in the new
     version: the same step by default, or *Stays on its version*.
  2. **Check what would move.** This dry run moves nothing. It says how many runs would move and
     why any would stay, for example a step with no place in the new version.
  3. **Move runs.** Possible only after a check with the same mapping. The move runs as a job
     with live progress, and each moved record's history notes the new version.

## Stage triggers and notifications

Two different things happen when a change or a release enters a new stage:
- **A trigger** (Admin › Automation › Triggers) can react with *When it enters a stage*, with the
  stage in its conditions (for example *stage is Deployment*). It runs its actions, such as a
  webhook or starting a workflow, **once per entry**. A move within the same stage runs nothing,
  and the record's history names the trigger.
- **A notification rule** (Admin › Notifications) tells people, by status: for changes,
  *A change enters a status*.

One move fires each at most once, so nobody gets the same automation twice or the same mail twice.

