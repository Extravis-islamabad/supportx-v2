// notifications labels (see ../README.md). English is the reference.
export const en = {
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
  'notification_area.asset': 'Assets',
  'notification_category.approval': 'Approvals',
  'notification_category.assignment': 'Assignments',
  'notification_category.conversation': 'Replies and notes',
  'notification_category.created': 'New records',
  'notification_category.following': 'Following',
  'notification_category.mention': 'Mentions',
  'notification_category.status': 'Status changes',
  'notification_channel.email': 'E-mail',
  'notification_channel.in_app': 'In the app',
  'notification_condition_operator.in': 'is one of',
  'notification_condition_operator.not_in': 'is not one of',
  'notification_event.announcement.ended': 'An announcement you follow ended',
  'notification_event.announcement.updated': 'An announcement you follow was updated',
  'notification_event.asset.ack_disputed': 'Asset disputed by its holder',
  'notification_event.asset.ack_requested': 'Asset given to you: please acknowledge',
  'notification_event.connector.failing': 'Connector stopped working',
  'notification_event.connector.recovered': 'Connector works again',
  'notification_event.incident.assigned': 'Incident assigned',
  'notification_event.incident.canceled': 'Incident canceled',
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
  'notification_event.kb_article.approved': 'Article approved',
  'notification_event.kb_article.rejected': 'Article sent back',
  'notification_event.kb_article.review_due': 'Article review due',
  'notification_event.kb_article.submitted': 'Article sent for review',
  'notification_event.kb_article.withdrawn': 'Article withdrawn',
  'notification_event.mailbox.credential_expiring': 'Mailbox app secret or certificate expiring',
  'notification_event.mailbox.failing': 'Mailbox stopped working',
  'notification_event.mailbox.mail_held': 'A sender is flooding a mailbox',
  'notification_event.service_request.approval_fallback': 'Approval waiting for the administrators',
  'notification_event.service_request.approval_requested': 'Approval requested',
  'notification_preferences.col.category': 'Kind',
  'notification_preferences.dnd_help':
    'No pop-ups and no e-mail except urgent and required ones; everything still lands in your notifications.',
  'notification_preferences.help':
    'Choose what you hear about, and where. Some notifications are required by your organization.',
  'notification_preferences.locked': 'Required by your organization: it cannot be switched off.',
  'notification_preferences.saved': 'Preferences saved.',
  'notification_preferences.title': 'Notifications',
  'notification_reason.do_not_disturb': 'Do not disturb was on',
  'notification_reason.gave_up': 'Delivery gave up after several tries',
  'notification_reason.mail_refused': 'The mail server refused the message',
  'notification_reason.no_access': 'They can no longer see the record',
  'notification_reason.no_address': 'Inactive, or no e-mail address',
  'notification_reason.preference': 'Switched off in their preferences',
  'notification_recipient.approvers': 'Approvers',
  'notification_recipient.assigned_by': 'The person who gave it',
  'notification_recipient.assignee': 'Assigned technician',
  'notification_recipient.author': 'Author',
  'notification_recipient.connector_admins': 'People who set up this connector',
  'notification_recipient.escalation_recipients': "The escalation level's recipients",
  'notification_recipient.followers': 'Followers',
  'notification_recipient.group': 'Group members',
  'notification_recipient.group_head': 'Group lead and department head',
  'notification_recipient.holder': 'The person who holds it',
  'notification_recipient.mail_admins': 'People who manage mailboxes',
  'notification_recipient.mentioned': 'People mentioned',
  'notification_recipient.new_follower': 'The new follower',
  'notification_recipient.on_behalf_of': 'Person it is for',
  'notification_recipient.owner': 'Article owner',
  'notification_recipient.previous_assignee': 'Previous technician',
  'notification_recipient.requester': 'Requester',
  'notification_recipient.topic_owner': 'Topic owner',
  'notification_rules.any_priority': 'Any priority',
  'notification_rules.changed': 'Changed {{when}}',
  'notification_rules.col.channels': 'How',
  'notification_rules.col.event': 'Event',
  'notification_rules.col.on': 'On',
  'notification_rules.col.priority': 'Only for priority',
  'notification_rules.col.recipients': 'Who',
  'notification_rules.default': 'Default',
  'notification_rules.intro':
    'Which events notify whom, and how. Every event starts with a sensible default; changes are recorded in the audit log.',
  'notification_rules.required': 'Required for people',
  'notification_rules.reset': 'Back to default',
  'notification_rules.saved': 'Notification rule saved.',
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
    'Hello {{ recipient.name }},\n\n{{ record.display_id }} "{{ record.title }}" was canceled.',
  'notification_template.incident.canceled.in_app': '{{ record.display_id }} was canceled',
  'notification_template.incident.canceled.subject':
    'Canceled: {{ record.display_id }} {{ record.title }}',
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
  'notification_variable.acknowledgement.comment': 'Acknowledgement › Comment',
  'notification_variable.actor.name': 'Changed by › Name',
  'notification_variable.approval_link': 'Approval › Link',
  'notification_variable.article.reason': 'Article › Reason',
  'notification_variable.article.review_on': 'Article › Review date',
  'notification_variable.assignee.name': 'Technician › Name',
  'notification_variable.change.from_status': 'Change › Previous status',
  'notification_variable.connector.name': 'Connector › Name',
  'notification_variable.connector.reason': 'Connector › Reason',
  'notification_variable.conversation.author': 'Reply or note › Author',
  'notification_variable.conversation.excerpt': 'Reply or note › Text',
  'notification_variable.holder.name': 'Holder › Name',
  'notification_variable.mailbox.address': 'Mailbox › Address',
  'notification_variable.mailbox.expires_at': 'Mailbox › Credential expires',
  'notification_variable.mailbox.reason': 'Mailbox › Reason',
  'notification_variable.recipient.name': 'Recipient › Name',
  'notification_variable.record.display_id': 'Record › ID',
  'notification_variable.record.link': 'Record › Link',
  'notification_variable.record.priority': 'Record › Priority',
  'notification_variable.record.status': 'Record › Status',
  'notification_variable.record.title': 'Record › Subject',
  'notification_variable.requester.name': 'Requester › Name',
  'notification_variable.sla.target': 'SLA › Target',
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
