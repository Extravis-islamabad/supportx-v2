import type { LabelResource } from '../en';

// ai labels (see ../README.md).
export const ar: LabelResource = {
  'ai_area.knowledge': 'المعرفة',
  'ai_area.predictions': 'التنبؤات',
  'ai_area.summaries': 'الملخصات',
  'ai_area.writing': 'الكتابة',
  'ai_feature.conversation_summary': 'ملخص المحادثة',
  'ai_feature.possible_duplicates': 'التكرارات المحتملة',
  'ai_feature.reply_draft': 'مسودات الردود',
  'ai_feature.text_improve': 'تحسين النص وترجمته',
  'ai_outcome.accepted': 'مقبول',
  'ai_outcome.discarded': 'مرفوض',
  'ai_outcome.edited': 'معدَّل',
  'ai_settings.always_masked': 'النموذج خارج منشأتك: تُخفى البيانات الشخصية دائمًا.',
  'ai_settings.confirm_master_off': 'إيقاف الذكاء الاصطناعي للجميع؟',
  'ai_settings.confirm_off': 'إيقاف «{{feature}}»؟',
  'ai_settings.days': 'يومًا',
  'ai_settings.external': 'خارج منشأتك',
  'ai_settings.features': 'الميزات',
  'ai_settings.local': 'داخل منشأتك',
  'ai_settings.mask_local': 'إخفاء البيانات الشخصية للنموذج المحلي أيضًا',
  'ai_settings.mask_local_help':
    'تُستبدل الأسماء وعناوين البريد وأرقام الهواتف والهويات قبل أن يقرأ النموذج النص. هذا مُفعّل دائمًا لنموذج خارج منشأتك.',
  'ai_settings.master': 'استخدام الذكاء الاصطناعي',
  'ai_settings.master_help': 'إيقاف: لا تعمل أي ميزة ذكاء اصطناعي لأي شخص ولا يُستدعى أي نموذج.',
  'ai_settings.model': 'النموذج',
  'ai_settings.model_value': '{{model}} ({{where}})',
  'ai_settings.no_training':
    'لا تُستخدم محادثاتك مع الذكاء الاصطناعي أبدًا لتدريب أي نموذج. يُحتفظ بنصها للمدة أدناه فقط ثم يُحذف، وكل حذف مسجّل في سجل التدقيق.',
  'ai_settings.off_effect':
    'يؤدي الإيقاف إلى إزالة الميزة للجميع فورًا. تبقى النتائج السابقة في السجل لكنها لا تُعرض.',
  'ai_settings.privacy': 'الخصوصية',
  'ai_settings.retention': 'الاحتفاظ بنص طلبات الذكاء الاصطناعي لمدة',
  'ai_settings.retention_help':
    'بعد ذلك يُحذف نص كل طلب؛ ويبقى من استخدم أي ميزة والنتيجة للتقارير.',
  'ai_settings.saved': 'تم الحفظ.',
  'ai_settings.switch_off': 'إيقاف',
  'ai_settings.title': 'الذكاء الاصطناعي',
  'ai_summary_source.description': 'الوصف',
  'ai_summary_source.private_notes': 'الملاحظات الخاصة',
  'ai_summary_source.public_notes': 'الملاحظات العامة',
  'ai_summary_source.replies': 'الردود',
  'audit.action.ai.calls_erased': 'حُذف نص محادثات شخص مع الذكاء الاصطناعي (محو البيانات)',
  'audit.action.ai.calls_purged': 'حُذف نص محادثات الذكاء الاصطناعي بعد انتهاء مدة الاحتفاظ',
  'audit.action.ai.settings_changed': 'غيّر إعدادات الذكاء الاصطناعي',
  'audit.action.ai.summaries_erased': 'حُذفت ملخصات المحادثات التي قد تذكر شخصًا مُحيت بياناته',
  'errors.ai_call_not_found': 'إجابة الذكاء الاصطناعي هذه غير موجودة أو ليست لك.',
  'errors.ai_feature_off': 'ميزة الذكاء الاصطناعي هذه متوقفة لمؤسستك.',
  'errors.ai_record_not_visible':
    'لا يمكنك رؤية هذا السجل، لذا لا يمكن للذكاء الاصطناعي العمل عليه.',
  'errors.ai_summary_nothing': 'لا يوجد ما يُلخَّص بعد: لا وصف ولا ردود ولا ملاحظات.',
  'errors.ai_unavailable': 'نموذج الذكاء الاصطناعي لا يستجيب. حاول مرة أخرى بعد قليل.',
  'errors.field.ai_feature_unknown': 'اختر ميزات من القائمة فقط.',
  'errors.field.ai_retention_out_of_range': 'احتفظ بالنص بين يوم واحد و365 يومًا.',
  'errors.field.ai_summary_source_unknown':
    'اختر من الوصف والردود والملاحظات العامة والملاحظات الخاصة.',
  'errors.field.ai_summary_sources_empty': 'اختر جزءًا واحدًا على الأقل لتقرأه الملخصات.',
  'event_type.ai.settings.changed': 'تغيّرت إعدادات الذكاء الاصطناعي',
  'event_type.ai.summary.changed': 'أُعدّ ملخص المحادثة أو لم يعد حديثًا',
  'nav.admin_ai': 'الذكاء الاصطناعي',
  // AI gateway (WP-037).
  'permission.ai.manage': 'إدارة الذكاء الاصطناعي',
  'permission.ai.manage.description':
    'تشغيل الذكاء الاصطناعي وميزاته أو إيقافها، واختيار الإخفاء ومدة الاحتفاظ بنصوص طلبات الذكاء الاصطناعي.',
  'permission_module.ai': 'الذكاء الاصطناعي',
};
