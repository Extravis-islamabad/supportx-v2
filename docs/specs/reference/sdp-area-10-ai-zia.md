# Area 10: AI / Zia

Tested on the trial (Enterprise, expires Nov 22, 2026). Every AI setting I changed is back to its original value; see "Restoration confirmation" at the end.

## Navigation path

- **Setup > Zia > Artificial Intelligence** has three tabs: Predictive Features, GenAI Features and Cluster Analysis.
- **Setup > Zia > Agents** holds Custom Agents.
- **Setup > Zia > Chatbot** has the tabs Ask Zia, Blended Conversations, Zia Actions and Chatbot Customization. Zia Actions only appears while Ask Zia is on.
- **Ask Zia** is also a left-rail entry that opens `/app/itdesk/askZia.do`.
- The AI buttons themselves sit inside the editors:
  - the reply editor on a request
  - the Add Note dialog
  - the New Solution form
  - the workflow editor (not opened this time)
- The Setup search box finds the Ask Zia page. Typing `forwardTo=ask_zia` directly gives an "Incorrect input format" error.

## Screens and what they do

1. **Predictive Features** is one page with a module dropdown. Each feature is a switch plus a status line.
   - Request: Collaborator Suggestion, Template Prediction, Category Prediction, Sub Category Prediction, Item Prediction, Priority Prediction, Group Prediction, Technician Prediction, Sentiment Analysis.
   - Problem: Technician Prediction.
   - Change: Risk Prediction.
   - Release: Release Engineer Prediction and Risk Prediction.
   - Solution: Solution Assist, which builds a curated summary from KB articles.
2. **GenAI Features** has 11 cards. Each card has a switch, a provider list ("Available via" icons), and after enabling a "Powered by" label, a kebab menu, and sometimes a Configure link. Enabling opens an "AI Provider" dialog where one provider is chosen per feature.
3. **Cluster Analysis** (Incident only) has an "Enable AI Based Insights" switch and a "Problem Suggestion" card. The card finds groups of similar incidents and suggests raising a problem. A "New Analysis" form lets an admin define their own analysis.
4. **Agents > Custom Agents** is an intro page whose "Create Agents" button opens the separate Agent Studio. I did not click it, and no agents exist.
5. **Chatbot > Ask Zia** switches the chat assistant on or off. Once on, it shows "Powered by Zia" and a kebab menu "Configure AI provider" (it opened no panel).
6. **Chatbot > Zia Actions** lists five prebuilt actions of type Blended Conversations, available to all technicians. They are Answer FAQs, Check ticket status, Need help?, Show my ticket summary and Update task status.
7. **Chatbot > Blended Conversations** is "Disabled" (web only). It is a builder for scripted conversations.
8. **Chatbot > Chatbot Customization** is described under Fields.
9. **Ask Zia chat page** has quick chips (Create an incident, Create Service Request, Search solutions, My Overdue Requests, Update Request Status, More Actions). It also has a "+" menu for attaching files (computer or cloud), a mic, and mode chips for Ask Zia and Help Center. Answers get thumbs up, thumbs down and regenerate icons. A footer warns that it can make mistakes.
10. **Privacy Settings** (Setup > Users & Permissions) is a GDPR-style personal-data page with a single "Enable privacy settings" button. It has no AI-specific options. I did not click it.

## Fields

**GenAI feature inventory.** All 11 were off originally.

| Feature | Providers offered | Where it appears once on | Notes |
|---|---|---|---|
| Asset Acknowledgement | Zia, Azure, ChatGPT, Claude, Google | Not observed (needs mail) | Reads users' email replies to update an asset's acknowledgement status. |
| Checklist Generator | all 5 | Not enabled or tested | Generates checklists for requests. |
| Code Generator | Azure, ChatGPT, Claude, Google (no Zia) | Not tested | Writes custom function code. Needs a third-party provider. |
| Conversation Summary | all 5 | Not found on request #42 | See below. |
| Custom Script Generator | Zia and Claude only | Not tested | Writes form-validation and field-action scripts. |
| Reply Assist | all 5 | Zia icon in the request reply editor | Tested. |
| Request Auto Approval | all 5, with a "View Predictions" link | Not tested | Auto-approves based on the approver's earlier responses. |
| Resolution Assist | Azure, ChatGPT, Claude, Google (no Zia) | No icon in the resolution editor | Blocked without a third-party provider. |
| Solution Generator | all 5 | "Solution Generator" button on the New Solution form | Tested. |
| Text Assist | all 5 | Zia icon in the Add Note dialog | Tested. |
| Workflow Assist | all 5 | Workflow editor | Switch tested; the editor itself was not opened. |

