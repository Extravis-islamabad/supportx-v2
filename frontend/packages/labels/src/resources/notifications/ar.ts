import type { LabelResource } from '../en';

// notifications labels (see ../README.md).
export const ar: LabelResource = {
  'assignee_unavailable.away': 'حالته «غائب»',
  'assignee_unavailable.inactive': 'لم يعد نشطًا',
  'assignee_unavailable.not_in_group': 'لم يعد في تلك المجموعة',
  'delivery_reason.authentication_failed': 'رفض خادم البريد تسجيل دخول SupportX',
  'delivery_reason.email_channel_not_configured': 'قناة البريد الإلكتروني غير مُعدّة',
  'delivery_reason.gave_up': 'استمر الفشل بعد كل محاولة',
  'delivery_reason.mail_not_configured': 'البريد الصادر غير مُعدّ',
  'delivery_reason.mail_refused': 'تعذّر إرسال الرسالة كما كُتبت',
  'delivery_reason.message_refused': 'رفض خادم البريد الرسالة',
  'delivery_reason.no_address': 'ليس لدى مقدّم الطلب عنوان بريد إلكتروني',
  'delivery_reason.not_notified': 'لا يتلقى مقدّم الطلب بريدًا بشأن هذا',
  'delivery_reason.not_sent_in_time': 'لم يُرسل: لم يُعدّ البريد خلال 7 أيام',
  'delivery_reason.recipient_deferred': 'طلب خادم بريد المستلم المحاولة لاحقًا',
  'delivery_reason.recipient_refused': 'رفض خادم بريد المستلم العنوان',
  'delivery_reason.server_busy': 'كان خادم البريد مشغولًا',
  'delivery_reason.server_unavailable': 'تعذّر الوصول إلى خادم البريد',
  'delivery_state.failed': 'فشل الإرسال',
  'delivery_state.not_sent': 'لم يُرسل',
  'delivery_state.queued': 'قيد الإرسال',
  'delivery_state.received': 'مُستلَم',
  'delivery_state.retrying': 'تجري إعادة المحاولة',
  'delivery_state.sent': 'تم الإرسال',
  'delivery_state.waiting': 'بانتظار إعداد البريد',
  'event_delivery.stalled.body':
    'الإشعارات والتحديثات المباشرة والتصديرات متأخرة. لن يضيع شيء: ستُرسل فور تعافي الخدمة.',
  'event_delivery.stalled.title': 'توقف تسليم الأحداث',
  'event_delivery_state.ok': 'يجري التسليم',
  'event_delivery_state.stalled': 'متوقف',
  'notification.open_record': 'فتح {{id}}',
  'notification_area.announcement': 'الإعلانات',
  'notification_area.asset': 'الأصول',
  'notification_area.break_glass': 'تسجيلات دخول الطوارئ',
  'notification_area.change': 'التغييرات',
  'notification_area.connector': 'الموصلات',
  'notification_area.incident': 'الحوادث',
  'notification_area.kb_article': 'المعرفة',
  'notification_area.mailbox': 'البريد',
  'notification_area.outgoing_mail': 'البريد الصادر',
  'notification_area.problem': 'المشكلات',
  'notification_area.problem_repeat': 'المشكلات',
  'notification_area.release': 'الإصدارات',
  'notification_area.reminder': 'التذكيرات',
  'notification_area.rule_step': 'القواعد والتصعيدات',
  'notification_area.service_request': 'طلبات الخدمة',
  'notification_area.task': 'المهام',
  'notification_category.approval': 'الموافقات',
  'notification_category.assignment': 'الإسنادات',
  'notification_category.conversation': 'الردود والملاحظات',
  'notification_category.created': 'السجلات الجديدة',
  'notification_category.following': 'المتابعة',
  'notification_category.mention': 'الإشارات',
  'notification_category.status': 'تغييرات الحالة',
  'notification_category.workflow': 'رسائل سير العمل',
  'notification_channel.email': 'البريد الإلكتروني',
  'notification_channel.in_app': 'داخل التطبيق',
  'notification_condition_operator.in': 'أحد',
  'notification_condition_operator.not_in': 'ليس أحد',
  'notification_event.announcement.ended': 'انتهاء إعلان تتابعه',
  'notification_event.announcement.updated': 'تحديث إعلان تتابعه',
  'notification_event.asset.ack_disputed': 'اعترض حامل الأصل عليه',
  'notification_event.asset.ack_requested': 'أصل سُلّم إليك: يرجى الإقرار به',
  'notification_event.asset.loan_due': 'موعد إرجاع الإعارة غدًا',
  'notification_event.asset.loan_overdue': 'الإعارة متأخرة',
  'notification_event.asset.mentioned': 'إشارة في ملاحظة أصل',
  'notification_event.asset.stock_low': 'المخزون عند حده الأدنى',
  'notification_event.asset.warranty_expiring': 'الضمان ينتهي قريبًا',
  'notification_event.break_glass.signed_in': 'سجّل مسؤول طوارئ الدخول',
  'notification_event.change.approval_fallback': 'موافقة تغيير بلا من يقرر',
  'notification_event.change.approval_requested': 'مطلوب موافقة على تغيير',
  'notification_event.change.approved': 'تغيير مُوافَق عليه',
  'notification_event.change.assigned': 'تغيير مُسند إليك',
  'notification_event.change.backed_out': 'تغيير تم التراجع عنه',
  'notification_event.change.board_empty': 'مجلس التغيير بلا أعضاء',
  'notification_event.change.cab_reminder': 'التغيير ينتظر قرارك في المجلس',
  'notification_event.change.clarification': 'التغيير يحتاج إلى معلومات إضافية',
  'notification_event.change.closed': 'تغيير مُغلَق',
  'notification_event.change.implementation_failed': 'فشل تنفيذ التغيير',
  'notification_event.change.implementation_overdue': 'تأخر تنفيذ التغيير',
  'notification_event.change.implemented': 'تغيير مُنفَّذ',
  'notification_event.change.mentioned': 'إشارة إليك في تغيير',
  'notification_event.change.note': 'ملاحظة على تغيير',
  'notification_event.change.overridden': 'استُخدم تجاوز الطوارئ',
  'notification_event.change.public_reply': 'رد على مقدم الطلب',
  'notification_event.change.rejected': 'تغيير مرفوض',
  'notification_event.change.review_due': 'حان موعد مراجعة التغيير',
  'notification_event.change.sent_back': 'تغيير مُوافَق عليه يحتاج إلى موافقة مجددًا',
  'notification_event.change.status_entered': 'دخل التغيير حالة',
  'notification_event.change.submitted': 'تغيير مُقدَّم',
  'notification_event.change.window_reminder': 'نافذة التغيير تبدأ قريبًا',
  'notification_event.connector.failing': 'توقف الموصل عن العمل',
  'notification_event.connector.recovered': 'عاد الموصل إلى العمل',
  'notification_event.incident.assigned': 'أُسند حادث',
  'notification_event.incident.canceled': 'أُلغي الحادث',
  'notification_event.incident.closed': 'أُغلق الحادث',
  'notification_event.incident.created': 'حادث جديد: إشعار بالاستلام',
  'notification_event.incident.created_in_group': 'حادث جديد في مجموعة',
  'notification_event.incident.follower_added': 'أُضيف كمتابع',
  'notification_event.incident.mentioned': 'إشارة',
  'notification_event.incident.private_note': 'ملاحظة خاصة',
  'notification_event.incident.public_note': 'ملاحظة عامة',
  'notification_event.incident.public_reply': 'رد عام',
  'notification_event.incident.reopened': 'أُعيد فتح الحادث',
  'notification_event.incident.requester_replied': 'ردّ مقدّم الطلب',
  'notification_event.incident.resolved': 'حُلّ الحادث',
  'notification_event.incident.sla_breached': 'تأخر هدف اتفاقية مستوى الخدمة',
  'notification_event.incident.sla_escalated': 'تصعيد اتفاقية مستوى الخدمة',
  'notification_event.incident.sla_warning': 'بلوغ نقطة تحذير اتفاقية مستوى الخدمة',
  'notification_event.incident.status_changed': 'تغيّرت الحالة',
  'notification_event.incident.workflow_notice': 'رسالة من سير عمل',
  'notification_event.kb_article.approved': 'اعتُمدت المقالة',
  'notification_event.kb_article.rejected': 'أُعيدت المقالة',
  'notification_event.kb_article.review_due': 'حان موعد مراجعة المقالة',
  'notification_event.kb_article.submitted': 'أُرسلت مقالة للمراجعة',
  'notification_event.kb_article.withdrawn': 'سُحبت المقالة',
  'notification_event.mailbox.credential_expiring':
    'سرّ تطبيق صندوق البريد أو شهادته على وشك الانتهاء',
  'notification_event.mailbox.failing': 'توقف صندوق البريد عن العمل',
  'notification_event.mailbox.mail_held': 'مُرسِل يُغرق صندوق بريد بالرسائل',
  'notification_event.outgoing_mail.not_sent': 'رسائل بريد لم تُرسل: البريد غير مُعدّ',
  'notification_event.problem.assigned': 'أُسندت مشكلة',
  'notification_event.problem.closed': 'أُغلقت مشكلة',
  'notification_event.problem.created_in_group': 'أُنشئت مشكلة في مجموعتك',
  'notification_event.problem.investigator_added': 'أُضيف محقق',
  'notification_event.problem.known_error': 'نُشر خطأ معروف',
  'notification_event.problem.mentioned': 'أُشير إليك في مشكلة',
  'notification_event.problem.note': 'ملاحظة على مشكلة',
  'notification_event.problem.resolved': 'حُلّت مشكلة',
  'notification_event.problem.target_breached': 'تجاوزت مشكلة موعدها المستهدف',
  'notification_event.problem.target_warning': 'اقترب الموعد المستهدف لمشكلة',
  'notification_event.problem_repeat.detected': 'وُجدت حوادث متكررة',
  'notification_event.release.public_reply': 'رد على مقدم الطلب',
  'notification_event.reminder.due': 'تذكيرك',
  'notification_event.rule_step.assignee_unavailable': 'تعذّر على القاعدة إسناد الشخص المحدد',
  'notification_event.service_request.approval_fallback': 'موافقة بانتظار المسؤولين',
  'notification_event.service_request.approval_requested': 'طلب موافقة',
  'notification_event.service_request.approved': 'الموافقة على الطلب',
  'notification_event.service_request.fulfilled': 'تنفيذ الطلب',
  'notification_event.service_request.public_reply': 'رد على مقدم الطلب',
  'notification_event.service_request.ready_to_fulfil': 'طلب جاهز للتنفيذ',
  'notification_event.service_request.received': 'استلام الطلب: إشعار',
  'notification_event.service_request.rejected': 'رفض الطلب',
  'notification_event.service_request.withdrawn': 'سحب الطلب',
  'notification_event.task.assigned': 'أُسندت إليك مهمة',
  'notification_event.task.overdue': 'مهمتك متأخرة',
  'notification_event.task.starts_soon': 'مهمتك تبدأ قريبًا',
  'notification_preferences.col.category': 'النوع',
  'notification_preferences.dnd_help':
    'لا نوافذ منبثقة ولا بريد إلا العاجل والإلزامي؛ ويبقى كل شيء في إشعاراتك.',
  'notification_preferences.help': 'اختر ما يصلك وأين. بعض الإشعارات تُلزمك بها مؤسستك.',
  'notification_preferences.locked': 'تُلزمك به مؤسستك: لا يمكن إيقافه.',
  'notification_preferences.saved': 'حُفظت التفضيلات.',
  'notification_preferences.title': 'الإشعارات',
  'notification_reason.do_not_disturb': 'كان وضع عدم الإزعاج مفعّلًا',
  'notification_reason.gave_up': 'توقف الإرسال بعد عدة محاولات',
  'notification_reason.mail_refused': 'رفض خادم البريد الرسالة',
  'notification_reason.no_access': 'لم يعد بإمكانه رؤية السجل',
  'notification_reason.no_address': 'غير نشط أو بلا بريد إلكتروني',
  'notification_reason.preference': 'أُوقف في تفضيلاته',
  'notification_recipient.approval_administrators': 'مسؤولو الموافقات',
  'notification_recipient.approver': 'المعتمِد',
  'notification_recipient.approvers': 'المعتمِدون',
  'notification_recipient.asset_managers': 'مديرو الأصول',
  'notification_recipient.assigned_by': 'الشخص الذي سلّمه',
  'notification_recipient.assignee': 'الفني المُسند',
  'notification_recipient.author': 'المؤلف',
  'notification_recipient.borrower': 'المستعير',
  'notification_recipient.cab': 'أعضاء المجلس الاستشاري للتغيير',
  'notification_recipient.cab_member': 'عضو المجلس الذي لم يقرر بعد',
  'notification_recipient.change_manager': 'مدير التغيير',
  'notification_recipient.change_owner': 'مالك التغيير',
  'notification_recipient.connector_admins': 'الأشخاص الذين يُعدّون هذا الموصل',
  'notification_recipient.escalation_recipients': 'مستلمو مستوى التصعيد',
  'notification_recipient.followers': 'المتابعون',
  'notification_recipient.group': 'أعضاء المجموعة',
  'notification_recipient.group_head': 'قائد المجموعة ورئيس القسم',
  'notification_recipient.holder': 'الشخص الذي يحمله',
  'notification_recipient.implementer': 'المنفِّذ',
  'notification_recipient.line_manager': 'المدير المباشر',
  'notification_recipient.linked_incident_technicians': 'فنيو الحوادث المرتبطة',
  'notification_recipient.loan_creator': 'من أنشأ الإعارة',
  'notification_recipient.mail_admins': 'من يديرون صناديق البريد',
  'notification_recipient.mentioned': 'الأشخاص المُشار إليهم',
  'notification_recipient.new_follower': 'المتابع الجديد',
  'notification_recipient.new_investigator': 'المحقق المضاف',
  'notification_recipient.on_behalf_of': 'الشخص المعني',
  'notification_recipient.other_tenant_admins': 'مسؤولو المؤسسة الآخرون',
  'notification_recipient.owner': 'مالك المقالة',
  'notification_recipient.previous_assignee': 'الفني السابق',
  'notification_recipient.requester': 'مقدّم الطلب',
  'notification_recipient.reviewer': 'المراجِع',
  'notification_recipient.step_owner': 'مالك القاعدة (وإلا فمسؤولوها)',
  'notification_recipient.stock_watchers': 'الأشخاص المحددون للحد الأدنى',
  'notification_recipient.topic_owner': 'مالك الموضوع',
  'notification_recipient.workflow_audience': 'الأشخاص الذين يحدّدهم سير العمل',
  'notification_rules.any_priority': 'أي أولوية',
  'notification_rules.any_status': 'أي حالة',
  'notification_rules.changed': 'غُيّر {{when}}',
  'notification_rules.col.channels': 'كيف',
  'notification_rules.col.event': 'الحدث',
  'notification_rules.col.on': 'مفعّل',
  'notification_rules.col.priority': 'لأولوية فقط',
  'notification_rules.col.recipients': 'من',
  'notification_rules.col.status': 'فقط للحالة',
  'notification_rules.intro':
    'الأحداث التي تُرسل إشعارات ولمن وكيف. يبدأ كل حدث بإعداد افتراضي مناسب، وتُسجَّل التغييرات في سجل التدقيق.',
  'notification_rules.none': 'لا يوجد حدث مطابق',
  'notification_rules.required': 'إلزامي للأشخاص',
  'notification_rules.reset': 'العودة إلى الافتراضي',
  'notification_rules.saved': 'حُفظت قاعدة الإشعار.',
  'notification_rules.search': 'البحث في الأحداث',
  'notification_state.failed': 'فشل',
  'notification_state.queued': 'قيد الإرسال',
  'notification_state.sent': 'أُرسل',
  'notification_state.suppressed': 'لم يُرسل',
  'notification_state.waiting': 'بانتظار إعداد البريد',
  'notification_template.announcement.ended.body':
    'مرحبًا {{ recipient.name }}،\n\nانتهى الإعلان "{{ record.title }}" الذي تتابعه.',
  'notification_template.announcement.ended.in_app': 'انتهى: {{ record.title }}',
  'notification_template.announcement.ended.subject': 'انتهى: {{ record.title }}',
  'notification_template.announcement.updated.body':
    'مرحبًا {{ recipient.name }}،\n\nتم تحديث الإعلان "{{ record.title }}" الذي تتابعه.',
  'notification_template.announcement.updated.in_app': 'تم التحديث: {{ record.title }}',
  'notification_template.announcement.updated.subject': 'تم التحديث: {{ record.title }}',
  'notification_template.asset.ack_disputed.body':
    'مرحبًا {{ recipient.name }}،\n\nاعترض {{ holder.name }} على {{ record.display_id }} "{{ record.title }}": {{ acknowledgement.comment }}',
  'notification_template.asset.ack_disputed.in_app':
    'اعترض {{ holder.name }} على {{ record.display_id }}: {{ acknowledgement.comment }}',
  'notification_template.asset.ack_disputed.subject':
    'اعتراض: {{ record.display_id }} {{ record.title }}',
  'notification_template.asset.ack_requested.body':
    'مرحبًا {{ recipient.name }}،\n\nسُلّم إليك {{ record.display_id }} "{{ record.title }}". افتح أصولي لقبوله أو لذكر ما فيه من خطأ.',
  'notification_template.asset.ack_requested.in_app':
    'يرجى الإقرار بـ {{ record.display_id }}: {{ record.title }}',
  'notification_template.asset.ack_requested.subject':
    'يرجى الإقرار بـ {{ record.display_id }} {{ record.title }}',
  'notification_template.asset.loan_due.body':
    'مرحبًا {{ recipient.name }}،\n\nموعد إرجاع الأصول المعارة إلى {{ holder.name }} غدًا.',
  'notification_template.asset.loan_due.in_app': 'موعد إرجاع إعارة {{ holder.name }} غدًا',
  'notification_template.asset.loan_due.subject': 'موعد إرجاع الأصول المعارة غدًا',
  'notification_template.asset.loan_overdue.body':
    'مرحبًا {{ recipient.name }}،\n\nحان موعد إرجاع الأصول المعارة إلى {{ holder.name }} ولم تُرجع بعد.',
  'notification_template.asset.loan_overdue.in_app': 'إعارة {{ holder.name }} متأخرة',
  'notification_template.asset.loan_overdue.subject': 'الأصول المعارة متأخرة',
  'notification_template.asset.mentioned.body':
    'مرحبًا {{ recipient.name }}،\n\nأشار إليك {{ conversation.author }} في ملاحظة على {{ record.display_id }} "{{ record.title }}".',
  'notification_template.asset.mentioned.in_app':
    'أشار إليك {{ conversation.author }} في {{ record.display_id }}',
  'notification_template.asset.mentioned.subject':
    'أُشير إليك في {{ record.display_id }}: {{ record.title }}',
  'notification_template.asset.stock_low.body':
    'مرحبًا {{ recipient.name }}،\n\nانخفض مخزون {{ record.title }} إلى {{ stock.quantity }}، عند حده الأدنى {{ stock.minimum }} أو دونه.',
  'notification_template.asset.stock_low.in_app':
    'انخفض {{ record.title }} إلى {{ stock.quantity }} (الحد الأدنى {{ stock.minimum }})',
  'notification_template.asset.stock_low.subject': '{{ record.title }} عند الحد الأدنى للمخزون',
  'notification_template.asset.warranty_expiring.body':
    'مرحبًا {{ recipient.name }}،\n\nينتهي ضمان {{ record.display_id }} "{{ record.title }}" في {{ warranty.ends_on }}.',
  'notification_template.asset.warranty_expiring.in_app':
    'ينتهي ضمان {{ record.display_id }} في {{ warranty.ends_on }}',
  'notification_template.asset.warranty_expiring.subject':
    'الضمان ينتهي: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.approval_fallback.body':
    'مرحبًا {{ recipient.name }}،\n\nلدى {{ record.display_id }} "{{ record.title }}" موافقة لا يتولاها أحد. يمكن لمسؤول الموافقات أن يقررها.',
  'notification_template.change.approval_fallback.in_app':
    'لدى {{ record.display_id }} موافقة بلا موافِق: {{ record.title }}',
  'notification_template.change.approval_fallback.subject':
    'لا موافِق: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.approval_requested.body':
    'مرحبًا {{ recipient.name }}،\n\nينتظر {{ record.display_id }} "{{ record.title }}" موافقتك.\n\nوافق أو ارفض: {{ approval_link }}\n\nيعمل الرابط مرة واحدة، لك وحدك.',
  'notification_template.change.approval_requested.in_app':
    'ينتظر {{ record.display_id }} موافقتك: {{ record.title }}',
  'notification_template.change.approval_requested.subject':
    'موافقتك: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.approved.body':
    'مرحبًا {{ recipient.name }}،\n\nتمت الموافقة على {{ record.display_id }} "{{ record.title }}". حالته الآن: {{ record.status }}.',
  'notification_template.change.approved.in_app':
    'تمت الموافقة على {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.approved.subject':
    'تمت الموافقة: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.assigned.body':
    'مرحبًا {{ recipient.name }}،\n\nأنت الآن مالك التغيير {{ record.display_id }} "{{ record.title }}".',
  'notification_template.change.assigned.in_app':
    'أنت مالك {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.assigned.subject':
    'أنت مالك {{ record.display_id }} {{ record.title }}',
  'notification_template.change.backed_out.body':
    'مرحبًا {{ recipient.name }}،\n\nتم التراجع عن {{ record.display_id }} "{{ record.title }}". حالته الآن: {{ record.status }}.',
  'notification_template.change.backed_out.in_app':
    'تم التراجع عن {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.backed_out.subject':
    'تم التراجع: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.board_empty.body':
    'مرحبًا {{ recipient.name }}،\n\nينتظر {{ record.display_id }} "{{ record.title }}" مجلس تغيير بلا أعضاء. أضف أعضاء إلى المجلس أو اختر مجلسًا آخر.',
  'notification_template.change.board_empty.in_app':
    'ينتظر {{ record.display_id }} مجلسًا بلا أعضاء: {{ record.title }}',
  'notification_template.change.board_empty.subject':
    'مجلس بلا أعضاء: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.cab_reminder.body':
    'مرحبًا {{ recipient.name }}،\n\nيبدأ {{ record.display_id }} "{{ record.title }}" في {{ window.start }} وما زال ينتظر قرارك.\n\nوافق أو ارفض: {{ approval_link }}',
  'notification_template.change.cab_reminder.in_app':
    'يبدأ {{ record.display_id }} في {{ window.start }} وينتظرك: {{ record.title }}',
  'notification_template.change.cab_reminder.subject':
    'قرارك، يبدأ قريبًا: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.clarification.body':
    'مرحبًا {{ recipient.name }}،\n\nيحتاج {{ record.display_id }} "{{ record.title }}" إلى معلومات إضافية قبل المتابعة. افتحه لترى المطلوب.',
  'notification_template.change.clarification.in_app':
    'يحتاج {{ record.display_id }} إلى معلومات إضافية: {{ record.title }}',
  'notification_template.change.clarification.subject':
    'مطلوب معلومات إضافية: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.closed.body':
    'مرحبًا {{ recipient.name }}،\n\nأُغلق {{ record.display_id }} "{{ record.title }}".',
  'notification_template.change.closed.in_app': 'أُغلق {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.closed.subject':
    'أُغلق: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.implementation_failed.body':
    'مرحبًا {{ recipient.name }}،\n\nفشل تنفيذ {{ record.display_id }} "{{ record.title }}". حالته الآن: {{ record.status }}.',
  'notification_template.change.implementation_failed.in_app':
    'فشل تنفيذ {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.implementation_failed.subject':
    'فشل التنفيذ: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.implementation_overdue.body':
    'مرحبًا {{ recipient.name }}،\n\nانتهت نافذة تنفيذ {{ record.display_id }} "{{ record.title }}"، ولم يُنفَّذ التغيير بعد.',
  'notification_template.change.implementation_overdue.in_app':
    'انتهت نافذة {{ record.display_id }} ولم يُنفَّذ: {{ record.title }}',
  'notification_template.change.implementation_overdue.subject':
    'تأخر التنفيذ: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.implemented.body':
    'مرحبًا {{ recipient.name }}،\n\nنُفِّذ {{ record.display_id }} "{{ record.title }}". حالته الآن: {{ record.status }}.',
  'notification_template.change.implemented.in_app':
    'نُفِّذ {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.implemented.subject':
    'نُفِّذ: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.mentioned.body':
    'مرحبًا {{ recipient.name }}،\n\nأشار إليك {{ conversation.author }} في {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.change.mentioned.in_app':
    'أشار إليك {{ conversation.author }} في {{ record.display_id }}',
  'notification_template.change.mentioned.subject':
    'أُشير إليك في {{ record.display_id }} {{ record.title }}',
  'notification_template.change.note.body':
    'مرحبًا {{ recipient.name }}،\n\nأضاف {{ conversation.author }} ملاحظة على {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.change.note.in_app':
    'أضاف {{ conversation.author }} ملاحظة على {{ record.display_id }}',
  'notification_template.change.note.subject':
    'ملاحظة جديدة: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.overridden.body':
    'مرحبًا {{ recipient.name }}،\n\nاستُخدم تجاوز الطوارئ على {{ record.display_id }} "{{ record.title }}". مراجعته الآن إلزامية.',
  'notification_template.change.overridden.in_app':
    'استُخدم تجاوز الطوارئ على {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.overridden.subject':
    'تجاوز طارئ: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.public_reply.body':
    'مرحبًا {{ recipient.name }}،\n\nردّ {{ conversation.author }} على {{ record.display_id }} «{{ record.title }}»:\n\n{{ conversation.excerpt }}',
  'notification_template.change.public_reply.in_app':
    'ردّ {{ conversation.author }} على {{ record.display_id }}',
  'notification_template.change.public_reply.subject':
    'رد جديد على {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.rejected.body':
    'مرحبًا {{ recipient.name }}،\n\nرُفض {{ record.display_id }} "{{ record.title }}". حالته الآن: {{ record.status }}.',
  'notification_template.change.rejected.in_app':
    'رُفض {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.rejected.subject':
    'مرفوض: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.review_due.body':
    'مرحبًا {{ recipient.name }}،\n\nحان موعد مراجعة ما بعد التنفيذ للتغيير {{ record.display_id }} "{{ record.title }}".',
  'notification_template.change.review_due.in_app':
    'حان موعد مراجعة {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.review_due.subject':
    'حان موعد المراجعة: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.sent_back.body':
    'مرحبًا {{ recipient.name }}،\n\nتغيّر {{ record.display_id }} "{{ record.title }}" بعد الموافقة عليه، لذا يحتاج إلى موافقة مجددًا.',
  'notification_template.change.sent_back.in_app':
    'يحتاج {{ record.display_id }} إلى موافقة مجددًا: {{ record.title }}',
  'notification_template.change.sent_back.subject':
    'يحتاج إلى موافقة مجددًا: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.status_entered.body':
    'مرحبًا {{ recipient.name }}،\n\n{{ record.display_id }} "{{ record.title }}" الآن: {{ record.status }}.',
  'notification_template.change.status_entered.in_app':
    '{{ record.display_id }} الآن {{ record.status }}: {{ record.title }}',
  'notification_template.change.status_entered.subject':
    '{{ record.status }}: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.submitted.body':
    'مرحبًا {{ recipient.name }}،\n\nقُدِّم {{ record.display_id }} "{{ record.title }}" وينتظر مدير التغيير.',
  'notification_template.change.submitted.in_app':
    'قُدِّم {{ record.display_id }}: {{ record.title }}',
  'notification_template.change.submitted.subject':
    'مُقدَّم: {{ record.display_id }} {{ record.title }}',
  'notification_template.change.window_reminder.body':
    'مرحبًا {{ recipient.name }}،\n\nتبدأ نافذة تنفيذ {{ record.display_id }} "{{ record.title }}" في {{ window.start }}.',
  'notification_template.change.window_reminder.in_app':
    'يبدأ {{ record.display_id }} في {{ window.start }}: {{ record.title }}',
  'notification_template.change.window_reminder.subject':
    'يبدأ قريبًا: {{ record.display_id }} {{ record.title }}',
  'notification_template.connector.failing.body':
    'مرحبًا {{ recipient.name }}،\n\nتوقف {{ record.title }} عن العمل: {{ connector.reason }}.\n\nستُبلَّغ مرة واحدة لا عند كل محاولة، ومرة أخرى عندما يعود إلى العمل. افتح الإدارة › التكاملات لرؤيته.',
  'notification_template.connector.failing.in_app':
    'توقف {{ record.title }} عن العمل: {{ connector.reason }}',
  'notification_template.connector.failing.subject': 'توقف {{ record.title }} عن العمل',
  'notification_template.connector.recovered.body':
    'مرحبًا {{ recipient.name }}،\n\nعاد {{ record.title }} إلى العمل. لا حاجة إلى أي إجراء آخر.',
  'notification_template.connector.recovered.in_app': 'عاد {{ record.title }} إلى العمل',
  'notification_template.connector.recovered.subject': 'عاد {{ record.title }} إلى العمل',
  'notification_template.incident.assigned.body':
    'مرحبًا {{ recipient.name }}،\n\nأصبح {{ record.display_id }} «{{ record.title }}» مُسندًا إلى {{ assignee.name }}.\n\nالأولوية: {{ record.priority }}\nالحالة: {{ record.status }}\nمقدّم الطلب: {{ requester.name }}',
  'notification_template.incident.assigned.in_app':
    'أُسند {{ record.display_id }} إلى {{ assignee.name }}: {{ record.title }}',
  'notification_template.incident.assigned.subject':
    'أُسند إلى {{ assignee.name }}: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.canceled.body':
    'مرحبًا {{ recipient.name }}،\n\nأُلغي {{ record.display_id }} «{{ record.title }}».',
  'notification_template.incident.canceled.in_app': 'أُلغي {{ record.display_id }}',
  'notification_template.incident.canceled.subject':
    'أُلغي: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.closed.body':
    'مرحبًا {{ recipient.name }}،\n\nأصبح {{ record.display_id }} «{{ record.title }}» مغلقًا الآن.',
  'notification_template.incident.closed.in_app': 'أُغلق {{ record.display_id }}',
  'notification_template.incident.closed.subject':
    'أُغلق: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.created.body':
    'مرحبًا {{ recipient.name }}،\n\nاستلمنا طلبك «{{ record.title }}» وسجّلناه برقم {{ record.display_id }}. سنبقيك على اطلاع.',
  'notification_template.incident.created.in_app':
    'استلمنا {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.created.subject':
    'استلمنا طلبك {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.created_in_group.body':
    'مرحبًا {{ recipient.name }}،\n\nوصل {{ record.display_id }} «{{ record.title }}» إلى مجموعتك.\n\nالأولوية: {{ record.priority }}\nمقدّم الطلب: {{ requester.name }}',
  'notification_template.incident.created_in_group.in_app':
    'جديد في مجموعتك: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.created_in_group.subject':
    'حادث جديد {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.follower_added.body':
    'مرحبًا {{ recipient.name }}،\n\nأصبحت تتابع {{ record.display_id }} «{{ record.title }}» وستصلك تحديثاته.',
  'notification_template.incident.follower_added.in_app':
    'أصبحت تتابع {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.follower_added.subject':
    'أصبحت تتابع {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.mentioned.body':
    'مرحبًا {{ recipient.name }}،\n\nأشار إليك {{ conversation.author }} في {{ record.display_id }} «{{ record.title }}»:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.mentioned.in_app':
    'أشار إليك {{ conversation.author }} في {{ record.display_id }}',
  'notification_template.incident.mentioned.subject':
    'أُشير إليك في {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.private_note.body':
    'مرحبًا {{ recipient.name }}،\n\nأضاف {{ conversation.author }} ملاحظة خاصة على {{ record.display_id }} «{{ record.title }}»:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.private_note.in_app':
    'أضاف {{ conversation.author }} ملاحظة خاصة على {{ record.display_id }}',
  'notification_template.incident.private_note.subject':
    'ملاحظة خاصة على {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.public_note.body':
    'مرحبًا {{ recipient.name }}،\n\nأضاف {{ conversation.author }} ملاحظة على {{ record.display_id }} «{{ record.title }}»:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.public_note.in_app':
    'أضاف {{ conversation.author }} ملاحظة على {{ record.display_id }}',
  'notification_template.incident.public_note.subject':
    'ملاحظة جديدة على {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.public_reply.body':
    'مرحبًا {{ recipient.name }}،\n\nردّ {{ conversation.author }} على {{ record.display_id }} «{{ record.title }}»:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.public_reply.in_app':
    'ردّ {{ conversation.author }} على {{ record.display_id }}',
  'notification_template.incident.public_reply.subject':
    'رد جديد على {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.reopened.body':
    'مرحبًا {{ recipient.name }}،\n\nأُعيد فتح {{ record.display_id }} «{{ record.title }}» ويحتاج إلى متابعة مجددًا.\n\nالحالة: {{ record.status }}',
  'notification_template.incident.reopened.in_app': 'أُعيد فتح {{ record.display_id }}',
  'notification_template.incident.reopened.subject':
    'أُعيد فتحه: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.requester_replied.body':
    'مرحبًا {{ recipient.name }}،\n\nردّ {{ conversation.author }} على {{ record.display_id }} «{{ record.title }}»:\n\n{{ conversation.excerpt }}',
  'notification_template.incident.requester_replied.in_app':
    'ردّ مقدّم الطلب {{ conversation.author }} على {{ record.display_id }}',
  'notification_template.incident.requester_replied.subject':
    'ردّ مقدّم الطلب على {{ record.display_id }}: {{ record.title }}',
  'notification_template.incident.resolved.body':
    'مرحبًا {{ recipient.name }}،\n\nحللنا {{ record.display_id }} «{{ record.title }}». إذا استمرت المشكلة، ردّ لإعلامنا.',
  'notification_template.incident.resolved.in_app': 'حُلّ {{ record.display_id }}',
  'notification_template.incident.resolved.subject':
    'تم الحل: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_breached.body':
    'مرحبًا {{ recipient.name }}،\n\nتجاوز {{ record.display_id }} "{{ record.title }}" موعد هدف {{ sla.target }}.',
  'notification_template.incident.sla_breached.in_app':
    '{{ record.display_id }}: تأخر {{ sla.target }}',
  'notification_template.incident.sla_breached.subject':
    'متأخر: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_escalated.body':
    'مرحبًا {{ recipient.name }}،\n\nصُعِّد إليك {{ record.display_id }} "{{ record.title }}" بموجب اتفاقية مستوى الخدمة الخاصة بـ {{ sla.target }}.',
  'notification_template.incident.sla_escalated.in_app':
    'صُعِّد إليك: {{ record.display_id }} ({{ sla.target }})',
  'notification_template.incident.sla_escalated.subject':
    'تصعيد: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.sla_warning.body':
    'مرحبًا {{ recipient.name }}،\n\nبلغ {{ record.display_id }} "{{ record.title }}" نقطة التحذير لهدف {{ sla.target }}.',
  'notification_template.incident.sla_warning.in_app':
    '{{ record.display_id }}: اقترب موعد {{ sla.target }}',
  'notification_template.incident.sla_warning.subject':
    'يستحق قريبًا: {{ record.display_id }} {{ record.title }}',
  'notification_template.incident.status_changed.body':
    'مرحبًا {{ recipient.name }}،\n\nتغيّرت حالة {{ record.display_id }} «{{ record.title }}» من {{ change.from_status }} إلى {{ record.status }}.',
  'notification_template.incident.status_changed.in_app':
    'أصبح {{ record.display_id }} الآن {{ record.status }}',
  'notification_template.incident.status_changed.subject':
    'أصبح {{ record.display_id }} الآن {{ record.status }}: {{ record.title }}',
  'notification_template.incident.workflow_notice.body': '{{ notice.body }}',
  'notification_template.incident.workflow_notice.in_app': '{{ notice.subject }}',
  'notification_template.incident.workflow_notice.subject': '{{ notice.subject }}',
  'notification_template.kb_article.approved.body':
    'مرحباً {{ recipient.name }}،\n\nاعتمد {{ actor.name }} المقالة {{ record.display_id }} "{{ record.title }}". يراها قرّاؤها الآن.',
  'notification_template.kb_article.approved.in_app':
    'نُشرت {{ record.display_id }}: {{ record.title }}',
  'notification_template.kb_article.approved.subject':
    'منشورة: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.rejected.body':
    'مرحباً {{ recipient.name }}،\n\nأعاد {{ actor.name }} المقالة {{ record.display_id }} "{{ record.title }}" كمسودة.\n\nالسبب: {{ article.reason }}',
  'notification_template.kb_article.rejected.in_app':
    'أُعيدت {{ record.display_id }}: {{ article.reason }}',
  'notification_template.kb_article.rejected.subject':
    'أُعيدت: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.review_due.body':
    'مرحباً {{ recipient.name }}،\n\nحان موعد مراجعة المقالة {{ record.display_id }} "{{ record.title }}" في {{ article.review_on }}. تحقّق من أنها ما زالت صحيحة أو عدّلها.',
  'notification_template.kb_article.review_due.in_app':
    'حان موعد مراجعة {{ record.display_id }}: {{ record.title }}',
  'notification_template.kb_article.review_due.subject':
    'موعد المراجعة: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.submitted.body':
    'مرحباً {{ recipient.name }}،\n\nأرسل {{ actor.name }} المقالة {{ record.display_id }} "{{ record.title }}" للمراجعة. افتحها لاعتمادها أو إعادتها.',
  'notification_template.kb_article.submitted.in_app':
    'أرسل {{ actor.name }} المقالة {{ record.display_id }} للمراجعة: {{ record.title }}',
  'notification_template.kb_article.submitted.subject':
    'مطلوب مراجعة: {{ record.display_id }} {{ record.title }}',
  'notification_template.kb_article.withdrawn.body':
    'مرحباً {{ recipient.name }}،\n\nسحب {{ actor.name }} المقالة {{ record.display_id }} "{{ record.title }}". لم يعد القرّاء يرونها.\n\nالسبب: {{ article.reason }}',
  'notification_template.kb_article.withdrawn.in_app':
    'سُحبت {{ record.display_id }}: {{ article.reason }}',
  'notification_template.kb_article.withdrawn.subject':
    'مسحوبة: {{ record.display_id }} {{ record.title }}',
  'notification_template.mailbox.credential_expiring.body':
    'مرحبًا {{ recipient.name }}،\n\nينتهي السرّ أو الشهادة التي يستخدمها SupportX لقراءة {{ record.title }} في {{ mailbox.expires_at }}. أضف واحدًا جديدًا في وحدة تحكم المسؤول لدى Microsoft أو Google، ثم أدخله في الإدارة › البريد ليستمر وصول البريد.',
  'notification_template.mailbox.credential_expiring.in_app':
    'ينتهي سرّ تطبيق {{ record.title }} أو شهادته في {{ mailbox.expires_at }}',
  'notification_template.mailbox.credential_expiring.subject':
    'صندوق البريد {{ record.title }}: تنتهي بيانات اعتماد التطبيق قريبًا',
  'notification_template.mailbox.failing.body':
    'مرحبًا {{ recipient.name }}،\n\nلا يستطيع SupportX قراءة {{ record.title }}: {{ mailbox.reason }}.\n\nيبقى البريد على الخادم حتى يُصلح ذلك. افتح الإدارة › البريد لرؤية صندوق البريد.',
  'notification_template.mailbox.failing.in_app':
    'توقف {{ record.title }} عن العمل: {{ mailbox.reason }}',
  'notification_template.mailbox.failing.subject': 'توقف صندوق البريد {{ record.title }} عن العمل',
  'notification_template.mailbox.mail_held.body':
    'مرحبًا {{ recipient.name }}،\n\nأرسل مُرسِل أكثر من 10 رسائل خلال ساعة إلى {{ record.title }}، بما فيها الردود. يحتجز SupportX بريده التالي بدل إنشاء سجلات، فلا يضيع شيء ولا تحدث حلقة.\n\nافتح الإدارة › البريد، وراجع الرسائل المحتجزة، ثم أعد إدخالها أو تجاهلها.',
  'notification_template.mailbox.mail_held.in_app':
    'البريد الوارد إلى {{ record.title }} محتجز للمراجعة: أرسل مُرسِل أكثر من 10 رسائل خلال ساعة',
  'notification_template.mailbox.mail_held.subject':
    'صندوق البريد {{ record.title }}: بريد محتجز للمراجعة',
  'notification_template.outgoing_mail.not_sent.body':
    'مرحبًا {{ recipient.name }}،\n\nلم تُرسل {{ mail.count }} من رسائل البريد لأن البريد الصادر لم يُعدّ خلال 7 أيام. أقدمها من {{ mail.oldest_at }}. لن تُرسل متأخرة. افتح الإدارة › البريد لإعداد البريد الصادر.',
  'notification_template.outgoing_mail.not_sent.in_app':
    'لم تُرسل {{ mail.count }} من رسائل البريد: لم يُعدّ البريد الصادر خلال 7 أيام (أقدمها من {{ mail.oldest_at }}). أعدّ البريد لتُرسل الرسائل القادمة.',
  'notification_template.outgoing_mail.not_sent.subject':
    'لم تُرسل {{ mail.count }} من رسائل البريد',
  'notification_template.problem.assigned.body':
    'مرحبًا {{ recipient.name }}،\n\nأصبحت {{ record.display_id }} "{{ record.title }}" مسندة إلى {{ assignee.name }}.\n\nالأولوية: {{ record.priority }}\nالحالة: {{ record.status }}',
  'notification_template.problem.assigned.in_app':
    'أُسندت {{ record.display_id }} إلى {{ assignee.name }}: {{ record.title }}',
  'notification_template.problem.assigned.subject':
    'أُسندت إلى {{ assignee.name }}: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.closed.body':
    'مرحبًا {{ recipient.name }}،\n\nأُغلقت {{ record.display_id }} "{{ record.title }}".',
  'notification_template.problem.closed.in_app': 'أُغلقت {{ record.display_id }}',
  'notification_template.problem.closed.subject':
    'أُغلقت: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.created_in_group.body':
    'مرحبًا {{ recipient.name }}،\n\nأُنشئت {{ record.display_id }} "{{ record.title }}" في مجموعتك.',
  'notification_template.problem.created_in_group.in_app':
    'مشكلة جديدة: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.created_in_group.subject':
    'مشكلة جديدة في مجموعتك: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.investigator_added.body':
    'مرحبًا {{ recipient.name }}،\n\nأضافك {{ actor.name }} محققًا في {{ record.display_id }} "{{ record.title }}". يمكنك العمل على مهامها وسجلات عملها.',
  'notification_template.problem.investigator_added.in_app':
    'أنت تحقق في {{ record.display_id }}: {{ record.title }}',
  'notification_template.problem.investigator_added.subject':
    'أنت تحقق في {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.known_error.body':
    'مرحبًا {{ recipient.name }}،\n\nأصبحت {{ record.display_id }} "{{ record.title }}" خطأً معروفًا. يمكن تطبيق حلها المؤقت على حوادثك.',
  'notification_template.problem.known_error.in_app':
    '{{ record.display_id }} خطأ معروف: طبّق حلها المؤقت',
  'notification_template.problem.known_error.subject':
    'خطأ معروف: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.mentioned.body':
    'مرحبًا {{ recipient.name }}،\n\nأشار إليك {{ conversation.author }} في {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.problem.mentioned.in_app':
    'أشار إليك {{ conversation.author }} في {{ record.display_id }}',
  'notification_template.problem.mentioned.subject':
    'أشار إليك {{ conversation.author }} في {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.note.body':
    'مرحبًا {{ recipient.name }}،\n\nكتب {{ conversation.author }} على {{ record.display_id }} "{{ record.title }}":\n\n{{ conversation.excerpt }}',
  'notification_template.problem.note.in_app':
    'كتب {{ conversation.author }} على {{ record.display_id }}',
  'notification_template.problem.note.subject':
    'ملاحظة جديدة على {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.resolved.body':
    'مرحبًا {{ recipient.name }}،\n\nحُلّت {{ record.display_id }} "{{ record.title }}". راجع الحوادث التي تسببت بها وقم بحلها.',
  'notification_template.problem.resolved.in_app':
    'حُلّت {{ record.display_id }}: {{ record.title }}',
  'notification_template.problem.resolved.subject':
    'حُلّت: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.target_breached.body':
    'مرحبًا {{ recipient.name }}،\n\nتجاوزت {{ record.display_id }} "{{ record.title }}" موعدها المستهدف ({{ sla.target }}).',
  'notification_template.problem.target_breached.in_app':
    'تجاوزت {{ record.display_id }} موعدها المستهدف',
  'notification_template.problem.target_breached.subject':
    'متأخرة: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem.target_warning.body':
    'مرحبًا {{ recipient.name }}،\n\nاقتربت {{ record.display_id }} "{{ record.title }}" من موعدها المستهدف ({{ sla.target }}).',
  'notification_template.problem.target_warning.in_app':
    '{{ record.display_id }}: اقترب الموعد المستهدف',
  'notification_template.problem.target_warning.subject':
    'مستحقة قريبًا: {{ record.display_id }} {{ record.title }}',
  'notification_template.problem_repeat.detected.body':
    'مرحبًا {{ recipient.name }}،\n\n{{ incident.count }} حوادث تطابق «{{ rule.name }}» ({{ category.name }}، {{ site.name }}). راجعها وأنشئ مشكلة إن كان لها سبب واحد.',
  'notification_template.problem_repeat.detected.in_app':
    '{{ incident.count }} حوادث متشابهة: {{ rule.name }}',
  'notification_template.problem_repeat.detected.subject':
    '{{ incident.count }} حوادث متشابهة: {{ rule.name }}',
  'notification_template.release.public_reply.body':
    'مرحبًا {{ recipient.name }}،\n\nردّ {{ conversation.author }} على {{ record.display_id }} «{{ record.title }}»:\n\n{{ conversation.excerpt }}',
  'notification_template.release.public_reply.in_app':
    'ردّ {{ conversation.author }} على {{ record.display_id }}',
  'notification_template.release.public_reply.subject':
    'رد جديد على {{ record.display_id }}: {{ record.title }}',
  'notification_template.reminder.due.body':
    'مرحبًا {{ recipient.name }}،\n\nتذكيرك على {{ record.display_id }} "{{ record.title }}" في {{ reminder.at }}:\n\n{{ reminder.note }}',
  'notification_template.reminder.due.in_app': 'تذكير في {{ reminder.at }}: {{ reminder.note }}',
  'notification_template.reminder.due.subject':
    'تذكير: {{ reminder.note }} ({{ record.display_id }})',
  'notification_template.rule_step.assignee_unavailable.body':
    'مرحبًا {{ recipient.name }}،\n\nكان على قاعدة أو تصعيد إسناد {{ record.display_id }} "{{ record.title }}" إلى {{ unavailable.person }}، الذي {{ unavailable.reason }}. انتقل إلى المجموعة دون أن يُسند إلى أحد. يُرجى إسناده إلى شخص ما أو تعديل القاعدة.',
  'notification_template.rule_step.assignee_unavailable.in_app':
    'انتقل {{ record.display_id }} إلى مجموعته دون أن يُسند إلى أحد: {{ unavailable.person }} {{ unavailable.reason }}',
  'notification_template.rule_step.assignee_unavailable.subject':
    'لم يُسند إلى أحد: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.approval_fallback.body':
    'مرحبًا {{ recipient.name }}،\n\n{{ record.display_id }} «{{ record.title }}» ليس له موافق نشط، لذا هو بانتظار مسؤول موافقات.',
  'notification_template.service_request.approval_fallback.in_app':
    '{{ record.display_id }} ليس له موافق نشط وهو بانتظار مسؤول موافقات: {{ record.title }}',
  'notification_template.service_request.approval_fallback.subject':
    'موافقة بالانتظار: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.approval_requested.body':
    'مرحبًا {{ recipient.name }}،\n\nطلب {{ requester.name }} {{ record.display_id }} «{{ record.title }}» وهو بانتظار موافقتك.\n\nوافق أو ارفض: {{ approval_link }}\n\nيعمل الرابط مرة واحدة ولك وحدك بعد تسجيل الدخول.',
  'notification_template.service_request.approval_requested.in_app':
    '{{ record.display_id }} بانتظار موافقتك: {{ record.title }}',
  'notification_template.service_request.approval_requested.subject':
    'موافقتك: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.approved.body':
    'مرحبًا {{ recipient.name }}،\n\nتمت الموافقة على طلبك {{ record.display_id }} «{{ record.title }}». نعمل عليه الآن.',
  'notification_template.service_request.approved.in_app':
    'تمت الموافقة على {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.approved.subject':
    'تمت الموافقة: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.fulfilled.body':
    'مرحبًا {{ recipient.name }}،\n\nنُفّذ طلبك {{ record.display_id }} «{{ record.title }}». يرجى تأكيد الاستلام أو إخبارنا إن كان ينقصه شيء.',
  'notification_template.service_request.fulfilled.in_app':
    'نُفّذ {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.fulfilled.subject':
    'تم التنفيذ: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.public_reply.body':
    'مرحبًا {{ recipient.name }}،\n\nردّ {{ conversation.author }} على {{ record.display_id }} «{{ record.title }}»:\n\n{{ conversation.excerpt }}',
  'notification_template.service_request.public_reply.in_app':
    'ردّ {{ conversation.author }} على {{ record.display_id }}',
  'notification_template.service_request.public_reply.subject':
    'رد جديد على {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.ready_to_fulfil.body':
    'مرحبًا {{ recipient.name }}،\n\nأُنجزت كل مهام {{ record.display_id }} «{{ record.title }}» لكن لا أحد مسند إليه. أسنده إلى أحد أعضاء مجموعتك لتنفيذه.',
  'notification_template.service_request.ready_to_fulfil.in_app':
    '{{ record.display_id }} جاهز للتنفيذ: أسنده إلى أحد',
  'notification_template.service_request.ready_to_fulfil.subject':
    'جاهز للتنفيذ: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.received.body':
    'مرحبًا {{ recipient.name }}،\n\nاستلمنا طلبك «{{ record.title }}» وسجّلناه برقم {{ record.display_id }}. سنبقيك على اطلاع.',
  'notification_template.service_request.received.in_app':
    'استلمنا {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.received.subject':
    'استلمنا طلبك {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.rejected.body':
    'مرحبًا {{ recipient.name }}،\n\nلم تتم الموافقة على طلبك {{ record.display_id }} «{{ record.title }}».{% if approval.comment %}\n\nقال الموافِق: {{ approval.comment }}{% endif %}',
  'notification_template.service_request.rejected.in_app':
    'لم تتم الموافقة على {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.rejected.subject':
    'لم تتم الموافقة: {{ record.display_id }} {{ record.title }}',
  'notification_template.service_request.withdrawn.body':
    'مرحبًا {{ recipient.name }}،\n\nسُحب طلبك {{ record.display_id }} «{{ record.title }}». لن يُتخذ بشأنه أي إجراء آخر.',
  'notification_template.service_request.withdrawn.in_app':
    'سُحب {{ record.display_id }}: {{ record.title }}',
  'notification_template.service_request.withdrawn.subject':
    'تم السحب: {{ record.display_id }} {{ record.title }}',
  'notification_template.task.assigned.body':
    'مرحبًا {{ recipient.name }}،\n\nأصبحت المهمة "{{ task.title }}" على {{ record.display_id }} "{{ record.title }}" لك الآن.',
  'notification_template.task.assigned.in_app':
    '{{ task.title }} على {{ record.display_id }} أصبحت لك',
  'notification_template.task.assigned.subject':
    'مهمة لك: {{ task.title }} ({{ record.display_id }})',
  'notification_template.task.overdue.body':
    'مرحبًا {{ recipient.name }}،\n\nكان موعد مهمتك "{{ task.title }}" على {{ record.display_id }} "{{ record.title }}" في {{ task.due_at }} وما زالت مفتوحة.',
  'notification_template.task.overdue.in_app': 'كان موعد {{ task.title }} في {{ task.due_at }}',
  'notification_template.task.overdue.subject':
    'متأخرة: {{ task.title }} ({{ record.display_id }})',
  'notification_template.task.starts_soon.body':
    'مرحبًا {{ recipient.name }}،\n\nتبدأ مهمتك "{{ task.title }}" على {{ record.display_id }} "{{ record.title }}" في {{ task.starts_at }}.',
  'notification_template.task.starts_soon.in_app': 'تبدأ {{ task.title }} في {{ task.starts_at }}',
  'notification_template.task.starts_soon.subject':
    'تبدأ قريبًا: {{ task.title }} ({{ record.display_id }})',
  'notification_variable.acknowledgement.comment': 'الإقرار › التعليق',
  'notification_variable.actor.name': 'غيّره › الاسم',
  'notification_variable.approval.comment': 'تعليق الموافِق',
  'notification_variable.approval_link': 'الموافقة › الرابط',
  'notification_variable.article.reason': 'المقالة › السبب',
  'notification_variable.article.review_on': 'المقالة › تاريخ المراجعة',
  'notification_variable.assignee.name': 'الفني › الاسم',
  'notification_variable.break_glass.person': 'مسؤول الطوارئ › الاسم',
  'notification_variable.category.name': 'الفئة',
  'notification_variable.change.from_status': 'التغيير › الحالة السابقة',
  'notification_variable.connector.name': 'الموصل › الاسم',
  'notification_variable.connector.reason': 'الموصل › السبب',
  'notification_variable.conversation.author': 'الرد أو الملاحظة › الكاتب',
  'notification_variable.conversation.excerpt': 'الرد أو الملاحظة › النص',
  'notification_variable.holder.name': 'الحامل › الاسم',
  'notification_variable.incident.count': 'عدد الحوادث',
  'notification_variable.mail.count': 'البريد › رسائل لم تُرسل',
  'notification_variable.mail.oldest_at': 'البريد › الأقدم',
  'notification_variable.mailbox.address': 'صندوق البريد › العنوان',
  'notification_variable.mailbox.expires_at': 'صندوق البريد › تنتهي بيانات الاعتماد',
  'notification_variable.mailbox.reason': 'صندوق البريد › السبب',
  'notification_variable.notice.body': 'الرسالة › النص',
  'notification_variable.notice.subject': 'الرسالة › الموضوع',
  'notification_variable.recipient.name': 'المستلم › الاسم',
  'notification_variable.record.display_id': 'السجل › المعرّف',
  'notification_variable.record.link': 'السجل › الرابط',
  'notification_variable.record.priority': 'السجل › الأولوية',
  'notification_variable.record.status': 'السجل › الحالة',
  'notification_variable.record.title': 'السجل › الموضوع',
  'notification_variable.reminder.at': 'وقت التذكير',
  'notification_variable.reminder.note': 'ملاحظة التذكير',
  'notification_variable.requester.name': 'مقدّم الطلب › الاسم',
  'notification_variable.rule.name': 'القاعدة',
  'notification_variable.site.name': 'الموقع',
  'notification_variable.sla.target': 'اتفاقية مستوى الخدمة › الهدف',
  'notification_variable.stock.minimum': 'المخزون › الحد الأدنى',
  'notification_variable.stock.quantity': 'المخزون › الكمية',
  'notification_variable.task.due_at': 'موعد استحقاق المهمة',
  'notification_variable.task.starts_at': 'البدء المجدول للمهمة',
  'notification_variable.task.title': 'عنوان المهمة',
  'notification_variable.unavailable.person': 'غير مُسند › الشخص',
  'notification_variable.unavailable.reason': 'غير مُسند › السبب',
  'notification_variable.warranty.ends_on': 'الضمان › ينتهي في',
  'notification_variable.window.start': 'بداية النافذة',
  'notifications.banner.no_mail_few':
    'تنتظر {{count}} رسائل لأن البريد الصادر غير مُعدّ. لا تزال الإشعارات داخل التطبيق تُرسل، وستُرسل الرسائل عند تشغيل البريد.',
  'notifications.banner.no_mail_many':
    'تنتظر {{count}} رسالة لأن البريد الصادر غير مُعدّ. لا تزال الإشعارات داخل التطبيق تُرسل، وستُرسل الرسائل عند تشغيل البريد.',
  'notifications.banner.no_mail_one':
    'تنتظر رسالة واحدة لأن البريد الصادر غير مُعدّ. لا تزال الإشعارات داخل التطبيق تُرسل، وستُرسل الرسالة عند تشغيل البريد.',
  'notifications.banner.no_mail_other':
    'تنتظر {{count}} رسالة لأن البريد الصادر غير مُعدّ. لا تزال الإشعارات داخل التطبيق تُرسل، وستُرسل الرسائل عند تشغيل البريد.',
  'notifications.banner.no_mail_two':
    'تنتظر رسالتان لأن البريد الصادر غير مُعدّ. لا تزال الإشعارات داخل التطبيق تُرسل، وستُرسلان عند تشغيل البريد.',
  'notifications.banner.no_mail_zero': 'لا توجد رسائل بانتظار إعداد البريد الصادر.',
  'notifications.banner.sending_few': 'يجري الآن إرسال {{count}} رسائل كانت بالانتظار.',
  'notifications.banner.sending_many': 'يجري الآن إرسال {{count}} رسالة كانت بالانتظار.',
  'notifications.banner.sending_one': 'يجري الآن إرسال رسالة واحدة كانت بالانتظار.',
  'notifications.banner.sending_other': 'يجري الآن إرسال {{count}} رسالة كانت بالانتظار.',
  'notifications.banner.sending_two': 'يجري الآن إرسال رسالتين كانتا بالانتظار.',
  'notifications.banner.sending_zero': 'لا توجد رسائل بالانتظار.',
  'notifications.banner.title': 'إشعارات البريد الإلكتروني بانتظار الإرسال',
  'notifications.do_not_disturb': 'عدم الإزعاج',
  'notifications.empty': 'لا توجد إشعارات بعد.',
  'notifications.more': 'عرض الأقدم',
  'notifications.open_few': 'الإشعارات، {{count}} إشعارات غير مقروءة',
  'notifications.open_many': 'الإشعارات، {{count}} إشعارًا غير مقروء',
  'notifications.open_one': 'الإشعارات، إشعار واحد غير مقروء',
  'notifications.open_other': 'الإشعارات، {{count}} إشعار غير مقروء',
  'notifications.open_two': 'الإشعارات، إشعاران غير مقروءين',
  'notifications.open_zero': 'الإشعارات، لا توجد إشعارات غير مقروءة',
  'notifications.read_all': 'تعليم الكل كمقروء',
  'notifications.title': 'الإشعارات',
};
