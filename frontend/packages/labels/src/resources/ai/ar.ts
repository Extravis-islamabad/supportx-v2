import type { LabelResource } from '../en';

// ai labels (see ../README.md).
export const ar: LabelResource = {
  // AI gateway (WP-037).
  'permission.ai.manage': 'إدارة الذكاء الاصطناعي',
  'permission.ai.manage.description':
    'تشغيل الذكاء الاصطناعي وميزاته أو إيقافها، واختيار الإخفاء ومدة الاحتفاظ بنصوص طلبات الذكاء الاصطناعي.',
  'permission_module.ai': 'الذكاء الاصطناعي',
  'ai_feature.reply_draft': 'مسودات الردود',
  'ai_feature.text_improve': 'تحسين النص وترجمته',
  'ai_feature.conversation_summary': 'ملخص المحادثة',
  'ai_feature.possible_duplicates': 'التكرارات المحتملة',
  'ai_area.writing': 'الكتابة',
  'ai_area.summaries': 'الملخصات',
  'ai_area.predictions': 'التنبؤات',
  'ai_area.knowledge': 'المعرفة',
  'errors.ai_feature_off': 'ميزة الذكاء الاصطناعي هذه متوقفة لمؤسستك.',
  'errors.ai_unavailable': 'نموذج الذكاء الاصطناعي لا يستجيب. حاول مرة أخرى بعد قليل.',
  'errors.ai_call_not_found': 'إجابة الذكاء الاصطناعي هذه غير موجودة أو ليست لك.',
  'errors.field.ai_feature_unknown': 'اختر ميزات من القائمة فقط.',
  'errors.field.ai_retention_out_of_range': 'احتفظ بالنص بين يوم واحد و365 يومًا.',
  'event_type.ai.settings.changed': 'تغيّرت إعدادات الذكاء الاصطناعي',
  'audit.action.ai.settings_changed': 'غيّر إعدادات الذكاء الاصطناعي',
  'ai_settings.title': 'الذكاء الاصطناعي',
  'ai_settings.master': 'استخدام الذكاء الاصطناعي',
  'ai_settings.master_help': 'إيقاف: لا تعمل أي ميزة ذكاء اصطناعي لأي شخص ولا يُستدعى أي نموذج.',
  'ai_settings.features': 'الميزات',
  'ai_settings.off_effect':
    'يؤدي الإيقاف إلى إزالة الميزة للجميع فورًا. تبقى النتائج السابقة في السجل لكنها لا تُعرض.',
  'ai_settings.confirm_off': 'إيقاف «{{feature}}»؟',
  'ai_settings.confirm_master_off': 'إيقاف الذكاء الاصطناعي للجميع؟',
  'ai_settings.switch_off': 'إيقاف',
  'ai_settings.privacy': 'الخصوصية',
  'ai_settings.mask_local': 'إخفاء البيانات الشخصية للنموذج المحلي أيضًا',
  'ai_settings.mask_local_help':
    'تُستبدل الأسماء وعناوين البريد وأرقام الهواتف والهويات قبل أن يقرأ النموذج النص. هذا مُفعّل دائمًا لنموذج خارج منشأتك.',
  'ai_settings.always_masked': 'النموذج خارج منشأتك: تُخفى البيانات الشخصية دائمًا.',
  'ai_settings.retention': 'الاحتفاظ بنص طلبات الذكاء الاصطناعي لمدة',
  'ai_settings.retention_help':
    'بعد ذلك يُحذف نص كل طلب؛ ويبقى من استخدم أي ميزة والنتيجة للتقارير.',
  'ai_settings.days': 'يومًا',
  'ai_settings.model': 'النموذج',
  'ai_settings.model_value': '{{model}} ({{where}})',
  'ai_settings.local': 'داخل منشأتك',
  'ai_settings.external': 'خارج منشأتك',
  'ai_settings.saved': 'تم الحفظ.',
  'nav.admin_ai': 'الذكاء الاصطناعي',
  'ai_outcome.accepted': 'مقبول',
  'ai_outcome.edited': 'معدَّل',
  'ai_outcome.discarded': 'مرفوض',
  'errors.ai_record_not_visible':
    'لا يمكنك رؤية هذا السجل، لذا لا يمكن للذكاء الاصطناعي العمل عليه.',
};