- **Provider dialog:** one radio per provider. Zia-zlabs-qwen35-35B-v1 is a Zoho-hosted model, described as keeping data private. Azure OpenAI, ChatGPT, Claude and Google AI Studio each show a red "Disabled" badge. The tooltip says to enable them under Third-party Integration, and I did not. The dialog notes that choosing a provider means accepting its terms. Confirm enables the feature, and a toast says "<Feature> enabled".
- **Conversation Summary, Configure dialog:** it picks which fields feed the summary. Email responses from users is checked and locked. Notes, Subject, Description and Resolution are optional and were unchecked. A 90,000-character input limit is stated.
- **Reply Assist and Text Assist dialogs:**
  - Input is a free-text box labelled "Type to Assist".
  - A Generate split-button offers "Generate Reply" (or "Generate Text") and "Refine Text" (grammar and spelling).
  - Output has Change Length (Elaborate, Shorten), Change Tone (Professional, Casual, Informational, Enthusiastic, Friendly), and Language (searchable list including German, Hindi and Portuguese).
  - Buttons are Copy Reply / Copy Text and Cancel.
- **Solution Generator dialog:**
  - Input is a free-text Prompt.
  - The Generate split-button can produce Title, Content or Keywords separately.
  - Output has Change Length, Change Type and Language.
  - The Add Generated Solution button fills the New Solution form.
- **New Cluster Analysis form (Incident):** Name (required), Description, Conditions (matching rules or none), Fields to Analyze (required), Actions (configure an action rule), Save and Cancel.
- **Chatbot Customization:** Bot Type (Conversational with GenAI, or Classic; currently Conversational), Bot Name (Ask Zia), Bot Theme (4), Bot Avatar (5 plus add), Welcome Message ("How may I help you today?"), and Bot Settings. Bot Settings has three checkboxes: make the chatbot available to requesters, enable voice input, and search solutions from external sources. There is also an Available Bots entry (Help Center), Reset, Save and Cancel, and a live preview of the welcome and chat screens.

## Actions and menus

- Each enabled GenAI card has a kebab menu, and some have Configure. Switching a feature off asks for confirmation only for Conversation Summary ("hides existing summaries and stops new ones"). The others switched off immediately.
- Ask Zia answers come with action buttons on request lists (Pick Up, Close, Assign, Delete). I never clicked these.
- Ask Zia offers shortcuts to create an incident or service request, search solutions, show overdue requests and update a request status.

## Configuration options

- A per-feature provider choice for GenAI features.
- A per-feature on/off switch for predictive features and GenAI features.
- A master switch for Ask Zia.
- A master switch for Cluster Analysis insights, plus a per-analysis switch.
- Chatbot look, bot type and requester availability (see Fields).
- Which request fields feed Conversation Summary.
- No setting found for data retention or prompt logging. The only data and privacy statements are the dialog line that Zia keeps data private, and the provider terms notice.

## Automation / triggers / rules in this area

- Cluster Analysis has an "Actions" step where an action rule can be attached to a finding.
- Request Auto Approval is itself an automation: it approves on the approver's behalf using learned behaviour.
- Predictive features, once trained, fill fields on a request automatically. These were not testable because none can be switched on yet.
- Workflow Assist adds AI help inside the workflow editor. I only confirmed the switch.
- Zia Actions are scripted conversations run by the chatbot, not rules with triggers.

## Behaviour observed in tests

Ask Zia, with it switched on:

