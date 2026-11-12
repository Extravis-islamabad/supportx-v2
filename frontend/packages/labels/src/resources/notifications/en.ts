// notifications labels (see ../README.md). English is the reference.
export const en = {
  'assignee_unavailable.away': 'is set to Away',
  'assignee_unavailable.inactive': 'is no longer active',
  'assignee_unavailable.not_in_group': 'is not in that group any more',
  'delivery_reason.authentication_failed': "the mail server refused SupportX's sign-in",
  'delivery_reason.email_channel_not_configured': 'email channel not configured',
  'delivery_reason.gave_up': 'still failing after every retry',
  'delivery_reason.mail_not_configured': 'outgoing mail is not set up',
  'delivery_reason.mail_refused': 'the message could not be sent as written',
  'delivery_reason.message_refused': 'the mail server refused the message',
  'delivery_reason.no_address': 'the requester has no e-mail address',
  'delivery_reason.not_notified': 'the requester does not get e-mail about this',
  'delivery_reason.not_sent_in_time': 'never sent: mail was not set up within 7 days',
  'delivery_reason.recipient_deferred': "the recipient's mail server asked to try later",
  'delivery_reason.recipient_refused': "the recipient's mail server refused the address",
  'delivery_reason.server_busy': 'the mail server was busy',
  'delivery_reason.server_unavailable': 'the mail server could not be reached',
  'delivery_state.failed': 'Sending failed',
  'delivery_state.not_sent': 'Not sent',
  'delivery_state.queued': 'Sending',
  'delivery_state.received': 'Received',
  'delivery_state.retrying': 'Trying again',
  'delivery_state.sent': 'Sent',
  'delivery_state.waiting': 'Waiting for mail to be set up',
  'event_delivery.stalled.body':
    'Notifications, live updates and exports are delayed. Nothing is lost: they go out as soon as the service recovers.',
  'event_delivery.stalled.title': 'Event delivery is stalled',
  'event_delivery_state.ok': 'Delivering',
  'event_delivery_state.stalled': 'Stalled',
  'notification.open_record': 'Open {{id}}',
  'notification_area.announcement': 'Announcements',
  'notification_area.asset': 'Assets',
  'notification_area.change': 'Changes',
  'notification_area.connector': 'Connectors',
  'notification_area.incident': 'Incidents',
  'notification_area.kb_article': 'Knowledge',
  'notification_area.mailbox': 'Mail',
  'notification_area.outgoing_mail': 'Outgoing mail',
  'notification_area.problem': 'Problems',
  'notification_area.problem_repeat': 'Problems',
  'notification_area.release': 'Releases',
  'notification_area.rule_step': 'Rules and escalations',
  'notification_area.service_request': 'Service requests',
  'notification_area.task': 'Tasks',
  'notification_category.approval': 'Approvals',
  'notification_category.assignment': 'Assignments',
  'notification_category.conversation': 'Replies and notes',
  'notification_category.created': 'New records',
  'notification_category.following': 'Following',
  'notification_category.mention': 'Mentions',
  'notification_category.status': 'Status changes',
  'notification_category.workflow': 'Workflow messages',
  'notification_channel.email': 'E-mail',
  'notification_channel.in_app': 'In the app',
  'notification_condition_operator.in': 'is one of',
  'notification_condition_operator.not_in': 'is not one of',
  'notification_event.announcement.ended': 'An announcement you follow ended',
  'notification_event.announcement.updated': 'An announcement you follow was updated',
  'notification_event.asset.ack_disputed': 'Asset disputed by its holder',
  'notification_event.asset.ack_requested': 'Asset given to you: please acknowledge',
  'notification_event.asset.loan_due': 'Loan due tomorrow',
  'notification_event.asset.loan_overdue': 'Loan overdue',
  'notification_event.asset.mentioned': 'Mentioned in an asset note',
  'notification_event.asset.stock_low': 'Stock at its minimum',
  'notification_event.asset.warranty_expiring': 'Warranty ending soon',
  'notification_event.change.approval_fallback': 'Change approval with nobody to decide',
  'notification_event.change.approval_requested': 'Change approval needed',
  'notification_event.change.approved': 'Change approved',
  'notification_event.change.assigned': 'Change assigned to you',
  'notification_event.change.backed_out': 'Change backed out',
  'notification_event.change.board_empty': 'Change board has no members',
  'notification_event.change.cab_reminder': 'Change waits for your CAB decision',
  'notification_event.change.clarification': 'Change needs more information',
  'notification_event.change.closed': 'Change closed',
  'notification_event.change.implementation_failed': 'Change implementation failed',
  'notification_event.change.implementation_overdue': 'Change implementation overdue',
  'notification_event.change.implemented': 'Change implemented',
  'notification_event.change.mentioned': 'Mentioned on a change',
  'notification_event.change.note': 'Note on a change',
  'notification_event.change.overridden': 'Emergency override used',
  'notification_event.change.public_reply': 'Reply to the requester',
  'notification_event.change.rejected': 'Change rejected',
  'notification_event.change.review_due': 'Change review due',
  'notification_event.change.sent_back': 'Approved change needs approval again',
  'notification_event.change.status_entered': 'Change entered a status',
  'notification_event.change.submitted': 'Change submitted',
  'notification_event.change.window_reminder': 'Change window starts soon',
  'notification_event.connector.failing': 'Connector stopped working',
  'notification_event.connector.recovered': 'Connector works again',
  'notification_event.incident.assigned': 'Incident assigned',
  'notification_event.incident.canceled': 'Incident cancelled',
  'notification_event.incident.closed': 'Incident closed',
  'notification_event.incident.created': 'New incident: acknowledgement',
  'notification_event.incident.created_in_group': 'New incident in a group',
  'notification_event.incident.follower_added': 'Added as a follower',
  'notification_event.incident.mentioned': 'Mentioned',
  'notification_event.incident.private_note': 'Private note',
  'notification_event.incident.public_note': 'Public note',
  'notification_event.incident.public_reply': 'Public reply',
  'notification_event.incident.reopened': 'Incident reopened',
  'notification_event.incident.requester_replied': 'Requester replied',
  'notification_event.incident.resolved': 'Incident resolved',
  'notification_event.incident.sla_breached': 'SLA target overdue',
  'notification_event.incident.sla_escalated': 'SLA escalation',
  'notification_event.incident.sla_warning': 'SLA warning point reached',
  'notification_event.incident.status_changed': 'Status changed',
  'notification_event.incident.workflow_notice': 'A workflow’s message',
  'notification_event.kb_article.approved': 'Article approved',
  'notification_event.kb_article.rejected': 'Article sent back',
  'notification_event.kb_article.review_due': 'Article review due',
  'notification_event.kb_article.submitted': 'Article sent for review',
  'notification_event.kb_article.withdrawn': 'Article withdrawn',
  'notification_event.mailbox.credential_expiring': 'Mailbox app secret or certificate expiring',
  'notification_event.mailbox.failing': 'Mailbox stopped working',
  'notification_event.mailbox.mail_held': 'A sender is flooding a mailbox',
  'notification_event.outgoing_mail.not_sent': 'E-mails never sent: mail is not set up',
  'notification_event.problem.assigned': 'Problem assigned',
  'notification_event.problem.closed': 'Problem closed',
  'notification_event.problem.created_in_group': 'Problem created in your group',
  'notification_event.problem.investigator_added': 'Investigator added',
  'notification_event.problem.known_error': 'Known error published',
  'notification_event.problem.mentioned': 'Mentioned on a problem',
  'notification_event.problem.note': 'Note on a problem',
  'notification_event.problem.resolved': 'Problem solved',
  'notification_event.problem.target_breached': 'Problem target date passed',
  'notification_event.problem.target_warning': 'Problem target date close',
  'notification_event.problem_repeat.detected': 'Repeated incidents found',
  'notification_event.release.public_reply': 'Reply to the requester',
  'notification_event.rule_step.assignee_unavailable': 'Rule could not assign its person',
  'notification_event.service_request.approval_fallback': 'Approval waiting for the administrators',
  'notification_event.service_request.approval_requested': 'Approval requested',
  'notification_event.service_request.approved': 'Request approved',
  'notification_event.service_request.fulfilled': 'Request fulfilled',
  'notification_event.service_request.public_reply': 'Reply to the requester',
  'notification_event.service_request.ready_to_fulfil': 'Request ready to fulfil',
  'notification_event.service_request.received': 'Request received: acknowledgement',
  'notification_event.service_request.rejected': 'Request rejected',
  'notification_event.service_request.withdrawn': 'Request withdrawn',
  'notification_event.task.assigned': 'A task is given to you',
  'notification_event.task.overdue': 'Your task is overdue',
  'notification_event.task.starts_soon': 'Your task starts soon',
  'notification_preferences.col.category': 'Kind',
  'notification_preferences.dnd_help':
    'No pop-ups and no e-mail except urgent and required ones; everything still lands in your notifications.',
  'notification_preferences.help':
    'Choose what you hear about, and where. Some notifications are required by your organisation.',
  'notification_preferences.locked': 'Required by your organisation: it cannot be switched off.',
  'notification_preferences.saved': 'Preferences saved.',
  'notification_preferences.title': 'Notifications',
  'notification_reason.do_not_disturb': 'Do not disturb was on',
  'notification_reason.gave_up': 'Delivery gave up after several tries',
  'notification_reason.mail_refused': 'The mail server refused the message',
  'notification_reason.no_access': 'They can no longer see the record',
  'notification_reason.no_address': 'Inactive, or no e-mail address',
  'notification_reason.preference': 'Switched off in their preferences',
  'notification_recipient.approval_administrators': 'Approval administrators',
  'notification_recipient.approver': 'Approver',
  'notification_recipient.approvers': 'Approvers',
  'notification_recipient.asset_managers': 'Asset managers',
  'notification_recipient.assigned_by': 'The person who gave it',
  'notification_recipient.assignee': 'Assigned technician',
  'notification_recipient.author': 'Author',
  'notification_recipient.borrower': 'The borrower',
  'notification_recipient.cab': 'CAB members',
  'notification_recipient.cab_member': 'The CAB member waiting to decide',
  'notification_recipient.change_manager': 'Change manager',
  'notification_recipient.change_owner': 'Change owner',
  'notification_recipient.connector_admins': 'People who set up this connector',
  'notification_recipient.escalation_recipients': "The escalation level's recipients",
  'notification_recipient.followers': 'Followers',
  'notification_recipient.group': 'Group members',
  'notification_recipient.group_head': 'Group lead and department head',
  'notification_recipient.holder': 'The person who holds it',
  'notification_recipient.implementer': 'Implementer',
  'notification_recipient.line_manager': 'Line manager',
  'notification_recipient.linked_incident_technicians': 'Technicians of the linked incidents',
  'notification_recipient.loan_creator': 'The person who made the loan',
  'notification_recipient.mail_admins': 'People who manage mailboxes',
  'notification_recipient.mentioned': 'People mentioned',
  'notification_recipient.new_follower': 'The new follower',
  'notification_recipient.new_investigator': 'The investigator added',
  'notification_recipient.on_behalf_of': 'Person it is for',
  'notification_recipient.owner': 'Article owner',
  'notification_recipient.previous_assignee': 'Previous technician',
  'notification_recipient.requester': 'Requester',
  'notification_recipient.reviewer': 'Reviewer',
  'notification_recipient.step_owner': "The rule's owner (else its administrators)",
  'notification_recipient.stock_watchers': "The minimum's people",
  'notification_recipient.topic_owner': 'Topic owner',
  'notification_recipient.workflow_audience': 'People the workflow names',
  'notification_rules.any_priority': 'Any priority',
  'notification_rules.any_status': 'Any status',
  'notification_rules.changed': 'Changed {{when}}',
  'notification_rules.col.channels': 'How',
  'notification_rules.col.event': 'Event',
  'notification_rules.col.on': 'On',
  'notification_rules.col.priority': 'Only for priority',
  'notification_rules.col.recipients': 'Who',
  'notification_rules.col.status': 'Only for status',
  'notification_rules.intro':
    'Which events notify whom, and how. Every event starts with a sensible default; changes are recorded in the audit log.',
  'notification_rules.none': 'No event matches',
  'notification_rules.required': 'Required for people',
  'notification_rules.reset': 'Back to default',
  'notification_rules.saved': 'Notification rule saved.',
  'notification_rules.search': 'Search events',
  'notification_state.failed': 'Failed',
  'notification_state.queued': 'Sending',
  'notification_state.sent': 'Sent',
  'notification_state.suppressed': 'Not sent',
  'notification_state.waiting': 'Waiting for mail set-up',
  'notification_template.announcement.ended.body':
    'Hello {{ recipient.name }},\n\nThe announcement "{{ record.title }}" that you follow has ended.',
  'notification_template.announcement.ended.in_app': 'Ended: {{ record.title }}',
  'notification_template.announcement.ended.subject': 'Ended: {{ record.title }}',
  'notification_template.announcement.updated.body':
    'Hello {{ recipient.name }},\n\nThe announcement "{{ record.title }}" that you follow has been updated.',
  'notification_template.announcement.updated.in_app': 'Updated: {{ record.title }}',
  'notification_template.announcement.updated.subject': 'Updated: {{ record.title }}',
  'notification_template.asset.ack_disputed.body':
    'Hello {{ recipient.name }},\n\n{{ holder.name }} disputed {{ record.display_id }} "{{ record.title }}": {{ acknowledgement.comment }}',
  'notification_template.asset.ack_disputed.in_app':
    '{{ holder.name }} disputed {{ record.display_id }}: {{ acknowledgement.comment }}',
  'notification_template.asset.ack_disputed.subject':
    'Disputed: {{ record.display_id }} {{ record.title }}',
  'notification_template.asset.ack_requested.body':
    'Hello {{ recipient.name }},\n\nYou have been given {{ record.display_id }} "{{ record.title }}". Open My assets to accept it, or to say what is wrong.',
  'notification_template.asset.ack_requested.in_app':
    'Please acknowledge {{ record.display_id }}: {{ record.title }}',
  'notification_template.asset.ack_requested.subject':
    'Please acknowledge {{ record.display_id }} {{ record.title }}',
  'notification_template.asset.loan_due.body':
    'Hello {{ recipient.name }},\n\nThe assets loaned to {{ holder.name }} are due back tomorrow.',
  'notification_template.asset.loan_due.in_app': 'Loan to {{ holder.name }} is due tomorrow',
  'notification_template.asset.loan_due.subject': 'Loaned assets are due back tomorrow',
  'notification_template.asset.loan_overdue.body':
    'Hello {{ recipient.name }},\n\nThe assets loaned to {{ holder.name }} were due back and are not yet returned.',
  'notification_template.asset.loan_overdue.in_app': 'Loan to {{ holder.name }} is overdue',
  'notification_template.asset.loan_overdue.subject': 'Loaned assets are overdue',
  'notification_template.asset.mentioned.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} mentioned you in a note on {{ record.display_id }} "{{ record.title }}".',
  'notification_template.asset.mentioned.in_app':
    '{{ conversation.author }} mentioned you on {{ record.display_id }}',
  'notification_template.asset.mentioned.subject':
    'You were mentioned on {{ record.display_id }}: {{ record.title }}',
  'notification_template.asset.stock_low.body':
    'Hello {{ recipient.name }},\n\nStock of {{ record.title }} has fallen to {{ stock.quantity }}, at or below its minimum of {{ stock.minimum }}.',
  'notification_template.asset.stock_low.in_app':
    '{{ record.title }} is down to {{ stock.quantity }} (minimum {{ stock.minimum }})',
  'notification_template.asset.stock_low.subject': '{{ record.title }} is at its minimum stock',
  'notification_template.asset.warranty_expiring.body':
    'Hello {{ recipient.name }},\n\nThe warranty of {{ record.display_id }} "{{ record.title }}" ends on {{ warranty.ends_on }}.',
  'notification_template.asset.warranty_expiring.in_app':
    'Warranty of {{ record.display_id }} ends on {{ warranty.ends_on }}',
  'notification_template.asset.warranty_expiring.subject':
    'Warranty ending: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.approval_fallback.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" has an approval that nobody holds. An approval administrator can decide it.',
  'notification_template.change.approval_fallback.in_app':
    '{{ record.display_id }} has an approval with no approver: {{ record.title }}',
  'notification_template.change.approval_fallback.subject':
    'No approver: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.approval_requested.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" waits for your approval.\n\nApprove or reject: {{ approval_link }}\n\nThe link works once, for you only.',
  'notification_template.change.approval_requested.in_app':
    '{{ record.display_id }} waits for your approval: {{ record.title }}',
  'notification_template.change.approval_requested.subject':
    'Your approval: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.approved.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was approved. It is now: {{ record.status }}.',
  'notification_template.change.approved.in_app':
    '{{ record.display_id }} was approved: {{ record.title }}',
  'notification_template.change.approved.subject':
    'Approved: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.assigned.body':
    'Hello {{ recipient.name }},\n\nYou are now the change owner of {{ record.display_id }} "{{ record.title }}".',
  'notification_template.change.assigned.in_app':
    'You are the owner of {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.assigned.subject':
    'You own {{ record.display_id }} {{ record.title }}',
  'notification_template.change.backed_out.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was backed out. It is now: {{ record.status }}.',
  'notification_template.change.backed_out.in_app':
    '{{ record.display_id }} was backed out: {{ record.title }}',
  'notification_template.change.backed_out.subject':
    'Backed out: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.board_empty.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" waits for a change board that has no members. Add members to the board, or choose another one.',
  'notification_template.change.board_empty.in_app':
    '{{ record.display_id }} waits for a board with no members: {{ record.title }}',
  'notification_template.change.board_empty.subject':
    'Board with no members: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.cab_reminder.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" starts at {{ window.start }} and still waits for your decision.\n\nApprove or reject: {{ approval_link }}',
  'notification_template.change.cab_reminder.in_app':
    '{{ record.display_id }} starts at {{ window.start }} and waits for you: {{ record.title }}',
  'notification_template.change.cab_reminder.subject':
    'Your decision, starts soon: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.clarification.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" needs more information before it can go on. Open it to see what is asked.',
  'notification_template.change.clarification.in_app':
    '{{ record.display_id }} needs more information: {{ record.title }}',
  'notification_template.change.clarification.subject':
    'More information needed: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.closed.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" is closed.',
  'notification_template.change.closed.in_app':
    '{{ record.display_id }} was closed: {{ record.title }}',
  'notification_template.change.closed.subject':
    'Closed: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.implementation_failed.body':
    'Hello {{ recipient.name }},\n\nThe implementation of {{ record.display_id }} "{{ record.title }}" failed. It is now: {{ record.status }}.',
  'notification_template.change.implementation_failed.in_app':
    '{{ record.display_id }} failed in implementation: {{ record.title }}',
  'notification_template.change.implementation_failed.subject':
    'Implementation failed: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.implementation_overdue.body':
    'Hello {{ recipient.name }},\n\nThe implementation window of {{ record.display_id }} "{{ record.title }}" has ended, and the change is not implemented yet.',
  'notification_template.change.implementation_overdue.in_app':
    'The window of {{ record.display_id }} has ended, and it is not implemented: {{ record.title }}',
  'notification_template.change.implementation_overdue.subject':
    'Implementation overdue: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.implemented.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was implemented. It is now: {{ record.status }}.',
  'notification_template.change.implemented.in_app':
    '{{ record.display_id }} was implemented: {{ record.title }}',
  'notification_template.change.implemented.subject':
    'Implemented: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.mentioned.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} mentioned you on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.change.mentioned.in_app':
    '{{ conversation.author }} mentioned you on {{ record.display_id }}',
  'notification_template.change.mentioned.subject':
    'You were mentioned on {{ record.display_id }} {{ record.title }}',
  'notification_template.change.note.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} added a note on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.change.note.in_app':
    '{{ conversation.author }} added a note on {{ record.display_id }}',
  'notification_template.change.note.subject':
    'New note: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.overridden.body':
    'Hello {{ recipient.name }},\n\nThe emergency override was used on {{ record.display_id }} "{{ record.title }}". Its review is now required.',
  'notification_template.change.overridden.in_app':
    'The emergency override was used on {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.overridden.subject':
    'Emergency override: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.public_reply.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} replied on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.change.public_reply.in_app':
    '{{ conversation.author }} replied on {{ record.display_id }}',
  'notification_template.change.public_reply.subject':
    'New reply on {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.rejected.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was rejected. It is now: {{ record.status }}.',
  'notification_template.change.rejected.in_app':
    '{{ record.display_id }} was rejected: {{ record.title }}',
  'notification_template.change.rejected.subject':
    'Rejected: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.review_due.body':
    'Hello {{ recipient.name }},\n\nThe post-implementation review of {{ record.display_id }} "{{ record.title }}" is due.',
  'notification_template.change.review_due.in_app':
    'The review of {{ record.display_id }} is due: {{ record.title }}',
  'notification_template.change.review_due.subject':
    'Review due: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.sent_back.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" changed after it was approved, so it needs approval again.',
  'notification_template.change.sent_back.in_app':
    '{{ record.display_id }} needs approval again: {{ record.title }}',
  'notification_template.change.sent_back.subject':
    'Needs approval again: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.status_entered.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" is now: {{ record.status }}.',
  'notification_template.change.status_entered.in_app':
    '{{ record.display_id }} is now {{ record.status }}: {{ record.title }}',
  'notification_template.change.status_entered.subject':
    '{{ record.status }}: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.submitted.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was submitted and waits for the change manager.',
  'notification_template.change.submitted.in_app':
    '{{ record.display_id }} was submitted: {{ record.title }}',
  'notification_template.change.submitted.subject':
    'Submitted: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.window_reminder.body':
    'Hello {{ recipient.name }},\n\nThe implementation window of {{ record.display_id }} "{{ record.title }}" starts at {{ window.start }}.',
  'notification_template.change.window_reminder.in_app':
    '{{ record.display_id }} starts at {{ window.start }}: {{ record.title }}',
  'notification_template.change.window_reminder.subject':
    'Starts soon: {{ record.display_id }} {{ record.title }}',
  'notification_template.connector.failing.body':
    'Hello {{ recipient.name }},\n\n{{ record.title }} stopped working: {{ connector.reason }}.\n\nYou are told once, not at every attempt, and again when it works. Open Admin › Integrations to see it.',
  'notification_template.connector.failing.in_app':
    '{{ record.title }} stopped working: {{ connector.reason }}',
  'notification_template.connector.failing.subject': '{{ record.title }} stopped working',
  'notification_template.connector.recovered.body':
    'Hello {{ recipient.name }},\n\n{{ record.title }} works again. Nothing else is needed.',
  'notification_template.connector.recovered.in_app': '{{ record.title }} works again',
  'notification_template.connector.recovered.subject': '{{ record.title }} works again',
  'notification_template.incident.assigned.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" is now assigned to {{ assignee.name }}.\n\nPriority: {{ record.priority }}\nStatus: {{ record.status }}\nRequester: {{ requester.name }}',
  'notification_template.incident.assigned.in_app':
    '{{ record.display_id }} is assigned to {{ assignee.name }}: {{ record.title }}',
  'notification_template.incident.assigned.subject':
    'Assigned to {{ assignee.name }}: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.canceled.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was cancelled.',
  'notification_template.incident.canceled.in_app': '{{ record.display_id }} was cancelled',
  'notification_template.incident.canceled.subject':
    'Cancelled: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.closed.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" is now closed.',
  'notification_template.incident.closed.in_app': '{{ record.display_id }} was closed',
  'notification_template.incident.closed.subject':
    'Closed: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.created.body':
    'Hello {{ recipient.name }},\n\nWe received your request "{{ record.title }}" and logged it as {{ record.display_id }}. We will keep you updated.',
  'notification_template.incident.created.in_app':
    'We received {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.created.subject':
    'We received your request {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.created_in_group.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" arrived in your group.\n\nPriority: {{ record.priority }}\nRequester: {{ requester.name }}',
  'notification_template.incident.created_in_group.in_app':
    'New in your group: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.created_in_group.subject':
    'New incident {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.follower_added.body':
    'Hello {{ recipient.name }},\n\nYou now follow {{ record.display_id }} "{{ record.title }}" and will hear about its updates.',
  'notification_template.incident.follower_added.in_app':
    'You now follow {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.follower_added.subject':
    'You now follow {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.mentioned.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} mentioned you on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.incident.mentioned.in_app':
    '{{ conversation.author }} mentioned you on {{ record.display_id }}',
  'notification_template.incident.mentioned.subject':
    'You were mentioned on {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.private_note.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} added a private note on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.incident.private_note.in_app':
    '{{ conversation.author }} added a private note on {{ record.display_id }}',
  'notification_template.incident.private_note.subject':
    'Private note on {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.public_note.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} added a note on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.incident.public_note.in_app':
    '{{ conversation.author }} added a note on {{ record.display_id }}',
  'notification_template.incident.public_note.subject':
    'New note on {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.public_reply.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} replied on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.incident.public_reply.in_app':
    '{{ conversation.author }} replied on {{ record.display_id }}',
  'notification_template.incident.public_reply.subject':
    'New reply on {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.reopened.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was reopened and needs attention again.\n\nStatus: {{ record.status }}',
  'notification_template.incident.reopened.in_app': '{{ record.display_id }} was reopened',
  'notification_template.incident.reopened.subject':
    'Reopened: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.requester_replied.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} replied on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.incident.requester_replied.in_app':
    '{{ conversation.author }} (requester) replied on {{ record.display_id }}',
  'notification_template.incident.requester_replied.subject':
    'The requester replied on {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.resolved.body':
    'Hello {{ recipient.name }},\n\nWe have resolved {{ record.display_id }} "{{ record.title }}". If the problem is still there, reply to let us know.',
  'notification_template.incident.resolved.in_app': '{{ record.display_id }} was resolved',
  'notification_template.incident.resolved.subject':
    'Resolved: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_breached.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" has passed the due time of its {{ sla.target }} target.',
  'notification_template.incident.sla_breached.in_app':
    '{{ record.display_id }}: {{ sla.target }} is overdue',
  'notification_template.incident.sla_breached.subject':
    'Overdue: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_escalated.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was escalated to you by its {{ sla.target }} SLA.',
  'notification_template.incident.sla_escalated.in_app':
    'Escalated to you: {{ record.display_id }} ({{ sla.target }})',
  'notification_template.incident.sla_escalated.subject':
    'Escalation: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_warning.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" has reached the warning point of its {{ sla.target }} target.',
  'notification_template.incident.sla_warning.in_app':
    '{{ record.display_id }}: {{ sla.target }} is close to its due time',
  'notification_template.incident.sla_warning.subject':
    'Due soon: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.status_changed.body':
    'Hello {{ recipient.name }},\n\nThe status of {{ record.display_id }} "{{ record.title }}" changed from {{ change.from_status }} to {{ record.status }}.',
  'notification_template.incident.status_changed.in_app':
    '{{ record.display_id }} is now {{ record.status }}',
  'notification_template.incident.status_changed.subject':
    '{{ record.display_id }} is now {{ record.status }}: {{ record.title }}',
  'notification_template.incident.workflow_notice.body': '{{ notice.body }}',
  'notification_template.incident.workflow_notice.in_app': '{{ notice.subject }}',
  'notification_template.incident.workflow_notice.subject': '{{ notice.subject }}',
  'notification_template.kb_article.approved.body':
    'Hello {{ recipient.name }},\n\n{{ actor.name }} approved the article {{ record.display_id }} "{{ record.title }}". Its readers see it now.',
  'notification_template.kb_article.approved.in_app':
    '{{ record.display_id }} is published: {{ record.title }}',
  'notification_template.kb_article.approved.subject':
    'Published: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.rejected.body':
    'Hello {{ recipient.name }},\n\n{{ actor.name }} sent the article {{ record.display_id }} "{{ record.title }}" back as a draft.\n\nReason: {{ article.reason }}',
  'notification_template.kb_article.rejected.in_app':
    '{{ record.display_id }} was sent back: {{ article.reason }}',
  'notification_template.kb_article.rejected.subject':
    'Sent back: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.review_due.body':
    'Hello {{ recipient.name }},\n\nThe article {{ record.display_id }} "{{ record.title }}" was due for review on {{ article.review_on }}. Check it is still correct, or edit it.',
  'notification_template.kb_article.review_due.in_app':
    '{{ record.display_id }} is due for review: {{ record.title }}',
  'notification_template.kb_article.review_due.subject':
    'Review due: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.submitted.body':
    'Hello {{ recipient.name }},\n\n{{ actor.name }} sent the article {{ record.display_id }} "{{ record.title }}" for review. Open it to approve it or send it back.',
  'notification_template.kb_article.submitted.in_app':
    '{{ actor.name }} sent {{ record.display_id }} for review: {{ record.title }}',
  'notification_template.kb_article.submitted.subject':
    'Review requested: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.withdrawn.body':
    'Hello {{ recipient.name }},\n\n{{ actor.name }} withdrew the article {{ record.display_id }} "{{ record.title }}". Readers no longer see it.\n\nReason: {{ article.reason }}',
  'notification_template.kb_article.withdrawn.in_app':
    '{{ record.display_id }} was withdrawn: {{ article.reason }}',
  'notification_template.kb_article.withdrawn.subject':
    'Withdrawn: {{ record.display_id }} {{ record.title }}',
  'notification_template.mailbox.credential_expiring.body':
    'Hello {{ recipient.name }},\n\nThe secret or certificate SupportX uses to read {{ record.title }} expires {{ mailbox.expires_at }}. Add a new one in your Microsoft or Google admin console, then enter it in Admin › Mail, so mail keeps arriving.',
  'notification_template.mailbox.credential_expiring.in_app':
    'The app secret or certificate of {{ record.title }} expires {{ mailbox.expires_at }}',
  'notification_template.mailbox.credential_expiring.subject':
    'Mailbox {{ record.title }}: app credential expires soon',
  'notification_template.mailbox.failing.body':
    'Hello {{ recipient.name }},\n\nSupportX cannot read {{ record.title }}: {{ mailbox.reason }}.\n\nMail waits on the server until this is fixed. Open Admin › Mail to see the mailbox.',
  'notification_template.mailbox.failing.in_app':
    '{{ record.title }} stopped working: {{ mailbox.reason }}',
  'notification_template.mailbox.failing.subject': 'Mailbox {{ record.title }} stopped working',
  'notification_template.mailbox.mail_held.body':
    'Hello {{ recipient.name }},\n\nA sender sent more than 10 messages in an hour to {{ record.title }}, replies included. SupportX holds their further mail instead of creating records, so nothing is lost and no loop runs.\n\nOpen Admin › Mail, review the held messages, and hand them in again or discard them.',
  'notification_template.mailbox.mail_held.in_app':
    'Mail to {{ record.title }} is held for review: a sender sent more than 10 messages in an hour',
  'notification_template.mailbox.mail_held.subject':
    'Mailbox {{ record.title }}: mail held for review',
  'notification_template.outgoing_mail.not_sent.body':
    'Hello {{ recipient.name }},\n\n{{ mail.count }} e-mails were never sent, because outgoing mail was not set up within 7 days. The oldest was from {{ mail.oldest_at }}. They will not be sent late. Open Admin › Mail to set up outgoing mail.',
  'notification_template.outgoing_mail.not_sent.in_app':
    '{{ mail.count }} e-mails were never sent: outgoing mail was not set up within 7 days (the oldest from {{ mail.oldest_at }}). Set up mail so the next ones go.',
  'notification_template.outgoing_mail.not_sent.subject':
    '{{ mail.count }} e-mails were never sent',
  'notification_template.problem.assigned.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" is now assigned to {{ assignee.name }}.\n\nPriority: {{ record.priority }}\nStatus: {{ record.status }}',
  'notification_template.problem.assigned.in_app':
    '{{ record.display_id }} is assigned to {{ assignee.name }}: {{ record.title }}',
  'notification_template.problem.assigned.subject':
    'Assigned to {{ assignee.name }}: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.closed.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was closed.',
  'notification_template.problem.closed.in_app': '{{ record.display_id }} was closed',
  'notification_template.problem.closed.subject':
    'Closed: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.created_in_group.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was created in your group.',
  'notification_template.problem.created_in_group.in_app':
    'New problem: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.created_in_group.subject':
    'New problem in your group: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.investigator_added.body':
    'Hello {{ recipient.name }},\n\n{{ actor.name }} added you as an investigator on {{ record.display_id }} "{{ record.title }}". You can work its tasks and worklogs.',
  'notification_template.problem.investigator_added.in_app':
    'You are investigating {{ record.display_id }}: {{ record.title }}',
  'notification_template.problem.investigator_added.subject':
    'You are investigating {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.known_error.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" is now a known error. Its workaround can be applied to your incidents.',
  'notification_template.problem.known_error.in_app':
    '{{ record.display_id }} is a known error: apply its workaround',
  'notification_template.problem.known_error.subject':
    'Known error: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.mentioned.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} mentioned you on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.problem.mentioned.in_app':
    '{{ conversation.author }} mentioned you on {{ record.display_id }}',
  'notification_template.problem.mentioned.subject':
    '{{ conversation.author }} mentioned you on {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.note.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} wrote on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.problem.note.in_app':
    '{{ conversation.author }} wrote on {{ record.display_id }}',
  'notification_template.problem.note.subject':
    'New note on {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.resolved.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" is solved. Check the incidents it caused and resolve them.',
  'notification_template.problem.resolved.in_app':
    '{{ record.display_id }} is solved: {{ record.title }}',
  'notification_template.problem.resolved.subject':
    'Solved: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.target_breached.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" has passed its {{ sla.target }} target date.',
  'notification_template.problem.target_breached.in_app':
    '{{ record.display_id }} is past its target date',
  'notification_template.problem.target_breached.subject':
    'Overdue: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.target_warning.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" is close to its {{ sla.target }} target date.',
  'notification_template.problem.target_warning.in_app':
    '{{ record.display_id }}: the target date is close',
  'notification_template.problem.target_warning.subject':
    'Due soon: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem_repeat.detected.body':
    'Hello {{ recipient.name }},\n\n{{ incident.count }} incidents match "{{ rule.name }}" ({{ category.name }}, {{ site.name }}). Look at them and create a problem if they share a cause.',
  'notification_template.problem_repeat.detected.in_app':
    '{{ incident.count }} similar incidents: {{ rule.name }}',
  'notification_template.problem_repeat.detected.subject':
    '{{ incident.count }} similar incidents: {{ rule.name }}',
  'notification_template.release.public_reply.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} replied on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.release.public_reply.in_app':
    '{{ conversation.author }} replied on {{ record.display_id }}',
  'notification_template.release.public_reply.subject':
    'New reply on {{ record.display_id }}: {{ record.title }}',
  'notification_template.rule_step.assignee_unavailable.body':
    'Hello {{ recipient.name }},\n\nA rule or escalation was to assign {{ record.display_id }} "{{ record.title }}" to {{ unavailable.person }}, who {{ unavailable.reason }}. It went to the group with nobody on it. Please assign someone, or change the rule.',
  'notification_template.rule_step.assignee_unavailable.in_app':
    '{{ record.display_id }} went to its group with nobody on it: {{ unavailable.person }} {{ unavailable.reason }}',
  'notification_template.rule_step.assignee_unavailable.subject':
    'Nobody assigned: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.approval_fallback.body':
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" has no active approver, so it waits for an approval administrator.',
  'notification_template.service_request.approval_fallback.in_app':
    '{{ record.display_id }} has no active approver and waits for an approval administrator: {{ record.title }}',
  'notification_template.service_request.approval_fallback.subject':
    'Approval waiting: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.approval_requested.body':
    'Hello {{ recipient.name }},\n\n{{ requester.name }} asks for {{ record.display_id }} "{{ record.title }}", and it waits for your approval.\n\nApprove or reject: {{ approval_link }}\n\nThe link works once, for you only, after you sign in.',
  'notification_template.service_request.approval_requested.in_app':
    '{{ record.display_id }} waits for your approval: {{ record.title }}',
  'notification_template.service_request.approval_requested.subject':
    'Your approval: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.approved.body':
    'Hello {{ recipient.name }},\n\nYour request {{ record.display_id }} "{{ record.title }}" was approved. We are working on it now.',
  'notification_template.service_request.approved.in_app':
    '{{ record.display_id }} was approved: {{ record.title }}',
  'notification_template.service_request.approved.subject':
    'Approved: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.fulfilled.body':
    'Hello {{ recipient.name }},\n\nYour request {{ record.display_id }} "{{ record.title }}" is done. Please confirm you received it, or tell us if something is missing.',
  'notification_template.service_request.fulfilled.in_app':
    '{{ record.display_id }} is done: {{ record.title }}',
  'notification_template.service_request.fulfilled.subject':
    'Done: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.public_reply.body':
    'Hello {{ recipient.name }},\n\n{{ conversation.author }} replied on {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.service_request.public_reply.in_app':
    '{{ conversation.author }} replied on {{ record.display_id }}',
  'notification_template.service_request.public_reply.subject':
    'New reply on {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.ready_to_fulfil.body':
    'Hello {{ recipient.name }},\n\nEvery task of {{ record.display_id }} "{{ record.title }}" is done, but nobody is on it. Assign someone of your group to fulfil it.',
  'notification_template.service_request.ready_to_fulfil.in_app':
    '{{ record.display_id }} is ready to fulfil: assign someone',
  'notification_template.service_request.ready_to_fulfil.subject':
    'Ready to fulfil: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.received.body':
    'Hello {{ recipient.name }},\n\nWe received your request "{{ record.title }}" and logged it as {{ record.display_id }}. We will keep you updated.',
  'notification_template.service_request.received.in_app':
    'We received {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.received.subject':
    'We received your request {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.rejected.body':
    'Hello {{ recipient.name }},\n\nYour request {{ record.display_id }} "{{ record.title }}" was not approved.{% if approval.comment %}\n\nThe approver said: {{ approval.comment }}{% endif %}',
  'notification_template.service_request.rejected.in_app':
    '{{ record.display_id }} was not approved: {{ record.title }}',
  'notification_template.service_request.rejected.subject':
    'Not approved: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.withdrawn.body':
    'Hello {{ recipient.name }},\n\nYour request {{ record.display_id }} "{{ record.title }}" was withdrawn. Nothing more will happen with it.',
  'notification_template.service_request.withdrawn.in_app':
    '{{ record.display_id }} was withdrawn: {{ record.title }}',
  'notification_template.service_request.withdrawn.subject':
    'Withdrawn: {{ record.display_id }} {{ record.title }}',
  'notification_template.task.assigned.body':
    'Hello {{ recipient.name }},\n\nThe task "{{ task.title }}" on {{ record.display_id }} "{{ record.title }}" is now yours.',
  'notification_template.task.assigned.in_app':
    '{{ task.title }} on {{ record.display_id }} is yours',
  'notification_template.task.assigned.subject':
    'Task for you: {{ task.title }} ({{ record.display_id }})',
  'notification_template.task.overdue.body':
    'Hello {{ recipient.name }},\n\nYour task "{{ task.title }}" on {{ record.display_id }} "{{ record.title }}" was due at {{ task.due_at }} and is still open.',
  'notification_template.task.overdue.in_app': '{{ task.title }} was due at {{ task.due_at }}',
  'notification_template.task.overdue.subject':
    'Overdue: {{ task.title }} ({{ record.display_id }})',
  'notification_template.task.starts_soon.body':
    'Hello {{ recipient.name }},\n\nYour task "{{ task.title }}" on {{ record.display_id }} "{{ record.title }}" starts at {{ task.starts_at }}.',
  'notification_template.task.starts_soon.in_app':
    '{{ task.title }} starts at {{ task.starts_at }}',
  'notification_template.task.starts_soon.subject':
    'Starts soon: {{ task.title }} ({{ record.display_id }})',
  'notification_variable.acknowledgement.comment': 'Acknowledgement › Comment',
  'notification_variable.actor.name': 'Changed by › Name',
  'notification_variable.approval.comment': 'Approval › Comment',
  'notification_variable.approval_link': 'Approval › Link',
  'notification_variable.article.reason': 'Article › Reason',
  'notification_variable.article.review_on': 'Article › Review date',
  'notification_variable.assignee.name': 'Technician › Name',
  'notification_variable.category.name': 'Category',
  'notification_variable.change.from_status': 'Change › Previous status',
  'notification_variable.connector.name': 'Connector › Name',
  'notification_variable.connector.reason': 'Connector › Reason',
  'notification_variable.conversation.author': 'Reply or note › Author',
  'notification_variable.conversation.excerpt': 'Reply or note › Text',
  'notification_variable.holder.name': 'Holder › Name',
  'notification_variable.incident.count': 'Number of incidents',
  'notification_variable.mail.count': 'Mail › E-mails not sent',
  'notification_variable.mail.oldest_at': 'Mail › Oldest',
  'notification_variable.mailbox.address': 'Mailbox › Address',
  'notification_variable.mailbox.expires_at': 'Mailbox › Credential expires',
  'notification_variable.mailbox.reason': 'Mailbox › Reason',
  'notification_variable.notice.body': 'Message › Text',
  'notification_variable.notice.subject': 'Message › Subject',
  'notification_variable.recipient.name': 'Recipient › Name',
  'notification_variable.record.display_id': 'Record › ID',
  'notification_variable.record.link': 'Record › Link',
  'notification_variable.record.priority': 'Record › Priority',
  'notification_variable.record.status': 'Record › Status',
  'notification_variable.record.title': 'Record › Subject',
  'notification_variable.requester.name': 'Requester › Name',
  'notification_variable.rule.name': 'Rule',
  'notification_variable.site.name': 'Site',
  'notification_variable.sla.target': 'SLA › Target',
  'notification_variable.stock.minimum': 'Stock › Minimum',
  'notification_variable.stock.quantity': 'Stock › Quantity',
  'notification_variable.task.due_at': 'Task due time',
  'notification_variable.task.starts_at': 'Task scheduled start',
  'notification_variable.task.title': 'Task title',
  'notification_variable.unavailable.person': 'Unassigned › Person',
  'notification_variable.unavailable.reason': 'Unassigned › Why',
  'notification_variable.warranty.ends_on': 'Warranty › Ends on',
  'notification_variable.window.start': 'Window start',
  'notifications.banner.no_mail_one':
    '{{count}} e-mail waits because outgoing mail is not set up. In-app notifications still go out; the e-mail is sent once mail works.',
  'notifications.banner.no_mail_other':
    '{{count}} e-mails wait because outgoing mail is not set up. In-app notifications still go out; the e-mails are sent once mail works.',
  'notifications.banner.sending_one': '{{count}} waiting e-mail is being sent now.',
  'notifications.banner.sending_other': '{{count}} waiting e-mails are being sent now.',
  'notifications.banner.title': 'E-mail notifications are waiting',
  'notifications.do_not_disturb': 'Do not disturb',
  'notifications.empty': 'No notifications yet.',
  'notifications.more': 'Show older',
  'notifications.open_one': 'Notifications, {{count}} unread',
  'notifications.open_other': 'Notifications, {{count}} unread',
  'notifications.read_all': 'Mark all read',
  'notifications.title': 'Notifications',
} as const;
