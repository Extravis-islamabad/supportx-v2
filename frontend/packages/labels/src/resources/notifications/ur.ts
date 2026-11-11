import type { LabelResource } from '../en';

// notifications labels (see ../README.md).
export const ur: LabelResource = {
  'assignee_unavailable.away': 'غیر حاضر پر ہیں',
  'assignee_unavailable.inactive': 'اب فعال نہیں',
  'assignee_unavailable.not_in_group': 'اب اس گروپ میں نہیں',
  'delivery_reason.authentication_failed': 'میل سرور نے SupportX کا سائن اِن رد کر دیا',
  'delivery_reason.email_channel_not_configured': 'ای میل چینل ترتیب نہیں دیا گیا',
  'delivery_reason.gave_up': 'ہر کوشش کے بعد بھی ناکام',
  'delivery_reason.mail_not_configured': 'باہر جانے والی میل ترتیب نہیں دی گئی',
  'delivery_reason.mail_refused': 'پیغام لکھے گئے انداز میں نہیں بھیجا جا سکا',
  'delivery_reason.message_refused': 'میل سرور نے پیغام رد کر دیا',
  'delivery_reason.no_address': 'درخواست گزار کا کوئی ای میل پتہ نہیں',
  'delivery_reason.not_notified': 'درخواست گزار کو اس بارے میں ای میل نہیں جاتی',
  'delivery_reason.not_sent_in_time': 'نہیں بھیجا گیا: 7 دن میں میل ترتیب نہیں دی گئی',
  'delivery_reason.recipient_deferred': 'وصول کنندہ کے میل سرور نے بعد میں کوشش کرنے کو کہا',
  'delivery_reason.recipient_refused': 'وصول کنندہ کے میل سرور نے پتہ رد کر دیا',
  'delivery_reason.server_busy': 'میل سرور مصروف تھا',
  'delivery_reason.server_unavailable': 'میل سرور تک رسائی نہیں ہو سکی',
  'delivery_state.failed': 'بھیجنا ناکام ہوا',
  'delivery_state.not_sent': 'نہیں بھیجا گیا',
  'delivery_state.queued': 'بھیجا جا رہا ہے',
  'delivery_state.received': 'موصول',
  'delivery_state.retrying': 'دوبارہ کوشش جاری',
  'delivery_state.sent': 'بھیج دیا گیا',
  'delivery_state.waiting': 'میل ترتیب دیے جانے کا انتظار',
  'event_delivery.stalled.body':
    'اطلاعات، براہ راست اپ ڈیٹس اور ایکسپورٹس میں تاخیر ہے۔ کچھ ضائع نہیں ہوگا: سروس بحال ہوتے ہی یہ بھیج دیے جائیں گے۔',
  'event_delivery.stalled.title': 'واقعات کی ترسیل رکی ہوئی ہے',
  'event_delivery_state.ok': 'ترسیل جاری',
  'event_delivery_state.stalled': 'رکی ہوئی',
  'notification.open_record': '{{id}} کھولیں',
  'notification_area.announcement': 'اعلانات',
  'notification_area.asset': 'اثاثے',
  'notification_area.change': 'تبدیلیاں',
  'notification_area.connector': 'کنیکٹرز',
  'notification_area.incident': 'واقعات',
  'notification_area.kb_article': 'علمی ذخیرہ',
  'notification_area.mailbox': 'میل',
  'notification_area.problem': 'مسائل',
  'notification_area.problem_repeat': 'مسائل',
  'notification_area.release': 'ریلیزز',
  'notification_area.reminder': 'یاد دہانیاں',
  'notification_area.rule_step': 'قواعد اور ایسکلیشن',
  'notification_area.service_request': 'سروس کی درخواستیں',
  'notification_category.approval': 'منظوریاں',
  'notification_category.assignment': 'تفویض',
  'notification_category.conversation': 'جوابات اور نوٹس',
  'notification_category.created': 'نئے ریکارڈ',
  'notification_category.following': 'فالو کرنا',
  'notification_category.mention': 'تذکرے',
  'notification_category.status': 'حالت کی تبدیلیاں',
  'notification_category.workflow': 'ورک فلو پیغامات',
  'notification_channel.email': 'ای میل',
  'notification_channel.in_app': 'ایپ میں',
  'notification_condition_operator.in': 'ان میں سے ایک ہے',
  'notification_condition_operator.not_in': 'ان میں سے کوئی نہیں',
  'notification_event.announcement.ended': 'آپ کا فالو کردہ اعلان ختم ہوا',
  'notification_event.announcement.updated': 'آپ کا فالو کردہ اعلان اپ ڈیٹ ہوا',
  'notification_event.asset.ack_disputed': 'اثاثے کے حامل نے اعتراض کیا',
  'notification_event.asset.ack_requested': 'آپ کو اثاثہ دیا گیا: براہ کرم تصدیق کریں',
  'notification_event.asset.loan_due': 'ادھار کل واپس کرنا ہے',
  'notification_event.asset.loan_overdue': 'ادھار کی مدت گزر گئی',
  'notification_event.asset.mentioned': 'اثاثے کے نوٹ میں ذکر',
  'notification_event.asset.stock_low': 'اسٹاک کم از کم پر',
  'notification_event.asset.warranty_expiring': 'وارنٹی جلد ختم ہو رہی ہے',
  'notification_event.change.approval_fallback': 'تبدیلی کی منظوری جس کا کوئی فیصلہ کرنے والا نہیں',
  'notification_event.change.approval_requested': 'تبدیلی کی منظوری درکار',
  'notification_event.change.approved': 'تبدیلی منظور',
  'notification_event.change.assigned': 'تبدیلی آپ کے سپرد',
  'notification_event.change.backed_out': 'تبدیلی واپس لی گئی',
  'notification_event.change.board_empty': 'تبدیلی بورڈ کا کوئی رکن نہیں',
  'notification_event.change.cab_reminder': 'تبدیلی بورڈ میں آپ کے فیصلے کی منتظر',
  'notification_event.change.clarification': 'تبدیلی کو مزید معلومات درکار',
  'notification_event.change.closed': 'تبدیلی بند',
  'notification_event.change.implementation_failed': 'تبدیلی کا نفاذ ناکام',
  'notification_event.change.implementation_overdue': 'تبدیلی کا نفاذ تاخیر کا شکار',
  'notification_event.change.implemented': 'تبدیلی نافذ',
  'notification_event.change.mentioned': 'تبدیلی پر آپ کا ذکر',
  'notification_event.change.note': 'تبدیلی پر نوٹ',
  'notification_event.change.overridden': 'ہنگامی استثنا استعمال ہوا',
  'notification_event.change.public_reply': 'درخواست گزار کو جواب',
  'notification_event.change.rejected': 'تبدیلی مسترد',
  'notification_event.change.review_due': 'تبدیلی کے جائزے کا وقت',
  'notification_event.change.sent_back': 'منظور شدہ تبدیلی کو دوبارہ منظوری درکار',
  'notification_event.change.status_entered': 'تبدیلی ایک حالت میں داخل ہوئی',
  'notification_event.change.submitted': 'تبدیلی جمع ہوئی',
  'notification_event.change.window_reminder': 'تبدیلی کا وقت جلد شروع',
  'notification_event.connector.failing': 'کنیکٹر نے کام کرنا چھوڑ دیا',
  'notification_event.connector.recovered': 'کنیکٹر دوبارہ کام کر رہا ہے',
  'notification_event.incident.assigned': 'واقعہ تفویض ہوا',
  'notification_event.incident.canceled': 'واقعہ منسوخ ہوا',
  'notification_event.incident.closed': 'واقعہ بند ہوا',
  'notification_event.incident.created': 'نیا واقعہ: وصولی کی تصدیق',
  'notification_event.incident.created_in_group': 'گروپ میں نیا واقعہ',
  'notification_event.incident.follower_added': 'فالوور کے طور پر شامل',
  'notification_event.incident.mentioned': 'ذکر',
  'notification_event.incident.private_note': 'نجی نوٹ',
  'notification_event.incident.public_note': 'عوامی نوٹ',
  'notification_event.incident.public_reply': 'عوامی جواب',
  'notification_event.incident.reopened': 'واقعہ دوبارہ کھلا',
  'notification_event.incident.requester_replied': 'درخواست گزار نے جواب دیا',
  'notification_event.incident.resolved': 'واقعہ حل ہوا',
  'notification_event.incident.sla_breached': 'ایس ایل اے ہدف میں تاخیر',
  'notification_event.incident.sla_escalated': 'ایس ایل اے ایسکلیشن',
  'notification_event.incident.sla_warning': 'ایس ایل اے کی انتباہی حد آ گئی',
  'notification_event.incident.status_changed': 'حالت بدلی',
  'notification_event.incident.workflow_notice': 'ورک فلو کا پیغام',
  'notification_event.kb_article.approved': 'مضمون منظور ہوا',
  'notification_event.kb_article.rejected': 'مضمون واپس بھیجا گیا',
  'notification_event.kb_article.review_due': 'مضمون کے جائزے کا وقت',
  'notification_event.kb_article.submitted': 'مضمون جائزے کے لیے بھیجا گیا',
  'notification_event.kb_article.withdrawn': 'مضمون واپس لیا گیا',
  'notification_event.mailbox.credential_expiring':
    'میل باکس ایپ کا سیکرٹ یا سرٹیفکیٹ ختم ہونے والا ہے',
  'notification_event.mailbox.failing': 'میل باکس نے کام کرنا بند کر دیا',
  'notification_event.mailbox.mail_held': 'ایک بھیجنے والا میل باکس کو پیغامات سے بھر رہا ہے',
  'notification_event.problem.assigned': 'مسئلہ تفویض ہوا',
  'notification_event.problem.closed': 'مسئلہ بند ہوا',
  'notification_event.problem.created_in_group': 'آپ کے گروپ میں مسئلہ بنا',
  'notification_event.problem.investigator_added': 'تفتیش کار شامل ہوا',
  'notification_event.problem.known_error': 'معلوم خرابی شائع ہوئی',
  'notification_event.problem.mentioned': 'مسئلے پر ذکر',
  'notification_event.problem.note': 'مسئلے پر نوٹ',
  'notification_event.problem.resolved': 'مسئلہ حل ہوا',
  'notification_event.problem.target_breached': 'مسئلے کی ہدف تاریخ گزر گئی',
  'notification_event.problem.target_warning': 'مسئلے کی ہدف تاریخ قریب',
  'notification_event.problem_repeat.detected': 'بار بار واقعات ملے',
  'notification_event.release.public_reply': 'درخواست گزار کو جواب',
  'notification_event.reminder.due': 'آپ کی یاد دہانی',
  'notification_event.rule_step.assignee_unavailable': 'قاعدہ اپنے فرد کو تفویض نہیں کر سکا',
  'notification_event.service_request.approval_fallback': 'منتظمین کی منتظر منظوری',
  'notification_event.service_request.approval_requested': 'منظوری کی درخواست',
  'notification_event.service_request.approved': 'درخواست منظور',
  'notification_event.service_request.fulfilled': 'درخواست مکمل',
  'notification_event.service_request.public_reply': 'درخواست گزار کو جواب',
  'notification_event.service_request.ready_to_fulfil': 'درخواست تکمیل کے لیے تیار',
  'notification_event.service_request.received': 'درخواست موصول: تصدیق',
  'notification_event.service_request.rejected': 'درخواست نامنظور',
  'notification_event.service_request.withdrawn': 'درخواست واپس لی گئی',
  'notification_preferences.col.category': 'قسم',
  'notification_preferences.dnd_help':
    'کوئی پاپ اپ نہیں اور فوری و لازمی کے سوا کوئی ای میل نہیں؛ سب کچھ آپ کی اطلاعات میں پھر بھی آتا ہے۔',
  'notification_preferences.help':
    'منتخب کریں کہ آپ کو کس بارے میں اور کہاں اطلاع ملے۔ کچھ اطلاعات آپ کی تنظیم کی طرف سے لازمی ہیں۔',
  'notification_preferences.locked': 'آپ کی تنظیم کی طرف سے لازمی: اسے بند نہیں کیا جا سکتا۔',
  'notification_preferences.saved': 'ترجیحات محفوظ ہو گئیں۔',
  'notification_preferences.title': 'اطلاعات',
  'notification_reason.do_not_disturb': 'پریشان نہ کریں آن تھا',
  'notification_reason.gave_up': 'کئی کوششوں کے بعد ترسیل روک دی گئی',
  'notification_reason.mail_refused': 'میل سرور نے پیغام مسترد کر دیا',
  'notification_reason.no_access': 'وہ اب ریکارڈ نہیں دیکھ سکتے',
  'notification_reason.no_address': 'غیر فعال، یا ای میل پتہ نہیں',
  'notification_reason.preference': 'ان کی ترجیحات میں بند ہے',
  'notification_recipient.approval_administrators': 'منظوری کے منتظمین',
  'notification_recipient.approver': 'منظوری دینے والا',
  'notification_recipient.approvers': 'منظور کنندگان',
  'notification_recipient.asset_managers': 'اثاثوں کے منتظمین',
  'notification_recipient.assigned_by': 'جس نے یہ دیا',
  'notification_recipient.assignee': 'تفویض شدہ تکنیکی ماہر',
  'notification_recipient.author': 'مصنف',
  'notification_recipient.borrower': 'ادھار لینے والا',
  'notification_recipient.cab': 'تبدیلی بورڈ کے ارکان',
  'notification_recipient.cab_member': 'فیصلے کا منتظر بورڈ رکن',
  'notification_recipient.change_manager': 'تبدیلی مینیجر',
  'notification_recipient.change_owner': 'تبدیلی کا مالک',
  'notification_recipient.connector_admins': 'وہ لوگ جو یہ کنیکٹر سیٹ اپ کرتے ہیں',
  'notification_recipient.escalation_recipients': 'ایسکلیشن درجے کے وصول کنندگان',
  'notification_recipient.followers': 'فالوورز',
  'notification_recipient.group': 'گروپ کے اراکین',
  'notification_recipient.group_head': 'گروپ لیڈ اور شعبے کا سربراہ',
  'notification_recipient.holder': 'جس کے پاس یہ ہے',
  'notification_recipient.implementer': 'نافذ کنندہ',
  'notification_recipient.line_manager': 'براہِ راست مینیجر',
  'notification_recipient.linked_incident_technicians': 'منسلک واقعات کے تکنیکی ماہرین',
  'notification_recipient.loan_creator': 'جس نے ادھار دیا',
  'notification_recipient.mail_admins': 'میل باکس سنبھالنے والے افراد',
  'notification_recipient.mentioned': 'جن کا ذکر ہوا',
  'notification_recipient.new_follower': 'نیا فالوور',
  'notification_recipient.new_investigator': 'شامل کیا گیا تفتیش کار',
  'notification_recipient.on_behalf_of': 'جس کے لیے ہے',
  'notification_recipient.owner': 'مضمون کا مالک',
  'notification_recipient.previous_assignee': 'سابقہ تکنیکی ماہر',
  'notification_recipient.requester': 'درخواست گزار',
  'notification_recipient.reviewer': 'جائزہ کار',
  'notification_recipient.step_owner': 'قاعدے کا مالک (ورنہ اس کے منتظمین)',
  'notification_recipient.stock_watchers': 'کم از کم حد کے نامزد لوگ',
  'notification_recipient.topic_owner': 'موضوع کا مالک',
  'notification_recipient.workflow_audience': 'ورک فلو میں نامزد افراد',
  'notification_rules.any_priority': 'کوئی بھی ترجیح',
  'notification_rules.any_status': 'کوئی بھی حالت',
  'notification_rules.changed': '{{when}} کو تبدیل ہوا',
  'notification_rules.col.channels': 'کیسے',
  'notification_rules.col.event': 'واقعہ',
  'notification_rules.col.on': 'آن',
  'notification_rules.col.priority': 'صرف اس ترجیح کے لیے',
  'notification_rules.col.recipients': 'کون',
  'notification_rules.col.status': 'صرف اس حالت کے لیے',
  'notification_rules.intro':
    'کون سے واقعات کسے اور کیسے اطلاع دیتے ہیں۔ ہر واقعہ ایک مناسب پہلے سے طے شدہ ترتیب سے شروع ہوتا ہے؛ تبدیلیاں آڈٹ لاگ میں درج ہوتی ہیں۔',
  'notification_rules.none': 'کوئی واقعہ نہیں ملا',
  'notification_rules.required': 'لوگوں کے لیے لازمی',
  'notification_rules.reset': 'پہلے سے طے شدہ پر واپس',
  'notification_rules.saved': 'اطلاع کا قاعدہ محفوظ ہو گیا۔',
  'notification_rules.search': 'واقعات تلاش کریں',
  'notification_state.failed': 'ناکام',
  'notification_state.queued': 'بھیجی جا رہی ہے',
  'notification_state.sent': 'بھیج دی گئی',
  'notification_state.suppressed': 'نہیں بھیجی گئی',
  'notification_state.waiting': 'میل سیٹ اپ کا انتظار',
  'notification_template.announcement.ended.body':
    'السلام علیکم {{ recipient.name }}،\n\nآپ کا فالو کردہ اعلان "{{ record.title }}" ختم ہو گیا ہے۔',
  'notification_template.announcement.ended.in_app': 'ختم: {{ record.title }}',
  'notification_template.announcement.ended.subject': 'ختم: {{ record.title }}',
  'notification_template.announcement.updated.body':
    'السلام علیکم {{ recipient.name }}،\n\nآپ کا فالو کردہ اعلان "{{ record.title }}" اپ ڈیٹ ہو گیا ہے۔',
  'notification_template.announcement.updated.in_app': 'اپ ڈیٹ: {{ record.title }}',
  'notification_template.announcement.updated.subject': 'اپ ڈیٹ: {{ record.title }}',
  'notification_template.asset.ack_disputed.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ holder.name }} نے {{ record.display_id }} "{{ record.title }}" پر اعتراض کیا: {{ acknowledgement.comment }}',
  'notification_template.asset.ack_disputed.in_app':
    '{{ holder.name }} نے {{ record.display_id }} پر اعتراض کیا: {{ acknowledgement.comment }}',
  'notification_template.asset.ack_disputed.subject':
    'اعتراض: {{ record.display_id }} {{ record.title }}',
  'notification_template.asset.ack_requested.body':
    'السلام علیکم {{ recipient.name }}،\n\nآپ کو {{ record.display_id }} "{{ record.title }}" دیا گیا ہے۔ اسے قبول کرنے یا مسئلہ بتانے کے لیے میرے اثاثے کھولیں۔',
  'notification_template.asset.ack_requested.in_app':
    'براہ کرم تصدیق کریں {{ record.display_id }}: {{ record.title }}',
  'notification_template.asset.ack_requested.subject':
    'براہ کرم {{ record.display_id }} {{ record.title }} کی تصدیق کریں',
  'notification_template.asset.loan_due.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ holder.name }} کو ادھار دیے گئے اثاثے کل واپس کرنے ہیں۔',
  'notification_template.asset.loan_due.in_app': '{{ holder.name }} کا ادھار کل واپس کرنا ہے',
  'notification_template.asset.loan_due.subject': 'ادھار اثاثے کل واپس کرنے ہیں',
  'notification_template.asset.loan_overdue.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ holder.name }} کو ادھار دیے گئے اثاثوں کی واپسی کا وقت گزر گیا اور وہ ابھی واپس نہیں آئے۔',
  'notification_template.asset.loan_overdue.in_app': '{{ holder.name }} کے ادھار کی مدت گزر گئی',
  'notification_template.asset.loan_overdue.subject': 'ادھار اثاثوں کی مدت گزر گئی',
  'notification_template.asset.mentioned.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" کے ایک نوٹ میں آپ کا ذکر کیا۔',
  'notification_template.asset.mentioned.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر آپ کا ذکر کیا',
  'notification_template.asset.mentioned.subject':
    '{{ record.display_id }} پر آپ کا ذکر ہوا: {{ record.title }}',
  'notification_template.asset.stock_low.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.title }} کا اسٹاک {{ stock.quantity }} تک گر گیا ہے، جو اس کی کم از کم حد {{ stock.minimum }} کے برابر یا اس سے کم ہے۔',
  'notification_template.asset.stock_low.in_app':
    '{{ record.title }} {{ stock.quantity }} تک رہ گیا (کم از کم {{ stock.minimum }})',
  'notification_template.asset.stock_low.subject': '{{ record.title }} کم از کم اسٹاک پر ہے',
  'notification_template.asset.warranty_expiring.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کی وارنٹی {{ warranty.ends_on }} کو ختم ہو رہی ہے۔',
  'notification_template.asset.warranty_expiring.in_app':
    '{{ record.display_id }} کی وارنٹی {{ warranty.ends_on }} کو ختم',
  'notification_template.asset.warranty_expiring.subject':
    'وارنٹی ختم ہو رہی ہے: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.approval_fallback.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کی ایک منظوری کسی کے پاس نہیں۔ منظوری کا منتظم اس کا فیصلہ کر سکتا ہے۔',
  'notification_template.change.approval_fallback.in_app':
    '{{ record.display_id }} کی ایک منظوری کا کوئی منظور کنندہ نہیں: {{ record.title }}',
  'notification_template.change.approval_fallback.subject':
    'کوئی منظور کنندہ نہیں: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.approval_requested.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" آپ کی منظوری کی منتظر ہے۔\n\nمنظور یا مسترد کریں: {{ approval_link }}\n\nیہ لنک صرف ایک بار، صرف آپ کے لیے کام کرتا ہے۔',
  'notification_template.change.approval_requested.in_app':
    '{{ record.display_id }} آپ کی منظوری کی منتظر ہے: {{ record.title }}',
  'notification_template.change.approval_requested.subject':
    'آپ کی منظوری: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.approved.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" منظور ہو گئی۔ اب اس کی حالت: {{ record.status }}۔',
  'notification_template.change.approved.in_app':
    '{{ record.display_id }} منظور ہوئی: {{ record.title }}',
  'notification_template.change.approved.subject':
    'منظور: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.assigned.body':
    'السلام علیکم {{ recipient.name }}،\n\nاب آپ {{ record.display_id }} "{{ record.title }}" کے مالک ہیں۔',
  'notification_template.change.assigned.in_app':
    'آپ {{ record.display_id }} کے مالک ہیں: {{ record.title }}',
  'notification_template.change.assigned.subject':
    'آپ {{ record.display_id }} {{ record.title }} کے مالک ہیں',
  'notification_template.change.backed_out.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" واپس لے لی گئی۔ اب اس کی حالت: {{ record.status }}۔',
  'notification_template.change.backed_out.in_app':
    '{{ record.display_id }} واپس لی گئی: {{ record.title }}',
  'notification_template.change.backed_out.subject':
    'واپس لی گئی: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.board_empty.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" ایسے تبدیلی بورڈ کی منتظر ہے جس کا کوئی رکن نہیں۔ بورڈ میں ارکان شامل کریں یا کوئی اور بورڈ چنیں۔',
  'notification_template.change.board_empty.in_app':
    '{{ record.display_id }} ایسے بورڈ کی منتظر ہے جس کا کوئی رکن نہیں: {{ record.title }}',
  'notification_template.change.board_empty.subject':
    'بورڈ بغیر ارکان: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.cab_reminder.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" {{ window.start }} پر شروع ہوگی اور ابھی تک آپ کے فیصلے کی منتظر ہے۔\n\nمنظور یا مسترد کریں: {{ approval_link }}',
  'notification_template.change.cab_reminder.in_app':
    '{{ record.display_id }} {{ window.start }} پر شروع ہوگی اور آپ کی منتظر ہے: {{ record.title }}',
  'notification_template.change.cab_reminder.subject':
    'آپ کا فیصلہ، جلد شروع: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.clarification.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کو آگے بڑھنے سے پہلے مزید معلومات درکار ہیں۔ کیا مانگا گیا ہے، دیکھنے کے لیے اسے کھولیں۔',
  'notification_template.change.clarification.in_app':
    '{{ record.display_id }} کو مزید معلومات درکار ہیں: {{ record.title }}',
  'notification_template.change.clarification.subject':
    'مزید معلومات درکار: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.closed.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" بند ہو گئی۔',
  'notification_template.change.closed.in_app':
    '{{ record.display_id }} بند ہوئی: {{ record.title }}',
  'notification_template.change.closed.subject': 'بند: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.implementation_failed.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کا نفاذ ناکام ہو گیا۔ اب اس کی حالت: {{ record.status }}۔',
  'notification_template.change.implementation_failed.in_app':
    '{{ record.display_id }} کا نفاذ ناکام ہوا: {{ record.title }}',
  'notification_template.change.implementation_failed.subject':
    'نفاذ ناکام: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.implementation_overdue.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کے نفاذ کا وقت ختم ہو گیا، اور تبدیلی ابھی نافذ نہیں ہوئی۔',
  'notification_template.change.implementation_overdue.in_app':
    '{{ record.display_id }} کا وقت ختم ہو گیا اور یہ نافذ نہیں ہوئی: {{ record.title }}',
  'notification_template.change.implementation_overdue.subject':
    'نفاذ میں تاخیر: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.implemented.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" نافذ ہو گئی۔ اب اس کی حالت: {{ record.status }}۔',
  'notification_template.change.implemented.in_app':
    '{{ record.display_id }} نافذ ہوئی: {{ record.title }}',
  'notification_template.change.implemented.subject':
    'نافذ: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.mentioned.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر آپ کا ذکر کیا:\n\n{{ conversation.excerpt }}',
  'notification_template.change.mentioned.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر آپ کا ذکر کیا',
  'notification_template.change.mentioned.subject':
    '{{ record.display_id }} {{ record.title }} پر آپ کا ذکر ہوا',
  'notification_template.change.note.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر نوٹ لکھا:\n\n{{ conversation.excerpt }}',
  'notification_template.change.note.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر نوٹ لکھا',
  'notification_template.change.note.subject':
    'نیا نوٹ: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.overridden.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" پر ہنگامی استثنا استعمال ہوا۔ اب اس کا جائزہ لازمی ہے۔',
  'notification_template.change.overridden.in_app':
    '{{ record.display_id }} پر ہنگامی استثنا استعمال ہوا: {{ record.title }}',
  'notification_template.change.overridden.subject':
    'ہنگامی استثنا: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.public_reply.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر جواب دیا:\n\n{{ conversation.excerpt }}',
  'notification_template.change.public_reply.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر جواب دیا',
  'notification_template.change.public_reply.subject':
    '{{ record.display_id }} پر نیا جواب: {{ record.title }}',
  'notification_template.change.rejected.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" مسترد ہو گئی۔ اب اس کی حالت: {{ record.status }}۔',
  'notification_template.change.rejected.in_app':
    '{{ record.display_id }} مسترد ہوئی: {{ record.title }}',
  'notification_template.change.rejected.subject':
    'مسترد: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.review_due.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کے نفاذ کے بعد کے جائزے کا وقت آ گیا ہے۔',
  'notification_template.change.review_due.in_app':
    '{{ record.display_id }} کے جائزے کا وقت آ گیا: {{ record.title }}',
  'notification_template.change.review_due.subject':
    'جائزے کا وقت: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.sent_back.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" منظوری کے بعد بدل گئی، اس لیے اسے دوبارہ منظوری درکار ہے۔',
  'notification_template.change.sent_back.in_app':
    '{{ record.display_id }} کو دوبارہ منظوری درکار ہے: {{ record.title }}',
  'notification_template.change.sent_back.subject':
    'دوبارہ منظوری درکار: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.status_entered.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کی حالت اب: {{ record.status }}۔',
  'notification_template.change.status_entered.in_app':
    '{{ record.display_id }} اب {{ record.status }} ہے: {{ record.title }}',
  'notification_template.change.status_entered.subject':
    '{{ record.status }}: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.submitted.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" جمع ہوئی اور تبدیلی مینیجر کی منتظر ہے۔',
  'notification_template.change.submitted.in_app':
    '{{ record.display_id }} جمع ہوئی: {{ record.title }}',
  'notification_template.change.submitted.subject':
    'جمع شدہ: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.window_reminder.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کے نفاذ کا وقت {{ window.start }} پر شروع ہوتا ہے۔',
  'notification_template.change.window_reminder.in_app':
    '{{ record.display_id }} {{ window.start }} پر شروع ہوگی: {{ record.title }}',
  'notification_template.change.window_reminder.subject':
    'جلد شروع: {{ record.display_id }} {{ record.title }}',
  'notification_template.connector.failing.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.title }} نے کام کرنا چھوڑ دیا: {{ connector.reason }}۔\n\nآپ کو ہر کوشش پر نہیں بلکہ ایک بار بتایا جائے گا، اور دوبارہ جب یہ کام کرنے لگے۔ اسے دیکھنے کے لیے ایڈمن › انٹیگریشنز کھولیں۔',
  'notification_template.connector.failing.in_app':
    '{{ record.title }} نے کام کرنا چھوڑ دیا: {{ connector.reason }}',
  'notification_template.connector.failing.subject': '{{ record.title }} نے کام کرنا چھوڑ دیا',
  'notification_template.connector.recovered.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.title }} دوبارہ کام کر رہا ہے۔ مزید کچھ کرنے کی ضرورت نہیں۔',
  'notification_template.connector.recovered.in_app': '{{ record.title }} دوبارہ کام کر رہا ہے',
  'notification_template.connector.recovered.subject': '{{ record.title }} دوبارہ کام کر رہا ہے',
  'notification_template.incident.assigned.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اب {{ assignee.name }} کو تفویض ہے۔\n\nترجیح: {{ record.priority }}\nحالت: {{ record.status }}\nدرخواست گزار: {{ requester.name }}',
  'notification_template.incident.assigned.in_app':
    '{{ record.display_id }} {{ assignee.name }} کو تفویض ہوا: {{ record.title }}',
  'notification_template.incident.assigned.subject':
    '{{ assignee.name }} کو تفویض: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.canceled.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" منسوخ کر دیا گیا۔',
  'notification_template.incident.canceled.in_app': '{{ record.display_id }} منسوخ ہو گیا',
  'notification_template.incident.canceled.subject':
    'منسوخ: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.closed.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اب بند ہے۔',
  'notification_template.incident.closed.in_app': '{{ record.display_id }} بند ہو گیا',
  'notification_template.incident.closed.subject':
    'بند: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.created.body':
    'السلام علیکم {{ recipient.name }}،\n\nہمیں آپ کی درخواست "{{ record.title }}" موصول ہوئی اور اسے {{ record.display_id }} کے طور پر درج کر لیا گیا ہے۔ ہم آپ کو باخبر رکھیں گے۔',
  'notification_template.incident.created.in_app':
    'ہمیں {{ record.display_id }} موصول ہوا: {{ record.title }}',
  'notification_template.incident.created.subject':
    'آپ کی درخواست {{ record.display_id }} موصول ہوئی: {{ record.title }}',
  'notification_template.incident.created_in_group.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" آپ کے گروپ میں آیا ہے۔\n\nترجیح: {{ record.priority }}\nدرخواست گزار: {{ requester.name }}',
  'notification_template.incident.created_in_group.in_app':
    'آپ کے گروپ میں نیا: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.created_in_group.subject':
    'نیا واقعہ {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.follower_added.body':
    'السلام علیکم {{ recipient.name }}،\n\nآپ اب {{ record.display_id }} "{{ record.title }}" کو فالو کرتے ہیں اور اس کی تازہ کاریوں سے باخبر رہیں گے۔',
  'notification_template.incident.follower_added.in_app':
    'آپ اب {{ record.display_id }} کو فالو کرتے ہیں: {{ record.title }}',
  'notification_template.incident.follower_added.subject':
    'آپ اب {{ record.display_id }} کو فالو کرتے ہیں: {{ record.title }}',
  'notification_template.incident.mentioned.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر آپ کا ذکر کیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.mentioned.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر آپ کا ذکر کیا',
  'notification_template.incident.mentioned.subject':
    '{{ record.display_id }} پر آپ کا ذکر ہوا: {{ record.title }}',
  'notification_template.incident.private_note.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر نجی نوٹ شامل کیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.private_note.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر نجی نوٹ شامل کیا',
  'notification_template.incident.private_note.subject':
    '{{ record.display_id }} پر نجی نوٹ: {{ record.title }}',
  'notification_template.incident.public_note.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر نوٹ شامل کیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.public_note.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر نوٹ شامل کیا',
  'notification_template.incident.public_note.subject':
    '{{ record.display_id }} پر نیا نوٹ: {{ record.title }}',
  'notification_template.incident.public_reply.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر جواب دیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.public_reply.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر جواب دیا',
  'notification_template.incident.public_reply.subject':
    '{{ record.display_id }} پر نیا جواب: {{ record.title }}',
  'notification_template.incident.reopened.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" دوبارہ کھل گیا ہے اور پھر توجہ چاہتا ہے۔\n\nحالت: {{ record.status }}',
  'notification_template.incident.reopened.in_app': '{{ record.display_id }} دوبارہ کھل گیا',
  'notification_template.incident.reopened.subject':
    'دوبارہ کھلا: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.requester_replied.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر جواب دیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.requester_replied.in_app':
    'درخواست گزار {{ conversation.author }} نے {{ record.display_id }} پر جواب دیا',
  'notification_template.incident.requester_replied.subject':
    'درخواست گزار نے {{ record.display_id }} پر جواب دیا: {{ record.title }}',
  'notification_template.incident.resolved.body':
    'السلام علیکم {{ recipient.name }}،\n\nہم نے {{ record.display_id }} "{{ record.title }}" حل کر دیا ہے۔ اگر مسئلہ اب بھی موجود ہے تو جواب دے کر ہمیں بتائیں۔',
  'notification_template.incident.resolved.in_app': '{{ record.display_id }} حل ہو گیا',
  'notification_template.incident.resolved.subject':
    'حل ہو گیا: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_breached.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اپنے {{ sla.target }} ہدف کا وقت گزار چکا ہے۔',
  'notification_template.incident.sla_breached.in_app':
    '{{ record.display_id }}: {{ sla.target }} میں تاخیر ہو گئی',
  'notification_template.incident.sla_breached.subject':
    'تاخیر: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_escalated.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اس کے {{ sla.target }} ایس ایل اے کے تحت آپ کو ایسکلیٹ کیا گیا ہے۔',
  'notification_template.incident.sla_escalated.in_app':
    'آپ کو ایسکلیٹ کیا گیا: {{ record.display_id }} ({{ sla.target }})',
  'notification_template.incident.sla_escalated.subject':
    'ایسکلیشن: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_warning.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اپنے {{ sla.target }} ہدف کی انتباہی حد تک پہنچ گیا ہے۔',
  'notification_template.incident.sla_warning.in_app':
    '{{ record.display_id }}: {{ sla.target }} کا وقت قریب ہے',
  'notification_template.incident.sla_warning.subject':
    'جلد واجب: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.status_changed.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کی حالت {{ change.from_status }} سے {{ record.status }} ہو گئی۔',
  'notification_template.incident.status_changed.in_app':
    '{{ record.display_id }} اب {{ record.status }} ہے',
  'notification_template.incident.status_changed.subject':
    '{{ record.display_id }} اب {{ record.status }} ہے: {{ record.title }}',
  'notification_template.incident.workflow_notice.body': '{{ notice.body }}',
  'notification_template.incident.workflow_notice.in_app': '{{ notice.subject }}',
  'notification_template.incident.workflow_notice.subject': '{{ notice.subject }}',
  'notification_template.kb_article.approved.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ actor.name }} نے مضمون {{ record.display_id }} "{{ record.title }}" منظور کر دیا۔ اب اس کے قارئین اسے دیکھ سکتے ہیں۔',
  'notification_template.kb_article.approved.in_app':
    '{{ record.display_id }} شائع ہو گیا: {{ record.title }}',
  'notification_template.kb_article.approved.subject':
    'شائع شدہ: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.rejected.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ actor.name }} نے مضمون {{ record.display_id }} "{{ record.title }}" مسودے کے طور پر واپس بھیج دیا۔\n\nوجہ: {{ article.reason }}',
  'notification_template.kb_article.rejected.in_app':
    '{{ record.display_id }} واپس بھیجا گیا: {{ article.reason }}',
  'notification_template.kb_article.rejected.subject':
    'واپس بھیجا گیا: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.review_due.body':
    'السلام علیکم {{ recipient.name }}،\n\nمضمون {{ record.display_id }} "{{ record.title }}" کا جائزہ {{ article.review_on }} کو ہونا تھا۔ دیکھیں کہ یہ اب بھی درست ہے، یا اس میں ترمیم کریں۔',
  'notification_template.kb_article.review_due.in_app':
    '{{ record.display_id }} کے جائزے کا وقت ہے: {{ record.title }}',
  'notification_template.kb_article.review_due.subject':
    'جائزے کا وقت: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.submitted.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ actor.name }} نے مضمون {{ record.display_id }} "{{ record.title }}" جائزے کے لیے بھیجا ہے۔ اسے کھول کر منظور کریں یا واپس بھیجیں۔',
  'notification_template.kb_article.submitted.in_app':
    '{{ actor.name }} نے {{ record.display_id }} جائزے کے لیے بھیجا: {{ record.title }}',
  'notification_template.kb_article.submitted.subject':
    'جائزہ درکار: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.withdrawn.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ actor.name }} نے مضمون {{ record.display_id }} "{{ record.title }}" واپس لے لیا۔ قارئین اب اسے نہیں دیکھ سکتے۔\n\nوجہ: {{ article.reason }}',
  'notification_template.kb_article.withdrawn.in_app':
    '{{ record.display_id }} واپس لیا گیا: {{ article.reason }}',
  'notification_template.kb_article.withdrawn.subject':
    'واپس لیا گیا: {{ record.display_id }} {{ record.title }}',
  'notification_template.mailbox.credential_expiring.body':
    'السلام علیکم {{ recipient.name }}،\n\nجو سیکرٹ یا سرٹیفکیٹ SupportX {{ record.title }} پڑھنے کے لیے استعمال کرتا ہے، وہ {{ mailbox.expires_at }} کو ختم ہو رہا ہے۔ اپنے Microsoft یا Google ایڈمن کنسول میں نیا بنائیں، پھر ایڈمن › میل میں درج کریں تاکہ میل آتی رہے۔',
  'notification_template.mailbox.credential_expiring.in_app':
    '{{ record.title }} کی ایپ کا سیکرٹ یا سرٹیفکیٹ {{ mailbox.expires_at }} کو ختم ہو رہا ہے',
  'notification_template.mailbox.credential_expiring.subject':
    'میل باکس {{ record.title }}: ایپ کی اسناد جلد ختم ہو رہی ہیں',
  'notification_template.mailbox.failing.body':
    'السلام علیکم {{ recipient.name }}،\n\nSupportX {{ record.title }} نہیں پڑھ سکتا: {{ mailbox.reason }}۔\n\nجب تک یہ ٹھیک نہ ہو، میل سرور پر انتظار کرتی ہے۔ میل باکس دیکھنے کے لیے ایڈمن › میل کھولیں۔',
  'notification_template.mailbox.failing.in_app':
    '{{ record.title }} نے کام کرنا بند کر دیا: {{ mailbox.reason }}',
  'notification_template.mailbox.failing.subject':
    'میل باکس {{ record.title }} نے کام کرنا بند کر دیا',
  'notification_template.mailbox.mail_held.body':
    'السلام علیکم {{ recipient.name }}،\n\nایک بھیجنے والے نے {{ record.title }} پر ایک گھنٹے میں 10 سے زیادہ پیغامات بھیجے، جوابات سمیت۔ SupportX ریکارڈ بنانے کے بجائے ان کی مزید میل روک لیتا ہے، اس لیے کچھ ضائع نہیں ہوتا اور کوئی لوپ نہیں چلتا۔\n\nایڈمن › میل کھولیں، روکے گئے پیغامات کا جائزہ لیں، اور انہیں دوبارہ داخل کریں یا رد کریں۔',
  'notification_template.mailbox.mail_held.in_app':
    '{{ record.title }} کی میل جائزے کے لیے روکی گئی: ایک بھیجنے والے نے ایک گھنٹے میں 10 سے زیادہ پیغامات بھیجے',
  'notification_template.mailbox.mail_held.subject':
    'میل باکس {{ record.title }}: میل جائزے کے لیے روکی گئی',
  'notification_template.problem.assigned.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اب {{ assignee.name }} کو تفویض ہے۔\n\nترجیح: {{ record.priority }}\nحالت: {{ record.status }}',
  'notification_template.problem.assigned.in_app':
    '{{ record.display_id }} {{ assignee.name }} کو تفویض: {{ record.title }}',
  'notification_template.problem.assigned.subject':
    '{{ assignee.name }} کو تفویض: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.closed.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" بند کر دیا گیا۔',
  'notification_template.problem.closed.in_app': '{{ record.display_id }} بند ہو گیا',
  'notification_template.problem.closed.subject': 'بند: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.created_in_group.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" آپ کے گروپ میں بنایا گیا۔',
  'notification_template.problem.created_in_group.in_app':
    'نیا مسئلہ: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.created_in_group.subject':
    'آپ کے گروپ میں نیا مسئلہ: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.investigator_added.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ actor.name }} نے آپ کو {{ record.display_id }} "{{ record.title }}" پر تفتیش کار کے طور پر شامل کیا۔ آپ اس کے کام اور ورک لاگ دیکھ سکتے ہیں۔',
  'notification_template.problem.investigator_added.in_app':
    'آپ {{ record.display_id }} کی تفتیش کر رہے ہیں: {{ record.title }}',
  'notification_template.problem.investigator_added.subject':
    'آپ {{ record.display_id }} {{ record.title }} کی تفتیش کر رہے ہیں',
  'notification_template.problem.known_error.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اب ایک معلوم خرابی ہے۔ اس کا عارضی حل آپ کے واقعات پر لگایا جا سکتا ہے۔',
  'notification_template.problem.known_error.in_app':
    '{{ record.display_id }} معلوم خرابی ہے: اس کا عارضی حل لگائیں',
  'notification_template.problem.known_error.subject':
    'معلوم خرابی: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.mentioned.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر آپ کا ذکر کیا:\n\n{{ conversation.excerpt }}',
  'notification_template.problem.mentioned.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر آپ کا ذکر کیا',
  'notification_template.problem.mentioned.subject':
    '{{ conversation.author }} نے {{ record.display_id }} {{ record.title }} پر آپ کا ذکر کیا',
  'notification_template.problem.note.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر لکھا:\n\n{{ conversation.excerpt }}',
  'notification_template.problem.note.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر لکھا',
  'notification_template.problem.note.subject':
    '{{ record.display_id }} {{ record.title }} پر نیا نوٹ',
  'notification_template.problem.resolved.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" حل ہو گیا۔ اس سے ہونے والے واقعات دیکھیں اور انہیں حل کریں۔',
  'notification_template.problem.resolved.in_app':
    '{{ record.display_id }} حل ہو گیا: {{ record.title }}',
  'notification_template.problem.resolved.subject':
    'حل ہوا: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.target_breached.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اپنی {{ sla.target }} ہدف تاریخ سے آگے نکل گیا۔',
  'notification_template.problem.target_breached.in_app':
    '{{ record.display_id }} ہدف تاریخ سے آگے ہے',
  'notification_template.problem.target_breached.subject':
    'تاخیر شدہ: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.target_warning.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اپنی {{ sla.target }} ہدف تاریخ کے قریب ہے۔',
  'notification_template.problem.target_warning.in_app':
    '{{ record.display_id }}: ہدف تاریخ قریب ہے',
  'notification_template.problem.target_warning.subject':
    'جلد واجب: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem_repeat.detected.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ incident.count }} واقعات "{{ rule.name }}" سے ملتے ہیں ({{ category.name }}، {{ site.name }})۔ انہیں دیکھیں اور اگر ان کی وجہ ایک ہو تو مسئلہ بنائیں۔',
  'notification_template.problem_repeat.detected.in_app':
    '{{ incident.count }} ملتے جلتے واقعات: {{ rule.name }}',
  'notification_template.problem_repeat.detected.subject':
    '{{ incident.count }} ملتے جلتے واقعات: {{ rule.name }}',
  'notification_template.release.public_reply.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر جواب دیا:\n\n{{ conversation.excerpt }}',
  'notification_template.release.public_reply.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر جواب دیا',
  'notification_template.release.public_reply.subject':
    '{{ record.display_id }} پر نیا جواب: {{ record.title }}',
  'notification_template.reminder.due.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" پر آپ کی یاد دہانی {{ reminder.at }} پر ہے:\n\n{{ reminder.note }}',
  'notification_template.reminder.due.in_app':
    '{{ reminder.at }} پر یاد دہانی: {{ reminder.note }}',
  'notification_template.reminder.due.subject':
    'یاد دہانی: {{ reminder.note }} ({{ record.display_id }})',
  'notification_template.rule_step.assignee_unavailable.body':
    'السلام علیکم {{ recipient.name }}،\n\nایک قاعدے یا ایسکلیشن کو {{ record.display_id }} "{{ record.title }}" کو {{ unavailable.person }} کے سپرد کرنا تھا، جو {{ unavailable.reason }}۔ یہ کسی کو تفویض کیے بغیر گروپ میں چلا گیا۔ براہ کرم کسی کو تفویض کریں یا قاعدہ بدلیں۔',
  'notification_template.rule_step.assignee_unavailable.in_app':
    '{{ record.display_id }} کسی کو تفویض کیے بغیر اپنے گروپ میں چلا گیا: {{ unavailable.person }} {{ unavailable.reason }}',
  'notification_template.rule_step.assignee_unavailable.subject':
    'کسی کو تفویض نہیں: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.approval_fallback.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} «{{ record.title }}» کا کوئی فعال منظوری دہندہ نہیں، اس لیے یہ منظوری کے منتظم کا منتظر ہے۔',
  'notification_template.service_request.approval_fallback.in_app':
    '{{ record.display_id }} کا کوئی فعال منظوری دہندہ نہیں، یہ منظوری کے منتظم کا منتظر ہے: {{ record.title }}',
  'notification_template.service_request.approval_fallback.subject':
    'منظوری منتظر: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.approval_requested.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ requester.name }} نے {{ record.display_id }} «{{ record.title }}» کی درخواست کی ہے، اور یہ آپ کی منظوری کی منتظر ہے۔\n\nمنظور یا مسترد کریں: {{ approval_link }}\n\nیہ لنک سائن ان کے بعد صرف آپ کے لیے، ایک بار کام کرتا ہے۔',
  'notification_template.service_request.approval_requested.in_app':
    '{{ record.display_id }} آپ کی منظوری کا منتظر ہے: {{ record.title }}',
  'notification_template.service_request.approval_requested.subject':
    'آپ کی منظوری: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.approved.body':
    'السلام علیکم {{ recipient.name }}،\n\nآپ کی درخواست {{ record.display_id }} «{{ record.title }}» منظور ہو گئی۔ ہم اب اس پر کام کر رہے ہیں۔',
  'notification_template.service_request.approved.in_app':
    '{{ record.display_id }} منظور ہو گئی: {{ record.title }}',
  'notification_template.service_request.approved.subject':
    'منظور: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.fulfilled.body':
    'السلام علیکم {{ recipient.name }}،\n\nآپ کی درخواست {{ record.display_id }} «{{ record.title }}» مکمل ہو گئی۔ براہ کرم تصدیق کریں کہ آپ کو مل گئی، یا بتائیں اگر کچھ رہ گیا ہو۔',
  'notification_template.service_request.fulfilled.in_app':
    '{{ record.display_id }} مکمل ہو گئی: {{ record.title }}',
  'notification_template.service_request.fulfilled.subject':
    'مکمل: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.public_reply.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر جواب دیا:\n\n{{ conversation.excerpt }}',
  'notification_template.service_request.public_reply.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر جواب دیا',
  'notification_template.service_request.public_reply.subject':
    '{{ record.display_id }} پر نیا جواب: {{ record.title }}',
  'notification_template.service_request.ready_to_fulfil.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} «{{ record.title }}» کے سب کام ہو گئے، مگر یہ کسی کو تفویض نہیں۔ اپنے گروپ کے کسی فرد کو تفویض کریں تاکہ وہ اسے مکمل کرے۔',
  'notification_template.service_request.ready_to_fulfil.in_app':
    '{{ record.display_id }} تکمیل کے لیے تیار ہے: کسی کو تفویض کریں',
  'notification_template.service_request.ready_to_fulfil.subject':
    'تکمیل کے لیے تیار: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.received.body':
    'السلام علیکم {{ recipient.name }}،\n\nہمیں آپ کی درخواست «{{ record.title }}» موصول ہوئی اور اسے {{ record.display_id }} کے طور پر درج کر لیا گیا۔ ہم آپ کو باخبر رکھیں گے۔',
  'notification_template.service_request.received.in_app':
    '{{ record.display_id }} موصول ہوئی: {{ record.title }}',
  'notification_template.service_request.received.subject':
    'آپ کی درخواست {{ record.display_id }} موصول ہوئی: {{ record.title }}',
  'notification_template.service_request.rejected.body':
    'السلام علیکم {{ recipient.name }}،\n\nآپ کی درخواست {{ record.display_id }} «{{ record.title }}» منظور نہیں ہوئی۔{% if approval.comment %}\n\nمنظوری دینے والے نے کہا: {{ approval.comment }}{% endif %}',
  'notification_template.service_request.rejected.in_app':
    '{{ record.display_id }} منظور نہیں ہوئی: {{ record.title }}',
  'notification_template.service_request.rejected.subject':
    'نامنظور: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.withdrawn.body':
    'السلام علیکم {{ recipient.name }}،\n\nآپ کی درخواست {{ record.display_id }} «{{ record.title }}» واپس لے لی گئی۔ اس پر مزید کچھ نہیں ہوگا۔',
  'notification_template.service_request.withdrawn.in_app':
    '{{ record.display_id }} واپس لی گئی: {{ record.title }}',
  'notification_template.service_request.withdrawn.subject':
    'واپس لی گئی: {{ record.display_id }} {{ record.title }}',
  'notification_variable.acknowledgement.comment': 'تصدیق › تبصرہ',
  'notification_variable.actor.name': 'تبدیل کنندہ › نام',
  'notification_variable.approval.comment': 'منظوری دینے والے کا تبصرہ',
  'notification_variable.approval_link': 'منظوری › لنک',
  'notification_variable.article.reason': 'مضمون › وجہ',
  'notification_variable.article.review_on': 'مضمون › جائزے کی تاریخ',
  'notification_variable.assignee.name': 'تکنیکی ماہر › نام',
  'notification_variable.category.name': 'زمرہ',
  'notification_variable.change.from_status': 'تبدیلی › سابقہ حالت',
  'notification_variable.connector.name': 'کنیکٹر › نام',
  'notification_variable.connector.reason': 'کنیکٹر › وجہ',
  'notification_variable.conversation.author': 'جواب یا نوٹ › مصنف',
  'notification_variable.conversation.excerpt': 'جواب یا نوٹ › متن',
  'notification_variable.holder.name': 'حامل › نام',
  'notification_variable.incident.count': 'واقعات کی تعداد',
  'notification_variable.mailbox.address': 'میل باکس › پتہ',
  'notification_variable.mailbox.expires_at': 'میل باکس › اسناد کی میعاد',
  'notification_variable.mailbox.reason': 'میل باکس › وجہ',
  'notification_variable.notice.body': 'پیغام › متن',
  'notification_variable.notice.subject': 'پیغام › موضوع',
  'notification_variable.recipient.name': 'وصول کنندہ › نام',
  'notification_variable.record.display_id': 'ریکارڈ › شناخت',
  'notification_variable.record.link': 'ریکارڈ › لنک',
  'notification_variable.record.priority': 'ریکارڈ › ترجیح',
  'notification_variable.record.status': 'ریکارڈ › حالت',
  'notification_variable.record.title': 'ریکارڈ › موضوع',
  'notification_variable.reminder.at': 'یاد دہانی کا وقت',
  'notification_variable.reminder.note': 'یاد دہانی کا نوٹ',
  'notification_variable.requester.name': 'درخواست گزار › نام',
  'notification_variable.rule.name': 'اصول',
  'notification_variable.site.name': 'مقام',
  'notification_variable.sla.target': 'ایس ایل اے › ہدف',
  'notification_variable.stock.minimum': 'اسٹاک › کم از کم',
  'notification_variable.stock.quantity': 'اسٹاک › مقدار',
  'notification_variable.unavailable.person': 'غیر تفویض › فرد',
  'notification_variable.unavailable.reason': 'غیر تفویض › وجہ',
  'notification_variable.warranty.ends_on': 'وارنٹی › ختم ہونے کی تاریخ',
  'notification_variable.window.start': 'وقت کا آغاز',
  'notifications.banner.no_mail_one':
    '{{count}} ای میل انتظار میں ہے کیونکہ باہر جانے والی میل سیٹ نہیں ہے۔ ایپ میں اطلاعات جاری ہیں؛ میل چلنے پر ای میل بھیج دی جائے گی۔',
  'notifications.banner.no_mail_other':
    '{{count}} ای میلز انتظار میں ہیں کیونکہ باہر جانے والی میل سیٹ نہیں ہے۔ ایپ میں اطلاعات جاری ہیں؛ میل چلنے پر ای میلز بھیج دی جائیں گی۔',
  'notifications.banner.sending_one': 'انتظار میں موجود {{count}} ای میل اب بھیجی جا رہی ہے۔',
  'notifications.banner.sending_other': 'انتظار میں موجود {{count}} ای میلز اب بھیجی جا رہی ہیں۔',
  'notifications.banner.title': 'ای میل اطلاعات انتظار میں ہیں',
  'notifications.do_not_disturb': 'پریشان نہ کریں',
  'notifications.empty': 'ابھی کوئی اطلاع نہیں۔',
  'notifications.more': 'پرانی دکھائیں',
  'notifications.open_one': 'اطلاعات، {{count}} نہ پڑھی ہوئی',
  'notifications.open_other': 'اطلاعات، {{count}} نہ پڑھی ہوئی',
  'notifications.read_all': 'سب کو پڑھا ہوا نشان زد کریں',
  'notifications.title': 'اطلاعات',
};
