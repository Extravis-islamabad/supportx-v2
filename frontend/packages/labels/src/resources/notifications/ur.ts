import type { LabelResource } from '../en';

// notifications labels (see ../README.md).
export const ur: LabelResource = {
  'delivery_reason.email_channel_not_configured': 'ای میل چینل ترتیب نہیں دیا گیا',
  'delivery_state.received': 'موصول',
  'delivery_state.not_sent': 'نہیں بھیجا گیا',
  'delivery_state.queued': 'بھیجا جا رہا ہے',
  'delivery_state.sent': 'بھیج دیا گیا',
  'delivery_state.failed': 'بھیجنا ناکام ہوا',
  'delivery_state.waiting': 'میل ترتیب دیے جانے کا انتظار',
  'delivery_state.retrying': 'دوبارہ کوشش جاری',
  'delivery_reason.mail_not_configured': 'باہر جانے والی میل ترتیب نہیں دی گئی',
  'delivery_reason.not_sent_in_time': 'نہیں بھیجا گیا: 7 دن میں میل ترتیب نہیں دی گئی',
  'delivery_reason.no_address': 'درخواست گزار کا کوئی ای میل پتہ نہیں',
  'delivery_reason.mail_refused': 'پیغام لکھے گئے انداز میں نہیں بھیجا جا سکا',
  'delivery_reason.not_notified': 'درخواست گزار کو اس بارے میں ای میل نہیں جاتی',
  'delivery_reason.recipient_refused': 'وصول کنندہ کے میل سرور نے پتہ رد کر دیا',
  'delivery_reason.recipient_deferred': 'وصول کنندہ کے میل سرور نے بعد میں کوشش کرنے کو کہا',
  'delivery_reason.message_refused': 'میل سرور نے پیغام رد کر دیا',
  'delivery_reason.authentication_failed': 'میل سرور نے SupportX کا سائن اِن رد کر دیا',
  'delivery_reason.server_unavailable': 'میل سرور تک رسائی نہیں ہو سکی',
  'delivery_reason.server_busy': 'میل سرور مصروف تھا',
  'delivery_reason.gave_up': 'ہر کوشش کے بعد بھی ناکام',
  'notification_recipient.approvers': 'منظور کنندگان',
  'notification_recipient.author': 'مصنف',
  'notification_recipient.owner': 'مضمون کا مالک',
  'notification_recipient.topic_owner': 'موضوع کا مالک',
  'notification_event.kb_article.submitted': 'مضمون جائزے کے لیے بھیجا گیا',
  'notification_event.kb_article.approved': 'مضمون منظور ہوا',
  'notification_event.kb_article.rejected': 'مضمون واپس بھیجا گیا',
  'notification_event.kb_article.withdrawn': 'مضمون واپس لیا گیا',
  'notification_event.kb_article.review_due': 'مضمون کے جائزے کا وقت',
  'notification_variable.article.reason': 'مضمون › وجہ',
  'notification_variable.article.review_on': 'مضمون › جائزے کی تاریخ',
  'notification_template.kb_article.submitted.in_app':
    '{{ actor.name }} نے {{ record.display_id }} جائزے کے لیے بھیجا: {{ record.title }}',
  'notification_template.kb_article.submitted.subject':
    'جائزہ درکار: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.submitted.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ actor.name }} نے مضمون {{ record.display_id }} "{{ record.title }}" جائزے کے لیے بھیجا ہے۔ اسے کھول کر منظور کریں یا واپس بھیجیں۔',
  'notification_template.kb_article.approved.in_app':
    '{{ record.display_id }} شائع ہو گیا: {{ record.title }}',
  'notification_template.kb_article.approved.subject':
    'شائع شدہ: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.approved.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ actor.name }} نے مضمون {{ record.display_id }} "{{ record.title }}" منظور کر دیا۔ اب اس کے قارئین اسے دیکھ سکتے ہیں۔',
  'notification_template.kb_article.rejected.in_app':
    '{{ record.display_id }} واپس بھیجا گیا: {{ article.reason }}',
  'notification_template.kb_article.rejected.subject':
    'واپس بھیجا گیا: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.rejected.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ actor.name }} نے مضمون {{ record.display_id }} "{{ record.title }}" مسودے کے طور پر واپس بھیج دیا۔\n\nوجہ: {{ article.reason }}',
  'notification_template.kb_article.withdrawn.in_app':
    '{{ record.display_id }} واپس لیا گیا: {{ article.reason }}',
  'notification_template.kb_article.withdrawn.subject':
    'واپس لیا گیا: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.withdrawn.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ actor.name }} نے مضمون {{ record.display_id }} "{{ record.title }}" واپس لے لیا۔ قارئین اب اسے نہیں دیکھ سکتے۔\n\nوجہ: {{ article.reason }}',
  'notification_template.kb_article.review_due.in_app':
    '{{ record.display_id }} کے جائزے کا وقت ہے: {{ record.title }}',
  'notification_template.kb_article.review_due.subject':
    'جائزے کا وقت: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.review_due.body':
    'السلام علیکم {{ recipient.name }}،\n\nمضمون {{ record.display_id }} "{{ record.title }}" کا جائزہ {{ article.review_on }} کو ہونا تھا۔ دیکھیں کہ یہ اب بھی درست ہے، یا اس میں ترمیم کریں۔',
  'notification_category.created': 'نئے ریکارڈ',
  'notification_category.assignment': 'تفویض',
  'notification_category.conversation': 'جوابات اور نوٹس',
  'notification_category.status': 'حالت کی تبدیلیاں',
  'notification_category.mention': 'تذکرے',
  'notification_category.following': 'فالو کرنا',
  'notification_channel.in_app': 'ایپ میں',
  'notification_channel.email': 'ای میل',
  'notification_condition_operator.in': 'ان میں سے ایک ہے',
  'notification_condition_operator.not_in': 'ان میں سے کوئی نہیں',
  'notification_state.queued': 'بھیجی جا رہی ہے',
  'notification_state.waiting': 'میل سیٹ اپ کا انتظار',
  'notification_state.sent': 'بھیج دی گئی',
  'notification_state.failed': 'ناکام',
  'notification_state.suppressed': 'نہیں بھیجی گئی',
  'notification_reason.no_access': 'وہ اب ریکارڈ نہیں دیکھ سکتے',
  'notification_reason.preference': 'ان کی ترجیحات میں بند ہے',
  'notification_reason.do_not_disturb': 'پریشان نہ کریں آن تھا',
  'notification_reason.no_address': 'غیر فعال، یا ای میل پتہ نہیں',
  'notification_reason.mail_refused': 'میل سرور نے پیغام مسترد کر دیا',
  'notification_reason.gave_up': 'کئی کوششوں کے بعد ترسیل روک دی گئی',
  'notification_recipient.requester': 'درخواست گزار',
  'notification_recipient.on_behalf_of': 'جس کے لیے ہے',
  'notification_recipient.assignee': 'تفویض شدہ تکنیکی ماہر',
  'notification_recipient.previous_assignee': 'سابقہ تکنیکی ماہر',
  'notification_recipient.group': 'گروپ کے اراکین',
  'notification_recipient.group_head': 'گروپ لیڈ اور شعبے کا سربراہ',
  'notification_recipient.followers': 'فالوورز',
  'notification_recipient.mentioned': 'جن کا ذکر ہوا',
  'notification_recipient.new_follower': 'نیا فالوور',
  'notification_event.incident.created': 'نیا واقعہ: وصولی کی تصدیق',
  'notification_event.incident.created_in_group': 'گروپ میں نیا واقعہ',
  'notification_event.incident.assigned': 'واقعہ تفویض ہوا',
  'notification_event.incident.public_reply': 'عوامی جواب',
  'notification_event.incident.public_note': 'عوامی نوٹ',
  'notification_event.incident.private_note': 'نجی نوٹ',
  'notification_event.incident.requester_replied': 'درخواست گزار نے جواب دیا',
  'notification_event.incident.mentioned': 'ذکر',
  'notification_event.incident.status_changed': 'حالت بدلی',
  'notification_event.incident.resolved': 'واقعہ حل ہوا',
  'notification_event.incident.closed': 'واقعہ بند ہوا',
  'notification_event.incident.reopened': 'واقعہ دوبارہ کھلا',
  'notification_event.incident.canceled': 'واقعہ منسوخ ہوا',
  'notification_event.incident.follower_added': 'فالوور کے طور پر شامل',
  'notification_variable.record.display_id': 'ریکارڈ › شناخت',
  'notification_variable.record.title': 'ریکارڈ › موضوع',
  'notification_variable.record.priority': 'ریکارڈ › ترجیح',
  'notification_variable.record.status': 'ریکارڈ › حالت',
  'notification_variable.record.link': 'ریکارڈ › لنک',
  'notification_variable.requester.name': 'درخواست گزار › نام',
  'notification_variable.assignee.name': 'تکنیکی ماہر › نام',
  'notification_variable.actor.name': 'تبدیل کنندہ › نام',
  'notification_variable.recipient.name': 'وصول کنندہ › نام',
  'notification_variable.conversation.author': 'جواب یا نوٹ › مصنف',
  'notification_variable.conversation.excerpt': 'جواب یا نوٹ › متن',
  'notification_variable.change.from_status': 'تبدیلی › سابقہ حالت',
  'notification.open_record': '{{id}} کھولیں',
  'notification_template.incident.created.in_app':
    'ہمیں {{ record.display_id }} موصول ہوا: {{ record.title }}',
  'notification_template.incident.created.subject':
    'آپ کی درخواست {{ record.display_id }} موصول ہوئی: {{ record.title }}',
  'notification_template.incident.created.body':
    'السلام علیکم {{ recipient.name }}،\n\nہمیں آپ کی درخواست "{{ record.title }}" موصول ہوئی اور اسے {{ record.display_id }} کے طور پر درج کر لیا گیا ہے۔ ہم آپ کو باخبر رکھیں گے۔',
  'notification_template.incident.created_in_group.in_app':
    'آپ کے گروپ میں نیا: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.created_in_group.subject':
    'نیا واقعہ {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.created_in_group.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" آپ کے گروپ میں آیا ہے۔\n\nترجیح: {{ record.priority }}\nدرخواست گزار: {{ requester.name }}',
  'notification_template.incident.assigned.in_app':
    '{{ record.display_id }} {{ assignee.name }} کو تفویض ہوا: {{ record.title }}',
  'notification_template.incident.assigned.subject':
    '{{ assignee.name }} کو تفویض: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.assigned.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اب {{ assignee.name }} کو تفویض ہے۔\n\nترجیح: {{ record.priority }}\nحالت: {{ record.status }}\nدرخواست گزار: {{ requester.name }}',
  'notification_template.incident.public_reply.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر جواب دیا',
  'notification_template.incident.public_reply.subject':
    '{{ record.display_id }} پر نیا جواب: {{ record.title }}',
  'notification_template.incident.public_reply.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر جواب دیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.public_note.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر نوٹ شامل کیا',
  'notification_template.incident.public_note.subject':
    '{{ record.display_id }} پر نیا نوٹ: {{ record.title }}',
  'notification_template.incident.public_note.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر نوٹ شامل کیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.private_note.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر نجی نوٹ شامل کیا',
  'notification_template.incident.private_note.subject':
    '{{ record.display_id }} پر نجی نوٹ: {{ record.title }}',
  'notification_template.incident.private_note.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر نجی نوٹ شامل کیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.requester_replied.in_app':
    'درخواست گزار {{ conversation.author }} نے {{ record.display_id }} پر جواب دیا',
  'notification_template.incident.requester_replied.subject':
    'درخواست گزار نے {{ record.display_id }} پر جواب دیا: {{ record.title }}',
  'notification_template.incident.requester_replied.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر جواب دیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.mentioned.in_app':
    '{{ conversation.author }} نے {{ record.display_id }} پر آپ کا ذکر کیا',
  'notification_template.incident.mentioned.subject':
    '{{ record.display_id }} پر آپ کا ذکر ہوا: {{ record.title }}',
  'notification_template.incident.mentioned.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ conversation.author }} نے {{ record.display_id }} "{{ record.title }}" پر آپ کا ذکر کیا:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.status_changed.in_app':
    '{{ record.display_id }} اب {{ record.status }} ہے',
  'notification_template.incident.status_changed.subject':
    '{{ record.display_id }} اب {{ record.status }} ہے: {{ record.title }}',
  'notification_template.incident.status_changed.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" کی حالت {{ change.from_status }} سے {{ record.status }} ہو گئی۔',
  'notification_template.incident.resolved.in_app': '{{ record.display_id }} حل ہو گیا',
  'notification_template.incident.resolved.subject':
    'حل ہو گیا: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.resolved.body':
    'السلام علیکم {{ recipient.name }}،\n\nہم نے {{ record.display_id }} "{{ record.title }}" حل کر دیا ہے۔ اگر مسئلہ اب بھی موجود ہے تو جواب دے کر ہمیں بتائیں۔',
  'notification_template.incident.closed.in_app': '{{ record.display_id }} بند ہو گیا',
  'notification_template.incident.closed.subject':
    'بند: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.closed.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اب بند ہے۔',
  'notification_template.incident.reopened.in_app': '{{ record.display_id }} دوبارہ کھل گیا',
  'notification_template.incident.reopened.subject':
    'دوبارہ کھلا: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.reopened.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" دوبارہ کھل گیا ہے اور پھر توجہ چاہتا ہے۔\n\nحالت: {{ record.status }}',
  'notification_template.incident.canceled.in_app': '{{ record.display_id }} منسوخ ہو گیا',
  'notification_template.incident.canceled.subject':
    'منسوخ: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.canceled.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" منسوخ کر دیا گیا۔',
  'notification_template.incident.follower_added.in_app':
    'آپ اب {{ record.display_id }} کو فالو کرتے ہیں: {{ record.title }}',
  'notification_template.incident.follower_added.subject':
    'آپ اب {{ record.display_id }} کو فالو کرتے ہیں: {{ record.title }}',
  'notification_template.incident.follower_added.body':
    'السلام علیکم {{ recipient.name }}،\n\nآپ اب {{ record.display_id }} "{{ record.title }}" کو فالو کرتے ہیں اور اس کی تازہ کاریوں سے باخبر رہیں گے۔',
  'notifications.title': 'اطلاعات',
  'notifications.open_one': 'اطلاعات، {{count}} نہ پڑھی ہوئی',
  'notifications.open_other': 'اطلاعات، {{count}} نہ پڑھی ہوئی',
  'notifications.read_all': 'سب کو پڑھا ہوا نشان زد کریں',
  'notifications.do_not_disturb': 'پریشان نہ کریں',
  'notifications.empty': 'ابھی کوئی اطلاع نہیں۔',
  'notifications.more': 'پرانی دکھائیں',
  'notifications.banner.title': 'ای میل اطلاعات انتظار میں ہیں',
  'notifications.banner.no_mail_one':
    '{{count}} ای میل انتظار میں ہے کیونکہ باہر جانے والی میل سیٹ نہیں ہے۔ ایپ میں اطلاعات جاری ہیں؛ میل چلنے پر ای میل بھیج دی جائے گی۔',
  'notifications.banner.no_mail_other':
    '{{count}} ای میلز انتظار میں ہیں کیونکہ باہر جانے والی میل سیٹ نہیں ہے۔ ایپ میں اطلاعات جاری ہیں؛ میل چلنے پر ای میلز بھیج دی جائیں گی۔',
  'notifications.banner.sending_one': 'انتظار میں موجود {{count}} ای میل اب بھیجی جا رہی ہے۔',
  'notifications.banner.sending_other': 'انتظار میں موجود {{count}} ای میلز اب بھیجی جا رہی ہیں۔',
  'notification_rules.intro':
    'کون سے واقعات کسے اور کیسے اطلاع دیتے ہیں۔ ہر واقعہ ایک مناسب پہلے سے طے شدہ ترتیب سے شروع ہوتا ہے؛ تبدیلیاں آڈٹ لاگ میں درج ہوتی ہیں۔',
  'notification_rules.saved': 'اطلاع کا قاعدہ محفوظ ہو گیا۔',
  'notification_rules.col.event': 'واقعہ',
  'notification_rules.col.on': 'آن',
  'notification_rules.col.recipients': 'کون',
  'notification_rules.col.channels': 'کیسے',
  'notification_rules.col.priority': 'صرف اس ترجیح کے لیے',
  'notification_rules.any_priority': 'کوئی بھی ترجیح',
  'notification_rules.required': 'لوگوں کے لیے لازمی',
  'notification_rules.default': 'پہلے سے طے شدہ',
  'notification_rules.changed': '{{when}} کو تبدیل ہوا',
  'notification_rules.reset': 'پہلے سے طے شدہ پر واپس',
  'notification_preferences.title': 'اطلاعات',
  'notification_preferences.help':
    'منتخب کریں کہ آپ کو کس بارے میں اور کہاں اطلاع ملے۔ کچھ اطلاعات آپ کی تنظیم کی طرف سے لازمی ہیں۔',
  'notification_preferences.saved': 'ترجیحات محفوظ ہو گئیں۔',
  'notification_preferences.col.category': 'قسم',
  'notification_preferences.locked': 'آپ کی تنظیم کی طرف سے لازمی: اسے بند نہیں کیا جا سکتا۔',
  'notification_preferences.dnd_help':
    'کوئی پاپ اپ نہیں اور فوری و لازمی کے سوا کوئی ای میل نہیں؛ سب کچھ آپ کی اطلاعات میں پھر بھی آتا ہے۔',
  'notification_event.mailbox.mail_held': 'ایک بھیجنے والا میل باکس کو پیغامات سے بھر رہا ہے',
  'notification_template.mailbox.mail_held.in_app':
    '{{ record.title }} کی میل جائزے کے لیے روکی گئی: ایک بھیجنے والے نے ایک گھنٹے میں 10 سے زیادہ پیغامات بھیجے',
  'notification_template.mailbox.mail_held.subject':
    'میل باکس {{ record.title }}: میل جائزے کے لیے روکی گئی',
  'notification_template.mailbox.mail_held.body':
    'السلام علیکم {{ recipient.name }}،\n\nایک بھیجنے والے نے {{ record.title }} پر ایک گھنٹے میں 10 سے زیادہ پیغامات بھیجے، جوابات سمیت۔ SupportX ریکارڈ بنانے کے بجائے ان کی مزید میل روک لیتا ہے، اس لیے کچھ ضائع نہیں ہوتا اور کوئی لوپ نہیں چلتا۔\n\nایڈمن › میل کھولیں، روکے گئے پیغامات کا جائزہ لیں، اور انہیں دوبارہ داخل کریں یا رد کریں۔',
  'notification_event.mailbox.failing': 'میل باکس نے کام کرنا بند کر دیا',
  'notification_event.mailbox.credential_expiring':
    'میل باکس ایپ کا سیکرٹ یا سرٹیفکیٹ ختم ہونے والا ہے',
  'notification_recipient.mail_admins': 'میل باکس سنبھالنے والے افراد',
  'notification_variable.mailbox.address': 'میل باکس › پتہ',
  'notification_variable.mailbox.reason': 'میل باکس › وجہ',
  'notification_variable.mailbox.expires_at': 'میل باکس › اسناد کی میعاد',
  'notification_template.mailbox.failing.in_app':
    '{{ record.title }} نے کام کرنا بند کر دیا: {{ mailbox.reason }}',
  'notification_template.mailbox.failing.subject':
    'میل باکس {{ record.title }} نے کام کرنا بند کر دیا',
  'notification_template.mailbox.failing.body':
    'السلام علیکم {{ recipient.name }}،\n\nSupportX {{ record.title }} نہیں پڑھ سکتا: {{ mailbox.reason }}۔\n\nجب تک یہ ٹھیک نہ ہو، میل سرور پر انتظار کرتی ہے۔ میل باکس دیکھنے کے لیے ایڈمن › میل کھولیں۔',
  'notification_template.mailbox.credential_expiring.in_app':
    '{{ record.title }} کی ایپ کا سیکرٹ یا سرٹیفکیٹ {{ mailbox.expires_at }} کو ختم ہو رہا ہے',
  'notification_template.mailbox.credential_expiring.subject':
    'میل باکس {{ record.title }}: ایپ کی اسناد جلد ختم ہو رہی ہیں',
  'notification_template.mailbox.credential_expiring.body':
    'السلام علیکم {{ recipient.name }}،\n\nجو سیکرٹ یا سرٹیفکیٹ SupportX {{ record.title }} پڑھنے کے لیے استعمال کرتا ہے، وہ {{ mailbox.expires_at }} کو ختم ہو رہا ہے۔ اپنے Microsoft یا Google ایڈمن کنسول میں نیا بنائیں، پھر ایڈمن › میل میں درج کریں تاکہ میل آتی رہے۔',
  'event_delivery.stalled.title': 'واقعات کی ترسیل رکی ہوئی ہے',
  'event_delivery.stalled.body':
    'اطلاعات، براہ راست اپ ڈیٹس اور ایکسپورٹس میں تاخیر ہے۔ کچھ ضائع نہیں ہوگا: سروس بحال ہوتے ہی یہ بھیج دیے جائیں گے۔',
  'event_delivery_state.ok': 'ترسیل جاری',
  'event_delivery_state.stalled': 'رکی ہوئی',
  'notification_event.connector.failing': 'کنیکٹر نے کام کرنا چھوڑ دیا',
  'notification_event.connector.recovered': 'کنیکٹر دوبارہ کام کر رہا ہے',
  'notification_recipient.connector_admins': 'وہ لوگ جو یہ کنیکٹر سیٹ اپ کرتے ہیں',
  'notification_variable.connector.name': 'کنیکٹر › نام',
  'notification_variable.connector.reason': 'کنیکٹر › وجہ',
  'notification_template.connector.failing.in_app':
    '{{ record.title }} نے کام کرنا چھوڑ دیا: {{ connector.reason }}',
  'notification_template.connector.failing.subject': '{{ record.title }} نے کام کرنا چھوڑ دیا',
  'notification_template.connector.failing.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.title }} نے کام کرنا چھوڑ دیا: {{ connector.reason }}۔\n\nآپ کو ہر کوشش پر نہیں بلکہ ایک بار بتایا جائے گا، اور دوبارہ جب یہ کام کرنے لگے۔ اسے دیکھنے کے لیے ایڈمن › انٹیگریشنز کھولیں۔',
  'notification_template.connector.recovered.in_app': '{{ record.title }} دوبارہ کام کر رہا ہے',
  'notification_template.connector.recovered.subject': '{{ record.title }} دوبارہ کام کر رہا ہے',
  'notification_template.connector.recovered.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.title }} دوبارہ کام کر رہا ہے۔ مزید کچھ کرنے کی ضرورت نہیں۔',
  'notification_event.incident.sla_warning': 'ایس ایل اے کی انتباہی حد آ گئی',
  'notification_event.incident.sla_breached': 'ایس ایل اے ہدف میں تاخیر',
  'notification_event.incident.sla_escalated': 'ایس ایل اے ایسکلیشن',
  'notification_recipient.escalation_recipients': 'ایسکلیشن درجے کے وصول کنندگان',
  'notification_variable.sla.target': 'ایس ایل اے › ہدف',
  'notification_template.incident.sla_warning.in_app':
    '{{ record.display_id }}: {{ sla.target }} کا وقت قریب ہے',
  'notification_template.incident.sla_warning.subject':
    'جلد واجب: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_warning.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اپنے {{ sla.target }} ہدف کی انتباہی حد تک پہنچ گیا ہے۔',
  'notification_template.incident.sla_breached.in_app':
    '{{ record.display_id }}: {{ sla.target }} میں تاخیر ہو گئی',
  'notification_template.incident.sla_breached.subject':
    'تاخیر: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_breached.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اپنے {{ sla.target }} ہدف کا وقت گزار چکا ہے۔',
  'notification_template.incident.sla_escalated.in_app':
    'آپ کو ایسکلیٹ کیا گیا: {{ record.display_id }} ({{ sla.target }})',
  'notification_template.incident.sla_escalated.subject':
    'ایسکلیشن: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_escalated.body':
    'السلام علیکم {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" اس کے {{ sla.target }} ایس ایل اے کے تحت آپ کو ایسکلیٹ کیا گیا ہے۔',
};
