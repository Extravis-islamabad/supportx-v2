### 2026-11-05 — Mobile app: the prototype's screens (WP-M3, WP-M4, WP-M5; D-155)

- **One role-based app.** After sign-in, technicians land on `/t/*` and requesters on `/r/*`.
  Each side has its own bottom bar, drawn in-app so that it follows the right-to-left switch.
  One live connection runs per session (`@supportx/realtime`, now React Native safe).
- **Technician:**
  - Home: the KPIs `my_open`, `my_overdue`, `my_due_today` and `unassigned` from
    `/incidents/views`, each opening its queue; a MonetX or monitoring alert card in my groups;
    and "needs your attention" (SLA overdue or warning).
  - Queue: filters Mine, My group, Unassigned and Overdue (server views) with counts, the SLA
    "due in / overdue by" on every row, and pull to refresh.
  - Incident: priority, status, requester, assignee and SLA. Take, Start work and Resolve come in
    a fixed order. A disabled action says why (`action_reason.*`), and Resolve asks for a
    resolution.
  - Conversation: public reply vs private note, visibly different. Live through the record
    channel.
  - Approvals: approve, or reject with a required reason (If-Match on the approval's version).
  - Alerts: notifications open their record and are marked read.
  - Me: Available / Away, organisation switch, language, server status, sign-out.
- **Requester:**
  - Home: announcements, Report a problem / Request something, and what is open.
  - Report a problem: knowledge suggestions while typing, urgency, and one idempotency key per
    form.
  - Catalog: items with "manager approves first" or "no approval", and their questions (text,
    long text, choice, number, date).
  - My requests: incidents and service requests together, with a status timeline and
    fulfilment steps.
  - "Yes, it's fixed" / "Still broken": the words are required, and the request reopens. A
    message can be added to the team.
- **Shared code:**
  - `@supportx/realtime`: the server origin comes from `currentApiOrigin()`, and the `document`
    and `pagehide` code is skipped when absent. Peer widened. 17 tests pass.
  - 88 `mobile.*` labels (en/ar/ur); everything else reuses the web's labels (priority, status,
    views, SLA, actions).
  - New mobile dependencies: `@supportx/realtime` (link), `centrifuge` 5.8.0 (D-030) and
    `@expo/vector-icons` (D-154).
- **Not in this round:**
  - Photo attachments (needs `expo-camera` or an image picker; `expo-camera` is approved for
    later).
  - The knowledge article page (suggestions show title and snippet only).
  - Push notifications (WP-M6).
  - An offline queue for replies.
- **Android toolchain (this PC):**
  - Temurin JDK 17 on C:. Command-line SDK on `D:\Android\Sdk`: platform 37, build-tools
    37.0.0, NDK 27.1, emulator, one Android 36 Google APIs image; 8 GB.
  - The virtual phone `SupportX_Phone` (2 GB RAM) in `D:\Android\avd`. The Gradle cache in
    `D:\Android\gradle`. No Android Studio.
- **Tests:** mobile 23 (4 suites), all passing. ESLint, Prettier and tsc clean.