| Question | Result | Accuracy |
|---|---|---|
| "How many open requests are there?" | It asked whether I meant system-wide or only mine. After "system-wide" it showed "All Open Requests", 24, with 10 pages. | The dashboard's "Requests by Technician" table shows 25 open (plus 3 on hold). The 24 vs 25 difference is unexplained. |
| "show SLA violated requests this week" | A list titled "SLA Violated This Week" (#33, #32, #28, #27 and more). | It matches the SLA-violated data I saw earlier (10 this week). The total count in its header rendered blank. |
| "How do I fix a printer spooler problem?" | A step answer grounded on my ZZ-CLAUDE-TEST solution SOL-6, with a source citation and an escalation note. | Correct. It did not use SOL-7 (unapproved), so approval status is respected. |
| "Show me the requests by priority as a chart" | A bar chart "Requests By Priority" (Not Assigned 13, High 8, Low 8, Medium about 5 or 6, Normal 4, Critical 2). | It matches the dashboard widget; the Medium bar may be misread by one. |

On request #42 (ZZ-CLAUDE-TEST incident from asset 1), all with the Zia provider:
- **Reply Assist:**
  - Prompt: "tell the user we are looking into their printer issue and will update them tomorrow".
  - It produced a polite, longer reply that kept my facts. It added only mild filler ("our team is working diligently to identify the root cause").
  - Time to result was a few seconds.
  - I used Cancel, so nothing was inserted or sent.
- **Text Assist:**
  - Prompt: "internal note: printer driver was reinstalled, waiting on user confirmation".
  - The output was fluent but invented extra detail: that the incident "will be marked as resolved" once the user confirms.
  - The tool rewrites freely and needs human review.
- **Solution Generator:**
  - Prompt: "How to reset a forgotten Windows domain password for an employee".
  - It returned a clean title and structured content starting with a Problem Statement.
  - I did not add it to the form, and the solution form was left unsaved.
- **Conversation Summary:**
  - I could not find where it shows on request #42.
  - There is no summary button on the request header, the Actions menu, or the extra tabs menu.
  - The request has no email conversation, and email from users is the one locked input, so the summary may only appear once there is conversation. I could not create that without sending mail.
  - Treat its display location as unconfirmed.
- **New Request form:** with predictive features off, there are no AI suggestions on Category, Priority, Group or Technician. The description editor on New Request has no Zia icon; the AI icons appear only in the reply and note editors.
- **Resolution editor on a request:** it has "Search Solutions" and a Save and Add To Solutions button, but no AI icon, because Resolution Assist cannot use Zia.

## Edition notes

- Zia-hosted generative features work on this trial with no extra account or key.
- Resolution Assist and Code Generator cannot use the built-in Zia model. They need Azure OpenAI, ChatGPT, Claude or Google AI Studio, enabled under Third-party Integration, and I did not do that.
- Custom Script Generator is limited to Zia and Claude.
- Predictive features all show "Training Required" except Sentiment Analysis (which has "View Predictions"). I could not switch them on within the time spent.
- Agents depend on the separate Agent Studio.
- No usage limit, credit count or quota was displayed anywhere in this area.
- Blended Conversations is web only and Disabled.

## Weak spots / confusing UX

- The Setup search finds Ask Zia, but the sidebar link took me to Agents. Direct URLs for these pages are not guessable.
- The Zia icon opens "Reply Assist" in the reply editor but "Text Assist" in notes. One icon with two names, and no tooltip text on the neighbouring green icon.
- Conversation Summary can be switched on with no sign of where it will appear.
- Ask Zia gave 24 open requests against 25 on the dashboard. The SLA list header had a blank count.
- Disabling Conversation Summary warns that existing summaries will be hidden, but the others give no such warning.
- Each feature picks its provider separately, so there is no single AI provider setting.
- Chat answers carry destructive buttons (Delete, Close) on lists, easy to hit by accident.
- A Chatbot Customization page offers "search solutions from external sources", with no explanation of what sources.

## Limits of this area

- I did not enable Checklist Generator, Code Generator, Custom Script Generator, Request Auto Approval or Asset Acknowledgement. I only inspected their cards and provider lists.
- I did not open the workflow editor to see Workflow Assist in use, or the script and function editors for the code generators.
- Predictive features and Cluster Analysis were never switched on.
- Requester-facing AI (the Help Center chatbot) is deferred to Area 15.
- No AI feature in reports or anomaly detection was found beyond Ask Zia's charts and the canned Zia Dashboard.

## Test records created

None new in this area. Requests, solutions and other test objects were reused (request #42, SOL-6 and SOL-7). A reply form, a notes dialog, a resolution edit, a New Solution form and a New Incident form were opened and cancelled without saving.

## Restoration confirmation

| Setting | Original | Now |
|---|---|---|
| Ask Zia (Chatbot) | OFF | OFF (verified; Zia Actions tab gone again) |
| Conversation Summary | OFF | OFF (verified) |
| Reply Assist | OFF | OFF (verified) |
| Text Assist | OFF | OFF (verified) |
| Solution Generator | OFF | OFF (verified) |
| Workflow Assist | OFF | OFF (verified) |
| Other 5 GenAI cards | OFF | OFF, never touched (verified) |
| Predictive features | OFF | OFF, never touched |
| Cluster Analysis (AI insights, Problem Suggestion) | OFF | OFF, never touched |
| Chatbot Customization | unchanged | unchanged |
| Blended Conversations | Disabled | Disabled |

No external provider was connected and no API key was entered.

=== END OF AREA 10 ===
