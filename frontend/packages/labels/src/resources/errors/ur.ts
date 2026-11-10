import type { LabelResource } from '../en';

// errors labels (see ../README.md).
export const ur: LabelResource = {
  'errors.action_link_expired':
    'اس لنک کی میعاد ختم ہو گئی ہے۔ اس کے بجائے درخواست ایپ میں کھولیں۔',
  'errors.action_link_not_found': 'یہ لنک درست نہیں۔',
  'errors.action_link_revoked': 'اب اس کی ضرورت نہیں: درخواست کا فیصلہ ہو چکا یا واپس لے لی گئی۔',
  'errors.action_link_sign_in_required': 'اس درخواست کو منظور یا مسترد کرنے کے لیے سائن ان کریں۔',
  'errors.action_link_stale': 'یہ لنک بھیجے جانے کے بعد درخواست بدل گئی۔ اسے ایپ میں کھولیں۔',
  'errors.action_link_used': 'یہ لنک پہلے ہی استعمال ہو چکا ہے۔',
  'errors.already_known_error': '{{display_id}} پہلے ہی معلوم خرابی ہے۔',
  'errors.already_taken': '{{taken_by}} نے ابھی اسے لے لیا ہے۔ دیکھنے کے لیے دوبارہ لوڈ کریں۔',
  'errors.already_yours': 'یہ پہلے ہی آپ کو تفویض ہے۔',
  'errors.announcement_not_found': 'یہ اعلان موجود نہیں یا آپ کے لیے دستیاب نہیں۔',
  'errors.api_key_allowlist_invalid':
    'زیادہ سے زیادہ 20 درست پتے یا نیٹ ورک درج کریں، جیسے 10.0.0.0/8۔',
  'errors.api_key_expired': 'اس API کلید کی میعاد ختم ہو گئی ہے۔',
  'errors.api_key_expiry_past': 'میعاد ختم ہونے کی تاریخ مستقبل میں ہونی چاہیے۔',
  'errors.api_key_expiry_required':
    'میعاد ختم ہونے کی تاریخ منتخب کریں: آپ کا ادارہ کبھی ختم نہ ہونے والی کلیدوں کی اجازت نہیں دیتا۔',
  'errors.api_key_expiry_too_far': 'کلید زیادہ سے زیادہ ایک سال چل سکتی ہے۔',
  'errors.api_key_invalid': 'یہ API کلید درست نہیں ہے۔',
  'errors.api_key_ip_refused': 'یہ API کلید اس پتے سے استعمال نہیں ہو سکتی۔',
  'errors.api_key_name_invalid': 'زیادہ سے زیادہ 100 حروف کا نام درج کریں۔',
  'errors.api_key_not_allowed': 'یہاں API کلیدیں استعمال نہیں ہو سکتیں: براؤزر سے سائن اِن کریں۔',
  'errors.api_key_not_found': 'یہ API کلید موجود نہیں یا آپ کی نہیں ہے۔',
  'errors.api_key_owner_inactive': 'اس API کلید کا مالک اب فعال نہیں ہے۔',
  'errors.api_key_owner_not_service': 'کسی اور کی کلید صرف سروس شناخت کی ہو سکتی ہے۔',
  'errors.api_key_revoked': 'یہ API کلید منسوخ کر دی گئی ہے۔',
  'errors.api_key_scope_unknown': 'پیش کردہ دائروں میں سے کم از کم ایک منتخب کریں۔',
  'errors.api_keys_people_off': 'آپ کا ادارہ لوگوں کو اپنی API کلیدیں بنانے کی اجازت نہیں دیتا۔',
  'errors.api_keys_unavailable': 'اس تنصیب پر API کلیدیں ترتیب نہیں دی گئیں۔',
  'errors.api_scope_missing': 'اس API کلید کے پاس دائرہ {{scope}} نہیں ہے۔',
  'errors.approval_changed': 'یہ منظوری اس دوران بدل گئی۔ اسے دوبارہ کھولیں۔',
  'errors.approval_closed': 'اس منظوری کا فیصلہ ہو چکا ہے یا اب ضرورت نہیں۔',
  'errors.approval_not_found': 'یہ منظوری نہیں ملی۔',
  'errors.approval_pending': '{{display_id}} پہلے ہی منظوری کا منتظر ہے۔',
  'errors.approval_segregation': 'آپ اپنی درخواست خود منظور نہیں کر سکتے۔',
  'errors.asset_acknowledgement_answered': 'آپ اس کا جواب پہلے ہی دے چکے ہیں۔',
  'errors.asset_acknowledgement_not_found': 'یہ تصدیق آپ کی نہیں، یا اب موجود نہیں۔',
  'errors.asset_already_disposed': 'اس اثاثے کا تلفی ریکارڈ پہلے سے موجود ہے۔',
  'errors.asset_bulk_empty': 'کم از کم ایک اثاثہ منتخب کریں۔',
  'errors.asset_bulk_too_many': 'ایک بار میں زیادہ سے زیادہ {{max}} اثاثے منتخب کریں۔',
  'errors.asset_copy_limit': 'ایک بار میں 1 سے {{max}} تک نقول بنائیں۔',
  'errors.asset_disposal_not_found': 'اس اثاثے کا کوئی تلفی ریکارڈ نہیں۔',
  'errors.asset_disposed_read_only':
    'یہ اثاثہ تلف ہو چکا ہے، اس لیے صرف پڑھا جا سکتا ہے۔ اسے بدلنے کے لیے تلف شدہ اثاثے بدلنے کی اجازت درکار ہے۔',
  'errors.asset_group_dynamic':
    'متحرک گروپ کے اراکین اس کے فلٹر سے آتے ہیں؛ اس کی بجائے فلٹر بدلیں۔',
  'errors.asset_group_name_taken': 'کسی اور گروپ کا یہی نام ہے۔',
  'errors.asset_group_not_found': 'یہ گروپ اب موجود نہیں۔',
  'errors.asset_has_components':
    'اس پر پرزے لگے ہیں ({{count}}): انہیں الگ کریں یا انہیں بھی تلف کریں۔',
  'errors.asset_life_cycle_in_use':
    'پروڈکٹ اقسام ابھی یہ لائف سائیکل استعمال کرتی ہیں ({{used}})۔ پہلے انہیں کسی اور پر منتقل کریں۔',
  'errors.asset_life_cycle_not_found': 'یہ لائف سائیکل موجود نہیں۔',
  'errors.asset_life_cycle_protected':
    'طے شدہ لائف سائیکل حذف نہیں ہو سکتا۔ پہلے کسی اور کو طے شدہ بنائیں۔',
  'errors.asset_limit_reached':
    'آپ کی تنظیم کے پلان میں آئی ٹی اثاثوں کی تمام جگہیں استعمال میں ہیں۔ کوئی اثاثہ تلف کریں یا اپنے منتظم سے مزید شامل کرنے کو کہیں۔',
  'errors.asset_link_exists': 'یہ دونوں اثاثے پہلے ہی اس طرح جڑے ہوئے ہیں۔',
  'errors.asset_link_not_found': 'یہ ربط اب موجود نہیں۔',
  'errors.asset_loan_not_found': 'یہ ادھار بند ہو چکا ہے یا اب موجود نہیں۔',
  'errors.asset_move_not_allowed': 'یہ اثاثہ اپنی موجودہ حالت سے اس حالت میں نہیں جا سکتا۔',
  'errors.asset_no_default_state':
    'اثاثے کو منتقل کرنے کے لیے کوئی طے شدہ حالت نہیں۔ کسی ایڈمن سے اثاثوں کی حالتیں دیکھنے کو کہیں۔',
  'errors.asset_no_disposed_state':
    'اثاثے کو منتقل کرنے کے لیے کوئی تلف شدہ حالت نہیں۔ کسی ایڈمن سے اثاثوں کی حالتیں دیکھنے کو کہیں۔',
  'errors.asset_not_found': 'یہ اثاثہ اب موجود نہیں، یا آپ اسے نہیں دیکھ سکتے۔',
  'errors.asset_not_loanable':
    '{{asset}} ادھار نہیں دیا جا سکتا: یہ ادھار کے قابل نہیں یا اسٹاک میں نہیں۔',
  'errors.asset_not_on_this_loan': 'یہ اثاثہ اس ادھار میں نہیں۔',
  'errors.asset_on_loan': '{{asset}} پہلے ہی ادھار پر ہے۔',
  'errors.asset_product_not_found': 'یہ پروڈکٹ موجود نہیں۔',
  'errors.asset_product_type_has_children':
    'اس کے نیچے دوسری پروڈکٹ اقسام ہیں ({{used}})۔ پہلے انہیں منتقل یا حذف کریں۔',
  'errors.asset_product_type_in_use': 'پروڈکٹس ابھی یہ قسم استعمال کرتی ہیں ({{used}})۔',
  'errors.asset_product_type_not_found': 'پروڈکٹ کی یہ قسم موجود نہیں۔',
  'errors.asset_state_in_use':
    'لائف سائیکلز کی منتقلیاں ابھی یہ حالت استعمال کرتی ہیں ({{used}})۔ پہلے انہیں ہٹائیں۔',
  'errors.asset_state_not_found': 'اثاثے کی یہ حالت موجود نہیں۔',
  'errors.asset_state_protected':
    'یہ حالت ادھار، تلفی یا اپنی کیٹیگری کی طے شدہ حالت کے طور پر استعمال ہوتی ہے، اس لیے حذف نہیں ہو سکتی۔',
  'errors.audit_archive_missing': 'آرکائیو فائل اب اسٹوریج میں موجود نہیں ہے۔',
  'errors.audit_archive_not_found': 'یہ آرکائیو موجود نہیں ہے۔',
  'errors.audit_archive_not_ready': 'صرف تصدیق شدہ آرکائیو بحال کیا جا سکتا ہے۔',
  'errors.audit_archive_not_restored': 'اس کے اندراجات پڑھنے کے لیے پہلے آرکائیو بحال کریں۔',
  'errors.audit_archive_out_of_order':
    'اس مہینے کے اندراجات غلط ترتیب میں مہر بند ہوئے؛ سپورٹ سے آڈٹ لاگ چیک کرنے کو کہیں۔',
  'errors.audit_archive_unsealed':
    'اس مہینے کے کچھ اندراجات ابھی مہر بند نہیں ہوئے، اس لیے اسے محفوظ نہیں کیا جا سکتا۔',
  'errors.audit_archive_unverified': 'اسٹوریج سے دوبارہ پڑھنے پر آرکائیو تصدیق میں ناکام رہا۔',
  'errors.audit_entry_not_found': 'یہ آڈٹ اندراج موجود نہیں ہے۔',
  'errors.audit_export_not_found': 'یہ برآمد موجود نہیں ہے۔',
  'errors.audit_export_not_ready':
    'یہ برآمد ڈاؤن لوڈ نہیں ہو سکتی (تیار نہیں، ناکام یا میعاد ختم)۔',
  'errors.audit_export_too_large': 'ایک برآمد کے لیے اندراجات بہت زیادہ ہیں۔ کم مدت منتخب کریں۔',
  'errors.auth_not_configured': 'اس انسٹالیشن کے لیے سائن اِن ترتیب نہیں دیا گیا۔',
  'errors.authentication_failed': 'میل سرور نے سائن اِن رد کر دیا۔',
  'errors.authorization_unavailable':
    'اجازتیں ابھی جانچی نہیں جا سکتیں۔ براہِ کرم تھوڑی دیر بعد دوبارہ کوشش کریں۔',
  'errors.bad_request': 'درخواست پر کارروائی نہیں ہو سکی۔',
  'errors.brand_colour_contrast':
    'یہ رنگ پڑھنے میں مشکل ہے: اس پر متن WCAG AA کنٹراسٹ سے کم ہے۔ تجویز کردہ رنگ استعمال کریں یا گہرا رنگ چنیں۔',
  'errors.branding_not_found': 'یہ برانڈ نہیں ملا۔',
  'errors.bulk_job_not_found': 'یہ اجتماعی تبدیلی نہیں ملی۔',
  'errors.calendar_in_use':
    'سائٹس یا سپورٹ گروپس ابھی یہ کیلنڈر استعمال کرتے ہیں۔ پہلے انہیں دوسرا کیلنڈر دیں۔',
  'errors.calendar_not_found': 'یہ کیلنڈر موجود نہیں یا حذف ہو چکا ہے۔',
  'errors.cannot_deactivate_self': 'آپ خود کو غیر فعال نہیں کر سکتے۔',
  'errors.cannot_publish': 'یہ اعلان ابھی شائع نہیں کیا جا سکتا۔',
  'errors.cannot_stop_own_sign_in': 'آپ اپنا سائن اِن خود بند نہیں کر سکتے۔',
  'errors.catalog_item_in_use':
    'اس آئٹم کی درخواستیں موجود ہیں، اس لیے اسے حذف نہیں کیا جا سکتا۔ اس کے بجائے اسے ختم کریں۔',
  'errors.catalog_item_incomplete': 'طے شدہ وقت پر آئٹم مکمل نہیں تھا، اس لیے یہ مسودہ ہی رہا۔',
  'errors.catalog_item_not_found': 'یہ کیٹلاگ آئٹم موجود نہیں یا آپ کے لیے دستیاب نہیں۔',
  'errors.category_not_found': 'یہ زمرہ موجود نہیں۔',
  'errors.certificate_invalid':
    'سرٹیفکیٹ پڑھا نہیں جا سکا۔ PEM کو اس کی پرائیویٹ کی کے ساتھ پیسٹ کریں۔',
  'errors.certificate_key_mismatch': 'نجی کلید اس سرٹیفکیٹ کی نہیں ہے۔',
  'errors.certificate_not_valid_now': 'سرٹیفکیٹ کی میعاد ختم ہو چکی ہے یا ابھی درست نہیں ہوا۔',
  'errors.certificate_unreadable': 'سرٹیفکیٹ پڑھا نہیں جا سکا: اسے PEM فارمیٹ میں چسپاں کریں۔',
  'errors.certificate_wrong_host': 'سرٹیفکیٹ میں یہ ڈومین شامل نہیں ہے۔',
  'errors.change_source_not_found': 'وہ ریکارڈ نہیں ملا جس کے لیے یہ تبدیلی بنائی گئی۔',
  'errors.client_id_invalid': 'سنک ایپ کی ایپلیکیشن (کلائنٹ) آئی ڈی درج کریں۔',
  'errors.closure_rules': 'یہ کرنے سے پہلے کچھ چیزیں درکار ہیں۔',
  'errors.conflict':
    'کسی اور نے یہ آئٹم تبدیل کر دیا۔ تازہ ترین ورژن دیکھنے کے لیے دوبارہ لوڈ کریں۔',
  'errors.console_requester_only': 'یہ اکاؤنٹ درخواست گزار پورٹل استعمال کرتا ہے، کنسول نہیں۔',
  'errors.contact_editing_off':
    'آپ کی تنظیم یہاں رابطے کی تفصیلات بدلنے کی اجازت نہیں دیتی۔ سروس ڈیسک سے پوچھیں۔',
  'errors.conversation_entry_not_found': 'یہ جواب یا نوٹ اب موجود نہیں ہے۔',
  'errors.copy_reference': 'حوالہ کاپی کریں',
  'errors.csrf_failed':
    'اس درخواست کی تصدیق نہیں ہو سکی۔ براہِ کرم صفحہ دوبارہ لوڈ کر کے پھر کوشش کریں۔',
  'errors.currency_change_needs_confirmation':
    'بنیادی کرنسی بدلنے کے لیے تصدیق درکار ہے: پہلے سے درج رقمیں پرانی کرنسی میں رہیں گی۔',
  'errors.custom_field_entity_not_found': 'اس قسم کے ریکارڈ کے لیے اپنی مرضی کے خانے دستیاب نہیں۔',
  'errors.custom_field_in_use':
    'ریکارڈز میں اس خانے کی قدریں موجود ہیں۔ پرانے ریکارڈز پر رکھنے کے لیے اسے ریٹائر کریں، یا ہٹا دیں: پرانی قدریں تاریخچے میں رہیں گی۔',
  'errors.custom_field_limit_reached':
    'اس قسم کے ریکارڈ میں پہلے ہی {{limit}} اپنی مرضی کے خانے ہیں، جو زیادہ سے زیادہ حد ہے۔ پہلے کوئی خانہ ہٹائیں یا دوبارہ استعمال کریں۔',
  'errors.custom_field_not_found': 'یہ اپنی مرضی کا خانہ موجود نہیں (اب نہیں رہا)۔',
  'errors.custom_field_used_by_rule':
    'آٹومیشن اصول یہ فیلڈ استعمال کرتے ہیں ({{rules}})۔ پہلے وہ اصول بدلیں یا ہٹائیں۔',
  'errors.dashboard_not_editable':
    'صرف اس کا مالک یہ ڈیش بورڈ بدل سکتا ہے۔ اپنی نقل بنانے کے لیے اسے کاپی کریں۔',
  'errors.dashboard_not_found': 'یہ ڈیش بورڈ موجود نہیں یا آپ کے ساتھ شیئر نہیں ہے۔',
  'errors.database_not_configured':
    'سروس ابھی مکمل طور پر ترتیب نہیں دی گئی۔ براہِ کرم اپنے منتظم سے رابطہ کریں۔',
  'errors.default_board_kept':
    'تبدیلیوں کا طے شدہ مشاورتی بورڈ ہٹایا نہیں جا سکتا۔ جن تبدیلیوں کا جائزہ کوئی اور بورڈ نہیں لیتا، وہ اسی کے پاس جاتی ہیں۔',
  'errors.default_site_required':
    'ڈیفالٹ سائٹ ہٹائی نہیں جا سکتی۔ پہلے کسی اور سائٹ کو ڈیفالٹ بنائیں۔',
  'errors.delivery_not_failed': 'یہ جواب ناکام نہیں ہوا، اس لیے دوبارہ بھیجنے کو کچھ نہیں۔',
  'errors.department_not_found': 'یہ شعبہ اب موجود نہیں۔',
  'errors.desk_limit_reached': 'آپ کا لائسنس مزید ڈیسک کی اجازت نہیں دیتا۔',
  'errors.directory_disabled': 'یہ ڈائریکٹری بند ہے۔ سنک کے لیے اسے آن کریں۔',
  'errors.directory_group_invalid':
    'ڈائریکٹری کا ایک گروپ درست نہیں۔ اسے فہرست سے دوبارہ منتخب کریں۔',
  'errors.directory_groups_required': 'سنک کرنے کے لیے کم از کم ایک گروپ منتخب کریں۔',
  'errors.directory_name_taken': 'اس نام کی ایک اور ڈائریکٹری پہلے سے موجود ہے۔',
  'errors.directory_not_found': 'ڈائریکٹری نہیں ملی۔',
  'errors.directory_secret_missing':
    'کوئی کارآمد کلائنٹ سیکرٹ یا سرٹیفکیٹ محفوظ نہیں۔ اسے دوبارہ درج کریں۔',
  'errors.directory_tenant_invalid': 'ڈائریکٹری کی ٹیننٹ آئی ڈی یا اس کا بنیادی ڈومین درج کریں۔',
  'errors.directory_unavailable':
    'ڈائریکٹری نے جواب نہیں دیا یا سنک ایپ کو مسترد کر دیا۔ تھوڑی دیر بعد دوبارہ کوشش کریں۔',
  'errors.domain_address_not_allowed':
    'ڈومین ایسے پتے کی طرف اشارہ کرتا ہے جس سے SupportX رابطہ نہیں کرتا۔',
  'errors.domain_check_failed': 'ڈومین نے جواب دیا، مگر اس SupportX کی طرح نہیں۔',
  'errors.domain_invalid': 'help.example.com جیسا ڈومین نام درج کریں۔',
  'errors.domain_limit': 'آپ زیادہ سے زیادہ {{max}} ڈومین شامل کر سکتے ہیں۔',
  'errors.domain_not_found': 'یہ ڈومین نہیں ملا۔',
  'errors.domain_not_reachable': 'ڈومین تک رسائی نہیں ہو سکی۔',
  'errors.domain_not_resolving': 'ڈومین کا ابھی کوئی DNS ریکارڈ نہیں ہے۔',
  'errors.domain_reserved': 'اس انسٹالیشن کے اپنے ڈومین کے پتے خودکار طور پر دیے جاتے ہیں۔',
  'errors.domain_taken': 'یہ ڈومین پہلے سے استعمال میں ہے۔',
  'errors.domain_wrong_answer':
    'ڈومین ابھی اس SupportX کی طرف اشارہ نہیں کرتا: اس کا DNS ریکارڈ دیکھیں۔',
  'errors.domains_not_configured': 'اس انسٹالیشن پر کسٹم ڈومین ترتیب نہیں دیے گئے۔',
  'errors.downtime_not_found': 'یہ بندش کا وقفہ موجود نہیں۔',
  'errors.entitlement_required': 'آپ کے پلان میں یہ خصوصیت شامل نہیں۔',
  'errors.entitlement_required.detail': '{{feature}} آپ کے ادارے کے پلان کا حصہ نہیں۔',
  'errors.entitlements_unavailable':
    'لائسنس کی معلومات عارضی طور پر دستیاب نہیں۔ براہِ کرم تھوڑی دیر بعد دوبارہ کوشش کریں۔',
  'errors.field.above_maximum': 'زیادہ سے زیادہ {{max}} ہے۔',
  'errors.field.already_linked': 'یہ ریکارڈ پہلے سے منسلک ہیں۔',
  'errors.field.announcement_message_required': 'وہ پیغام لکھیں جو لوگ دیکھیں گے۔',
  'errors.field.api_key_allowlist_invalid':
    'زیادہ سے زیادہ 20 درست پتے یا نیٹ ورک درج کریں، جیسے 10.0.0.0/8۔',
  'errors.field.api_key_expiry_past': 'میعاد ختم ہونے کی تاریخ مستقبل میں ہونی چاہیے۔',
  'errors.field.api_key_expiry_required':
    'میعاد ختم ہونے کی تاریخ منتخب کریں: آپ کا ادارہ کبھی ختم نہ ہونے والی کلیدوں کی اجازت نہیں دیتا۔',
  'errors.field.api_key_expiry_too_far': 'کلید زیادہ سے زیادہ ایک سال چل سکتی ہے۔',
  'errors.field.api_key_name_invalid': 'زیادہ سے زیادہ 100 حروف کا نام درج کریں۔',
  'errors.field.api_key_owner_not_service': 'کسی اور کی کلید صرف سروس شناخت کی ہو سکتی ہے۔',
  'errors.field.api_key_scope_unknown': 'پیش کردہ دائروں میں سے کم از کم ایک منتخب کریں۔',
  'errors.field.approver_is_requester': 'آپ اپنی درخواست منظور نہیں کر سکتے؛ کسی اور کا نام دیں۔',
  'errors.field.approver_not_active': 'کوئی فعال فرد چنیں۔',
  'errors.field.approver_not_eligible':
    'نامزد افراد میں سے کوئی یہ مسئلہ منظور نہیں کر سکتا (غیر فعال، یا اختیار کے بغیر)۔',
  'errors.field.asset_api_name_taken': 'پروڈکٹ کی کوئی اور قسم یہ API نام رکھتی ہے۔',
  'errors.field.asset_group_static': 'صرف متحرک گروپ کا فلٹر ہوتا ہے۔',
  'errors.field.asset_holder_not_found':
    'کوئی فعال فرد، شعبہ یا ایسا اثاثہ چنیں جو آپ دیکھ سکتے ہیں۔',
  'errors.field.asset_identifier_invalid':
    'صرف حروف، ہندسے اور - . / : # استعمال کریں، خالی جگہ کے بغیر۔',
  'errors.field.asset_life_cycle_code_taken': 'کوئی اور لائف سائیکل یہ کوڈ رکھتا ہے۔',
  'errors.field.asset_life_cycle_default_needed':
    'ایک طے شدہ لائف سائیکل لازمی ہے۔ اس کے بجائے کسی اور کو طے شدہ بنائیں۔',
  'errors.field.asset_life_cycle_not_found': 'فہرست سے لائف سائیکل منتخب کریں۔',
  'errors.field.asset_link_to_itself': 'اثاثہ خود سے نہیں جوڑا جا سکتا۔',
  'errors.field.asset_move_duplicate': 'یہ منتقلی پہلے سے فہرست میں ہے، یا اسی حالت میں جاتی ہے۔',
  'errors.field.asset_nested_in_itself': 'اثاثہ خود پر یا اپنے کسی حصے پر نہیں لگایا جا سکتا۔',
  'errors.field.asset_product_not_found': 'یہ پروڈکٹ اب موجود نہیں۔',
  'errors.field.asset_product_type_cycle':
    'پروڈکٹ کی قسم خود اپنے یا اپنی ذیلی قسم کے نیچے نہیں آ سکتی۔',
  'errors.field.asset_product_type_inherited': 'یہ والدین قسم سے آتا ہے۔ اسے وہاں تبدیل کریں۔',
  'errors.field.asset_product_type_not_found': 'فہرست سے پروڈکٹ کی قسم منتخب کریں۔',
  'errors.field.asset_product_type_too_deep': 'درخت زیادہ سے زیادہ {{max}} درجے گہرا ہو سکتا ہے۔',
  'errors.field.asset_serial_number_taken': 'اثاثہ {{asset}} کے پاس پہلے سے یہ سیریل نمبر ہے۔',
  'errors.field.asset_state_code_taken': 'کوئی اور حالت یہ کوڈ رکھتی ہے۔',
  'errors.field.asset_state_default_needed':
    'ہر کیٹیگری کو ایک طے شدہ حالت چاہیے۔ اس کے بجائے کسی اور حالت کو طے شدہ بنائیں۔',
  'errors.field.asset_state_not_found': 'فہرست سے حالتیں منتخب کریں۔',
  'errors.field.asset_state_system':
    'ادھار اور تلفی اس حالت پر انحصار کرتے ہیں، اس لیے اس کی کیٹیگری برقرار رہتی ہے۔',
  'errors.field.asset_tag_pattern_invalid':
    'کاؤنٹر {n} ایک بار، اس کے ساتھ کچھ متن کے ساتھ استعمال کریں، مثلاً AST-{n}۔',
  'errors.field.asset_tag_taken': 'اثاثہ {{asset}} کے پاس پہلے سے یہ ٹیگ ہے۔',
  'errors.field.auto_close_needs_notifications':
    'خودکار بندش کے لیے درخواست گزاروں کو اطلاعات درکار ہیں: ابھی کوئی ذریعہ درخواست گزاروں کو حل کی اطلاع نہیں دے سکتا۔',
  'errors.field.before_publish': 'ختم کرنے کا وقت شائع کرنے کے بعد ہونا چاہیے۔',
  'errors.field.before_start': 'اختتام آغاز سے پہلے نہیں ہو سکتا۔',
  'errors.field.below_minimum': 'کم از کم {{min}} ہے۔',
  'errors.field.board_not_found': 'یہ مشاورتی بورڈ موجود نہیں۔',
  'errors.field.brand_image_svg':
    'SVG تصاویر قبول نہیں کی جاتیں کیونکہ ان میں اسکرپٹ ہو سکتے ہیں۔ PNG، JPEG، WebP یا ICO فائل استعمال کریں۔',
  'errors.field.brand_image_too_large': 'یہ تصویر بہت بڑی ہے: زیادہ سے زیادہ 5 MB اور 25 میگاپکسل۔',
  'errors.field.brand_image_too_small': 'یہ تصویر بہت چھوٹی ہے: ہر طرف کم از کم 16 پکسل۔',
  'errors.field.brand_image_unreadable':
    'یہ تصویر پڑھی نہیں جا سکی۔ PNG، JPEG، WebP یا ICO فائل استعمال کریں۔',
  'errors.field.bucket_not_allowed':
    'صرف تاریخ والی فیلڈز کو دن، ہفتے یا مہینے کے مطابق گروپ کیا جا سکتا ہے۔',
  'errors.field.bucket_required':
    'تاریخوں کو گروپ کرنے کا طریقہ منتخب کریں: دن، ہفتہ، مہینہ، سہ ماہی، سال یا عمر۔',
  'errors.field.builtin_type_names': 'پہلے سے موجود قسم کے نام نہیں بدلتے۔',
  'errors.field.calendar_not_found': 'فہرست سے کیلنڈر منتخب کریں۔',
  'errors.field.cannot_link_itself': 'ریکارڈ کو خود سے منسلک نہیں کیا جا سکتا۔',
  'errors.field.cannot_merge_itself': 'کسی مسئلے کو خود میں ضم نہیں کیا جا سکتا۔',
  'errors.field.cannot_see_record':
    'یہ شخص یہ ریکارڈ نہیں دیکھ سکتا، اس لیے اسے فالو نہیں کر سکتا۔',
  'errors.field.catalog_item_not_found': 'کیٹلاگ سے ایسا آئٹم منتخب کریں جو آپ کے لیے دستیاب ہو۔',
  'errors.field.catalog_too_deep': 'کیٹلاگ کیٹیگریز کے زیادہ سے زیادہ چار درجے ہو سکتے ہیں۔',
  'errors.field.category_disabled': 'یہ زمرہ اب استعمال میں نہیں۔',
  'errors.field.category_loop':
    'کوئی کیٹیگری خود اپنے اندر یا اپنی ذیلی کیٹیگری کے اندر نہیں رکھی جا سکتی۔',
  'errors.field.category_not_found': 'یہ زمرہ موجود نہیں۔',
  'errors.field.certificate_key_mismatch': 'نجی کلید اس سرٹیفکیٹ کی نہیں ہے۔',
  'errors.field.certificate_not_valid_now':
    'سرٹیفکیٹ کی میعاد ختم ہو چکی ہے یا ابھی درست نہیں ہوا۔',
  'errors.field.certificate_unreadable':
    'سرٹیفکیٹ پڑھا نہیں جا سکا: اسے PEM فارمیٹ میں چسپاں کریں۔',
  'errors.field.certificate_wrong_host': 'سرٹیفکیٹ میں یہ ڈومین شامل نہیں ہے۔',
  'errors.field.channel_reserved':
    'صرف فون یا بالمشافہ چنا جا سکتا ہے؛ دوسرے ذرائع خود بخود طے ہوتے ہیں۔',
  'errors.field.choices_required': 'کم از کم ایک انتخاب شامل کریں۔',
  'errors.field.code_taken': 'یہ کوڈ پہلے سے استعمال میں ہے۔',
  'errors.field.comment_required': 'تبصرہ شامل کریں: اس آئٹم کے لیے تبصرہ لازمی ہے۔',
  'errors.field.condition_not_supported': 'اس اجازت کے لیے ابھی قواعد دستیاب نہیں۔',
  'errors.field.country_invalid': 'فہرست میں سے ملک چنیں۔',
  'errors.field.currency_unknown': 'فہرست میں سے کرنسی چنیں۔',
  'errors.field.dashboard_not_shared':
    'کسی کردار کا ہوم صرف بلٹ اِن یا شیئر شدہ ڈیش بورڈ ہو سکتا ہے۔',
  'errors.field.date_format_unknown': 'فہرست میں سے تاریخ کی شکل چنیں۔',
  'errors.field.date_in_future': 'آج یا اس سے پہلے کی تاریخ چنیں۔',
  'errors.field.date_in_past': 'ابھی کے بعد کا وقت چنیں۔',
  'errors.field.default_cannot_be_disabled':
    'ڈیفالٹ سانچہ بند نہیں ہو سکتا۔ پہلے کسی اور سانچے کو ڈیفالٹ بنائیں۔',
  'errors.field.default_cannot_be_inactive': 'ڈیفالٹ کو غیر فعال نہیں کیا جا سکتا۔',
  'errors.field.default_cannot_be_removed':
    'طے شدہ اصول ہٹایا نہیں جا سکتا۔ اس کے بجائے اسے بند کریں۔',
  'errors.field.default_language_not_offered':
    'پہلے سے طے شدہ زبان دستیاب زبانوں میں سے ہونی چاہیے۔',
  'errors.field.default_required':
    'ہمیشہ ایک ڈیفالٹ سانچہ ہوتا ہے۔ اس کے بجائے کسی اور سانچے کو ڈیفالٹ بنائیں۔',
  'errors.field.department_not_found': 'کوئی فعال شعبہ منتخب کریں۔',
  'errors.field.desk_not_found': 'کوئی فعال ڈیسک منتخب کریں۔',
  'errors.field.dimension_not_groupable':
    'متعدد انتخاب والی فیلڈز ابھی گروپ بندی کے لیے استعمال نہیں ہو سکتیں۔',
  'errors.field.disabled_cannot_be_default': 'ڈیفالٹ بنانے سے پہلے یہ سانچہ آن کریں۔',
  'errors.field.domain_invalid': 'help.example.com جیسا ڈومین نام درج کریں۔',
  'errors.field.domain_reserved': 'اس انسٹالیشن کے اپنے ڈومین کے پتے خودکار طور پر دیے جاتے ہیں۔',
  'errors.field.due_in_past': 'مستقبل کا کوئی وقت منتخب کریں۔',
  'errors.field.duplicate': 'یہ پہلے سے استعمال میں ہے۔',
  'errors.field.duplicate_column': 'ہر کالم ایک بار درج کیا جا سکتا ہے۔',
  'errors.field.duplicate_dimension': 'یہ گروپ بندی پہلے سے استعمال میں ہے۔',
  'errors.field.duplicate_measure': 'ہر پیمانہ ایک ہی بار استعمال ہو سکتا ہے۔',
  'errors.field.duplicate_name': 'یہ نام پہلے سے استعمال میں ہے۔',
  'errors.field.duplicate_permission': 'یہ اجازت دو بار درج ہے۔',
  'errors.field.duplicate_sort_field': 'ترتیب میں ہر فیلڈ صرف ایک بار استعمال ہو سکتی ہے۔',
  'errors.field.duplicate_value': 'یہ ایک سے زیادہ بار درج ہے۔',
  'errors.field.duration_mismatch': 'دورانیہ آغاز اور اختتام کے اوقات سے میل نہیں کھاتا۔',
  'errors.field.email_invalid': 'name@example.com جیسا ای میل پتہ درج کریں۔',
  'errors.field.email_not_valid': 'ای میل پتہ درج کریں، جیسے name@example.com۔',
  'errors.field.email_required_for_sign_in':
    'سائن اِن کے لیے ای میل ضروری ہے۔ ای میل شامل کریں یا اس فرد کو رابطہ بنائیں۔',
  'errors.field.email_taken': 'یہ ای میل کوئی اور فرد استعمال کر رہا ہے۔',
  'errors.field.employee_id_taken': 'یہ ملازم آئی ڈی کسی اور فرد کی ہے۔',
  'errors.field.end_before_start': 'اختتامی تاریخ آغاز کی تاریخ سے پہلے ہے۔',
  'errors.field.end_or_duration_required': 'اختتامی وقت یا دورانیہ درج کریں۔',
  'errors.field.english_label_required': 'انگریزی نام ضروری ہے۔',
  'errors.field.english_text_required':
    'انگریزی متن شامل کریں: جہاں ترجمہ نہ ہو وہاں یہی دکھایا جاتا ہے۔',
  'errors.field.exception_range_order': 'آخری دن پہلے دن کے برابر یا اس کے بعد ہونا چاہیے۔',
  'errors.field.exception_range_too_long':
    'مخصوص اوقات زیادہ سے زیادہ ایک سال پر محیط ہو سکتے ہیں۔',
  'errors.field.exception_ranges_overlap':
    'یہ تاریخیں اس کیلنڈر کے دوسرے مخصوص اوقات سے ٹکراتی ہیں۔ تاریخیں بدلیں یا دوسری مدت میں ترمیم کریں۔',
  'errors.field.expiry_before_review': 'ختم ہونے کی تاریخ جائزے کی تاریخ کے بعد ہونی چاہیے۔',
  'errors.field.fallback_fixed': 'ڈیفالٹ پالیسی ہمیشہ لاگو ہوتی ہے اور اس کی کوئی شرائط نہیں۔',
  'errors.field.field_always_required':
    'موضوع اور درخواست گزار ہمیشہ دکھائے جاتے ہیں اور لازمی ہیں۔',
  'errors.field.field_not_settable': 'قاعدہ یہ فیلڈ مقرر نہیں کر سکتا۔',
  'errors.field.field_retired': 'یہ خانہ ریٹائر ہو چکا ہے اور نئی قدریں نہیں لیتا۔',
  'errors.field.field_set_twice': 'یہ فیلڈ قاعدے کے کسی اور عمل سے پہلے ہی مقرر ہے۔',
  'errors.field.fill_needs_see': 'درخواست گزار صرف وہی فیلڈ بھر سکتے ہیں جو وہ دیکھ سکیں۔',
  'errors.field.filter_too_deep': 'فلٹر میں بہت زیادہ اندرونی گروپ ہیں۔',
  'errors.field.filter_too_large': 'فلٹر بہت بڑا ہے۔',
  'errors.field.fixed_calendar_required': 'استعمال ہونے والا کیلنڈر منتخب کریں۔',
  'errors.field.fixed_calendar_unused': 'کیلنڈر صرف تب منتخب ہوتا ہے جب ماخذ مقررہ کیلنڈر ہو۔',
  'errors.field.flow_not_available': 'اس قسم کے ریکارڈ کی درج بمقابلہ حل شدہ رپورٹ دستیاب نہیں۔',
  'errors.field.flow_without_groupings': 'درج بمقابلہ حل شدہ رپورٹ میں گروپ بندی نہیں ہوتی۔',
  'errors.field.fulfiller_required': 'پہلے یہ درخواست کسی کو تفویض کریں تاکہ وہ اسے مکمل کرے۔',
  'errors.field.full_sla_off':
    'مسائل کے لیے صرف ہدف کی تاریخیں ہیں۔ جواب کے اہداف شامل کرنے کے لیے مسائل پر مکمل SLA آن کریں۔',
  'errors.field.group_not_found': 'یہ گروپ موجود نہیں۔',
  'errors.field.group_not_yours': 'آپ اس گروپ کے رکن نہیں۔',
  'errors.field.group_required': 'چنیں کہ آپ کا کون سا گروپ اسے لے گا۔',
  'errors.field.half_day_single_date': 'صبح یا دوپہر کی چھٹی صرف ایک دن کی ہوتی ہے۔',
  'errors.field.hidden_cannot_be_required':
    'چھپی ہوئی فیلڈ لازمی نہیں ہو سکتی: اسے کوئی بھر نہیں سکے گا۔',
  'errors.field.hidden_required_needs_default':
    'چھپے لازمی فیلڈ کو ابتدائی قدر درکار ہے، ورنہ کوئی اسے بھر نہیں سکے گا۔',
  'errors.field.holiday_list_not_found': 'فہرست سے تعطیلات کی فہرستیں منتخب کریں۔',
  'errors.field.holiday_range_order': 'آخری دن پہلے دن کے برابر یا اس کے بعد ہونا چاہیے۔',
  'errors.field.holiday_range_too_long': 'ایک تعطیل زیادہ سے زیادہ ایک سال لمبی ہو سکتی ہے۔',
  'errors.field.ical_invalid': 'یہ iCalendar (.ics) فائل نہیں ہے۔',
  'errors.field.ical_not_utf8': 'یہ فائل ٹیکسٹ کیلنڈر فائل (UTF-8) نہیں ہے۔',
  'errors.field.ical_too_large': 'فائل 1 MB سے بڑی ہے۔',
  'errors.field.ical_too_many_lines': 'فائل میں 20,000 سے زیادہ سطریں ہیں۔',
  'errors.field.invalid_choice': 'یہ اجازت یافتہ قدروں میں سے نہیں ہے۔',
  'errors.field.invalid_code': 'حروف، اعداد، نقطے یا ڈیش استعمال کریں (زیادہ سے زیادہ 50)۔',
  'errors.field.invalid_colour': '#1677ff جیسا رنگ منتخب کریں۔',
  'errors.field.invalid_currency': 'تین حرفی کرنسی کوڈ استعمال کریں، جیسے USD یا PKR۔',
  'errors.field.invalid_date': 'تاریخ درج کریں۔',
  'errors.field.invalid_email': 'یہ پتے درست نہیں ہیں: {{addresses}}',
  'errors.field.invalid_group': 'گروپ میں کم از کم ایک شرط ہونی چاہیے۔',
  'errors.field.invalid_json': 'فلٹر درست نہیں ہے۔',
  'errors.field.invalid_key': 'خانے کو ایسا نام دیں جس میں کم از کم دو حروف یا ہندسے ہوں۔',
  'errors.field.invalid_language':
    'نام انگریزی، عربی اور اردو میں دیے جا سکتے ہیں، ہر ایک 200 حروف تک۔',
  'errors.field.invalid_node': 'فلٹر کا یہ حصہ نہ شرط ہے نہ گروپ۔',
  'errors.field.invalid_number': 'عدد درج کریں۔',
  'errors.field.invalid_pattern': 'یہ پیٹرن درست ریگولر ایکسپریشن نہیں ہے۔',
  'errors.field.invalid_phone': 'فون نمبر درج کریں: ہندسے، خالی جگہیں، +، - اور قوسین۔',
  'errors.field.invalid_prefix': '2 سے 6 بڑے انگریزی حروف استعمال کریں۔',
  'errors.field.invalid_range': 'حد کا آغاز اس کے اختتام کے بعد ہے۔',
  'errors.field.invalid_sort': 'ترتیب کے لیے ایک سے تین فیلڈز منتخب کریں۔',
  'errors.field.invalid_tag': 'ٹیگ میں حروف، ہندسے، خالی جگہ، نقطے اور ڈیش ہو سکتے ہیں (40 تک)۔',
  'errors.field.invalid_text': 'متن درج کریں۔',
  'errors.field.invalid_value': 'یہ قدر درست نہیں۔',
  'errors.field.invalid_website': 'http:// یا https:// سے شروع ہونے والا ویب پتہ درج کریں۔',
  'errors.field.invitation_days_out_of_range': '{{min}} اور {{max}} دن کے درمیان رکھیں۔',
  'errors.field.kb_vote_comment_too_long': 'تبصرہ 1,000 حروف تک رکھیں۔',
  'errors.field.kb_vote_reason_for_no_only': 'وجہ صرف «نہیں» کے ساتھ دی جاتی ہے۔',
  'errors.field.kb_vote_reason_unknown': 'پیش کردہ وجوہات میں سے ایک منتخب کریں۔',
  'errors.field.key_cannot_change': 'خانے کا API نام تبدیل نہیں ہو سکتا۔',
  'errors.field.languages_invalid': 'انگریزی ہمیشہ دستیاب ہے؛ عربی اور اردو میں سے بھی چنیں۔',
  'errors.field.last_value': 'کم از کم ایک قدر استعمال میں رہنی چاہیے۔',
  'errors.field.level_does_nothing':
    'یہ درجہ نہ کسی کو بتاتا ہے نہ کچھ کرتا ہے۔ وصول کنندگان یا کوئی کارروائی شامل کریں۔',
  'errors.field.level_too_many_actions': 'ہر درجے کے لیے زیادہ سے زیادہ {{max}} کارروائیاں۔',
  'errors.field.level_too_many_recipients': 'ہر درجے کے لیے زیادہ سے زیادہ {{max}} وصول کنندگان۔',
  'errors.field.levels_same_moment': 'دو درجے ایک ہی وقت پر چلتے ہیں۔ ہر ایک کو اپنا وقت دیں۔',
  'errors.field.limited_template_for_requesters':
    'درخواست گزاروں کا سانچہ سب کے لیے ہے: اسے گروپوں تک محدود نہیں کیا جا سکتا۔',
  'errors.field.list_too_long': 'اس فہرست میں بہت زیادہ قدریں ہیں۔',
  'errors.field.logo_required': 'پہلے لوگو اپ لوڈ کریں۔',
  'errors.field.mailbox_address_invalid': 'میل باکس کا ای میل پتہ درج کریں۔',
  'errors.field.mailbox_auth_model_unsupported': 'اس قسم کے میل باکس کے لیے دستیاب نہیں۔',
  'errors.field.managed_by_directory': 'یہ فیلڈ آپ کی ڈائریکٹری رکھتی ہے۔ اسے وہیں تبدیل کریں۔',
  'errors.field.manager_loop':
    'یہ فرد پہلے ہی اس مینیجر کا مینیجر ہے (براہِ راست یا دوسروں کے ذریعے)۔',
  'errors.field.matrix_incomplete': 'اثر اور فوریت کے ہر جوڑے کو ترجیح درکار ہے۔',
  'errors.field.measure_not_available': 'یہ پیمانہ ابھی دستیاب نہیں۔',
  'errors.field.message_required': 'کم از کم انگریزی میں پیغام لکھیں۔',
  'errors.field.mfa_grace_out_of_range': '{{min}} اور {{max}} دن کے درمیان رکھیں۔',
  'errors.field.mfa_mode_invalid': 'بند، اختیاری یا لازمی منتخب کریں۔',
  'errors.field.month_out_of_range': 'فہرست میں سے مہینہ چنیں۔',
  'errors.field.move_articles_first': 'اس موضوع میں ابھی مضامین ہیں۔ منتخب کریں کہ وہ کہاں جائیں۔',
  'errors.field.must_be_future': 'مستقبل کا کوئی وقت منتخب کریں۔',
  'errors.field.my_groups_in_records':
    'فہرست "میرے گروپ" استعمال نہیں کر سکتی۔ چارٹ استعمال کریں یا گروپ منتخب کریں۔',
  'errors.field.name_needs_letters': 'نام میں کم از کم ایک حرف یا ہندسہ استعمال کریں۔',
  'errors.field.name_required': 'نام درج کریں۔',
  'errors.field.name_taken': 'یہ نام پہلے سے استعمال میں ہے۔',
  'errors.field.no_default_allowed': 'اس فیلڈ کی ابتدائی قدر نہیں ہو سکتی۔',
  'errors.field.not_a_field': 'اس قسم کے لیے یہ فیلڈ موجود نہیں۔',
  'errors.field.not_a_technician':
    'صرف وہی ٹیکنیشن جو مسائل پر کام کرتا ہے کسی مسئلے کی تفتیش کر سکتا ہے۔',
  'errors.field.not_allowed': 'یہ دوسری اقدار کے ساتھ اجازت شدہ نہیں۔',
  'errors.field.not_allowed_for_notes': 'نوٹس کے وصول کنندگان نہیں ہوتے۔',
  'errors.field.not_eligible': 'یہ شخص یا گروپ یہ کردار نہیں رکھ سکتا۔',
  'errors.field.not_for_this_status': 'یہ ترتیب صرف ان حالتوں کے لیے ہے جو کسی کا انتظار کرتی ہیں۔',
  'errors.field.not_found': 'یہ اب موجود نہیں۔',
  'errors.field.not_in_past': 'یہ وقت ماضی کا ہونا چاہیے۔',
  'errors.field.note_too_long': 'نوٹ زیادہ سے زیادہ {{max}} حروف کا ہو سکتا ہے۔',
  'errors.field.number_already_used':
    'یہ نمبر پہلے ہی استعمال ہو چکا ہے۔ {{minimum}} یا اس سے زیادہ منتخب کریں۔',
  'errors.field.oauth_certificate_invalid':
    'سرٹیفکیٹ اور اس کی RSA پرائیویٹ کی، دونوں PEM میں چسپاں کریں۔',
  'errors.field.offset_too_large':
    'کوئی درجہ اپنے نقطۂ آغاز سے زیادہ سے زیادہ 30 کاروباری دن دور ہو سکتا ہے۔',
  'errors.field.one_day_required': 'ہفتے کا ایک دن منتخب کریں۔',
  'errors.field.operator_not_allowed': 'یہ موازنہ اس فیلڈ کے ساتھ استعمال نہیں ہو سکتا۔',
  'errors.field.order_incomplete': 'ترتیب بدلتے وقت فہرست بدل گئی۔ دوبارہ لوڈ کر کے پھر کوشش کریں۔',
  'errors.field.order_must_list_every_value':
    'اس دوران فہرست بدل گئی۔ ری لوڈ کر کے دوبارہ کوشش کریں۔',
  'errors.field.out_of_range': 'یہ عدد اجازت یافتہ حد سے باہر ہے۔',
  'errors.field.owner_not_allowed':
    'یہ شخص اعلانات کا انتظام نہیں کر سکتا، اس لیے مالک نہیں بن سکتا۔',
  'errors.field.parent_loop': 'اس سے یہ اپنا ہی والد بن جائے گا۔',
  'errors.field.password_policy_out_of_range': '{{min}} اور {{max}} کے درمیان رکھیں۔',
  'errors.field.pattern_mismatch': 'یہ قدر متوقع شکل میں نہیں ہے۔',
  'errors.field.pattern_too_complex':
    'یہ پیٹرن ایسے گروپ کو دہراتا ہے جو خود بھی دہرایا جاتا ہے، جس سے محفوظ کرنا بہت سست ہو سکتا ہے۔ اسے آسان کریں، مثلاً ([A-Z]+)+ کے بجائے [A-Z]+۔',
  'errors.field.period_time_invalid': 'اوقات HH:MM کی شکل میں درج کریں، 00:00 سے 24:00 تک۔',
  'errors.field.period_weekday_invalid': 'ہفتے کا کوئی دن منتخب کریں۔',
  'errors.field.periods_overlap':
    'کام کے دورانیے ایک دوسرے پر آ رہے ہیں۔ رات کا دورانیہ بھی اگلی صبح کے دورانیے سے پہلے ختم ہونا چاہیے۔',
  'errors.field.person_in_no_group':
    'یہ فرد کسی سپورٹ گروپ میں نہیں، اس لیے انہیں کچھ تفویض نہیں ہو سکتا۔',
  'errors.field.person_not_in_group': 'یہ فرد منتخب گروپ کے رکن نہیں۔',
  'errors.field.phone_not_valid': 'فون نمبر درج کریں: ہندسے، خالی جگہ، +، - اور قوسین۔',
  'errors.field.plain_connection_refused':
    'بغیر انکرپشن کنکشن رد کیا جاتا ہے جب تک آپ اجازت نہ دیں۔',
  'errors.field.private_key_unreadable':
    'نجی کلید پڑھی نہیں جا سکی: اسے غیر خفیہ PEM فارمیٹ میں چسپاں کریں۔',
  'errors.field.range_end_before_start': 'اختتام آغاز کے بعد ہونا چاہیے۔',
  'errors.field.read_category_unknown': 'اس قسم کی پڑھائی لاگ نہیں کی جا سکتی۔',
  'errors.field.read_only': 'یہ فیلڈ یہاں تبدیل نہیں ہو سکتی۔',
  'errors.field.read_only_in_stage': 'موجودہ مرحلے میں یہ فیلڈ بدلی نہیں جا سکتی۔',
  'errors.field.reason_required': 'وجہ بتائیں۔',
  'errors.field.reassign_group_required':
    'یہ فرد کئی گروپوں میں ہیں: وہ گروپ چنیں جس میں ریکارڈ جائے گا۔',
  'errors.field.recipient_shape': 'اس وصول کنندہ کے لیے شخص یا گروپ منتخب کریں۔',
  'errors.field.recipients_required': 'کم از کم ایک شخص یا گروپ منتخب کریں۔',
  'errors.field.record_not_found': 'آپ کے دیکھنے کے قابل کسی ریکارڈ کی یہ شناخت نہیں۔',
  'errors.field.replies_are_public':
    'جوابات ٹیم سے باہر کے لوگوں کو جاتے ہیں، اس لیے وہ ہمیشہ عوامی ہوتے ہیں۔',
  'errors.field.report_not_found': 'یہ رپورٹ موجود نہیں یا آپ کے ساتھ شیئر نہیں۔',
  'errors.field.requester_always_needed':
    'درخواست گزار موضوع اور درخواست گزار ہمیشہ دیکھتے اور بھرتے ہیں۔',
  'errors.field.requester_audience_empty':
    'درخواست دہندگان کا کم از کم ایک گروپ، سائٹ یا شعبہ منتخب کریں۔',
  'errors.field.requester_only': 'یہ کوڈ صرف درخواست گزار کی تصدیق سے لگتا ہے۔',
  'errors.field.required': 'یہ خانہ ضروری ہے۔',
  'errors.field.required_for_known_error':
    'معلوم خرابی نشان زد کرنے سے پہلے عارضی حل یا بنیادی وجہ لکھیں۔',
  'errors.field.required_for_move': 'منتقلی سے پہلے یہ بھریں۔',
  'errors.field.required_to_close': 'بند کرنے سے پہلے درکار ہے۔',
  'errors.field.required_to_confirm_cause': 'تصدیق سے پہلے بنیادی وجہ لکھیں۔',
  'errors.field.required_to_leave_stage': 'اس مرحلے سے نکلنے سے پہلے یہ بھریں۔',
  'errors.field.required_to_resolve': 'حل کرنے سے پہلے درکار ہے۔',
  'errors.field.review_date_past': 'آج یا بعد کی تاریخ منتخب کریں۔',
  'errors.field.role_disabled': 'یہ کردار ختم کیا جا چکا ہے: کسی نئے کو نہیں دیا جا سکتا۔',
  'errors.field.same_folder': 'اس کی رپورٹس کے لیے کوئی دوسرا فولڈر منتخب کریں۔',
  'errors.field.schedule_never_runs': 'ان تاریخوں کے ساتھ شیڈول کبھی نہیں چلے گا۔',
  'errors.field.scope_not_allowed': 'یہ دائرہ اس اجازت کے لیے دستیاب نہیں۔',
  'errors.field.session_absolute_out_of_range':
    'کم از کم غیرفعالی کی مہلت جتنا اور زیادہ سے زیادہ {{max}} گھنٹے رکھیں۔',
  'errors.field.session_idle_out_of_range': '{{min}} سے {{max}} منٹ کے درمیان رکھیں۔',
  'errors.field.site_inactive': 'یہ سائٹ غیر فعال ہے۔ فعال سائٹ منتخب کریں۔',
  'errors.field.site_not_found': 'یہ مقام موجود نہیں۔',
  'errors.field.sso_certificate_expired':
    'سرٹیفکیٹ کی میعاد ختم ہو چکی ہے۔ شناخت فراہم کنندہ سے نیا لیں۔',
  'errors.field.sso_certificate_missing': 'میٹا ڈیٹا میں دستخطی سرٹیفکیٹ نہیں ہے۔',
  'errors.field.sso_certificate_required': 'شناخت فراہم کنندہ کا دستخطی سرٹیفکیٹ چسپاں کریں۔',
  'errors.field.sso_certificate_unreadable':
    'سرٹیفکیٹ پڑھا نہیں جا سکا: اسے PEM صورت میں چسپاں کریں۔',
  'errors.field.sso_client_id_required': 'کلائنٹ آئی ڈی درج کریں۔',
  'errors.field.sso_client_rejected':
    'شناخت فراہم کنندہ نے یہ کلائنٹ آئی ڈی اور سیکرٹ قبول نہیں کیے۔',
  'errors.field.sso_client_secret_required': 'کلائنٹ سیکرٹ درج کریں۔',
  'errors.field.sso_discovery_invalid': 'یہ پتا OpenID Connect جاری کنندہ کی طرح جواب نہیں دیتا۔',
  'errors.field.sso_discovery_unreachable': 'SupportX اس جاری کنندہ تک نہیں پہنچ سکا۔ پتا جانچیں۔',
  // WP-039 identity: Admin > Sign-in and security
  'errors.field.sso_domain_in_use':
    '{{domain}} آپ کے کسی اور سنگل سائن آن سیٹ اپ میں استعمال ہو رہا ہے۔',
  'errors.field.sso_domain_invalid': '{{domain}} ڈومین کا نام نہیں، جیسے example.com۔',
  'errors.field.sso_domain_public':
    '{{domain}} عوامی میل سروس ہے اور سنگل سائن آن کے لیے استعمال نہیں ہو سکتی۔',
  'errors.field.sso_domain_required': 'کم از کم ایک ای میل ڈومین شامل کریں۔',
  'errors.field.sso_domain_taken': 'ان میں سے ایک ڈومین کسی اور تنظیم کے پاس ہے۔',
  'errors.field.sso_domain_unverified':
    'سنگل سائن آن کے استعمال سے پہلے ثابت کریں کہ {{domain}} آپ کی تنظیم کا ہے۔',
  'errors.field.sso_domains_too_many': 'زیادہ سے زیادہ {{max}} ڈومین رکھیں۔',
  'errors.field.sso_issuer_mismatch':
    'یہ پتا کسی اور جاری کنندہ کا نام دیتا ہے۔ جاری کنندہ کا عین پتا استعمال کریں۔',
  'errors.field.sso_issuer_required': 'جاری کنندہ کا پتا درج کریں۔',
  'errors.field.sso_metadata_required':
    'میٹا ڈیٹا اپ لوڈ کریں، اس کا پتا دیں، یا سائن اِن کا پتا بھریں۔',
  'errors.field.sso_metadata_unreachable': 'SupportX اس پتے سے میٹا ڈیٹا نہیں لا سکا۔',
  'errors.field.sso_metadata_unreadable': 'یہ فائل قابلِ مطالعہ SAML میٹا ڈیٹا نہیں۔',
  'errors.field.sso_name_length': '1 سے {{max}} حروف رکھیں۔',
  'errors.field.sso_protocol_fixed':
    'سیٹ اپ اپنا پروٹوکول برقرار رکھتا ہے۔ اس کے بجائے نیا شامل کریں۔',
  'errors.field.sso_sign_in_url_missing': 'میٹا ڈیٹا میں سائن اِن کا پتا نہیں ہے۔',
  'errors.field.sso_url_invalid': 'مکمل پتا درج کریں جو https:// سے شروع ہو۔',
  'errors.field.system_calendar_fixed':
    'چوبیس گھنٹے ہمیشہ ہر گھنٹہ گنتا ہے۔ صرف اس کا نام بدلا جا سکتا ہے۔',
  'errors.field.target_amount_invalid': '1 سے 100,000 تک کا پورا عدد درج کریں۔',
  'errors.field.target_duplicate': 'اس ترجیح کے لیے یہ ہدف پہلے سے مقرر ہے۔',
  'errors.field.technician_audience_empty': 'تمام تکنیکی ماہرین یا کم از کم ایک گروپ منتخب کریں۔',
  'errors.field.technician_not_allowed': 'یہ شخص ان ریکارڈز پر کام نہیں کر سکتا۔',
  'errors.field.technician_not_in_group': 'یہ ٹیکنیشن منتخب گروپ کا رکن نہیں۔',
  'errors.field.template_disabled': 'یہ سانچہ بند کر دیا گیا ہے۔ کوئی اور سانچہ منتخب کریں۔',
  'errors.field.template_not_found': 'یہ سانچہ اب موجود نہیں۔ کوئی اور منتخب کریں۔',
  'errors.field.template_not_offered': 'یہ سانچہ آپ کے لیے دستیاب نہیں۔ کوئی اور سانچہ منتخب کریں۔',
  'errors.field.time_format_unknown': '24 گھنٹے یا 12 گھنٹے کا وقت چنیں۔',
  'errors.field.time_zone_unknown': 'فہرست میں سے ٹائم زون چنیں۔',
  'errors.field.timezone_required': 'ٹائم زون شامل کریں۔',
  'errors.field.title_required': 'عنوان درج کریں۔',
  'errors.field.too_deep': 'زمروں کی زیادہ سے زیادہ تین سطحیں ہیں۔',
  'errors.field.too_many': 'وصول کنندگان بہت زیادہ ہیں۔',
  'errors.field.too_many_actions': 'ایک قاعدے میں زیادہ سے زیادہ {{max}} عمل ہو سکتے ہیں۔',
  'errors.field.too_many_approvers': 'ایک مرحلے میں زیادہ سے زیادہ 10 منظور کنندگان ہو سکتے ہیں۔',
  'errors.field.too_many_categories':
    'کوئی آئٹم زیادہ سے زیادہ پانچ دیگر کیٹیگریز میں بھی دکھایا جا سکتا ہے۔',
  'errors.field.too_many_conditions': 'شرائط بہت زیادہ ہیں۔',
  'errors.field.too_many_decimals': 'زیادہ سے زیادہ {{max}} اعشاری مقامات استعمال کریں۔',
  'errors.field.too_many_items': 'اندراجات بہت زیادہ ہیں۔',
  'errors.field.too_many_keywords': 'ہر زبان میں زیادہ سے زیادہ 20 کلیدی الفاظ استعمال کریں۔',
  'errors.field.too_many_levels': 'ہر ہدف کے لیے زیادہ سے زیادہ {{max}} ایسکلیشن درجے۔',
  'errors.field.too_many_options': 'ایک سوال میں زیادہ سے زیادہ 50 انتخاب ہو سکتے ہیں۔',
  'errors.field.too_many_questions': 'فارم میں زیادہ سے زیادہ 30 سوال ہو سکتے ہیں۔',
  'errors.field.too_many_recipients': 'زیادہ سے زیادہ 50 افراد اور 20 گروپ۔',
  'errors.field.too_many_records': 'زیادہ سے زیادہ {{max}} ریکارڈ منتخب کریں۔',
  'errors.field.too_many_tasks': 'ایک منصوبے میں زیادہ سے زیادہ 20 کام ہو سکتے ہیں۔',
  'errors.field.too_many_values': 'زیادہ سے زیادہ {{max}} منتخب کریں۔',
  'errors.field.topic_too_deep': 'موضوعات زیادہ سے زیادہ {{max}} درجے گہرے ہو سکتے ہیں۔',
  'errors.field.topic_under_itself': 'کوئی موضوع خود اپنے یا اپنے ذیلی موضوع کے نیچے نہیں جا سکتا۔',
  'errors.field.type_cannot_change':
    'خانے کی قسم تبدیل نہیں ہو سکتی۔ نیا خانہ بنائیں اور اسے ریٹائر کریں۔',
  'errors.field.unknown_article_type': 'مضمون کی یہ قسم موجود نہیں یا ختم کر دی گئی ہے۔',
  'errors.field.unknown_builtin_report': 'یہ بلٹ اِن رپورٹ موجود نہیں۔',
  'errors.field.unknown_column': 'یہ کالم ان ریکارڈز کے لیے موجود نہیں۔',
  'errors.field.unknown_dimension': 'رپورٹس کو اس فیلڈ کے مطابق گروپ نہیں کیا جا سکتا۔',
  'errors.field.unknown_entity': 'اس قسم کی کوئی چیز رپورٹ کے لیے موجود نہیں۔',
  'errors.field.unknown_field': 'آپ اس فیلڈ پر فلٹر نہیں کر سکتے۔',
  'errors.field.unknown_folder': 'یہ فولڈر اب موجود نہیں۔',
  'errors.field.unknown_key': 'فلٹر کی یہ ترتیب پہچانی نہیں گئی۔',
  'errors.field.unknown_language': 'صرف انگریزی، عربی اور اردو نام قابل قبول ہیں۔',
  'errors.field.unknown_measure': 'یہ پیمانہ ان ریکارڈز کے لیے دستیاب نہیں۔',
  'errors.field.unknown_operator': 'یہ موازنہ پہچانا نہیں گیا۔',
  'errors.field.unknown_option': 'یہ انتخاب سوال کے اختیارات میں شامل نہیں۔',
  'errors.field.unknown_parameter': 'فہرست کا یہ اختیار پہچانا نہیں گیا۔',
  'errors.field.unknown_permission': 'یہ اجازت موجود نہیں ہے۔',
  'errors.field.unknown_placeholder':
    'قوسین میں صرف فارم کے سوالات کی کلیدیں، یا {person}، استعمال کریں۔',
  'errors.field.unknown_priority': 'فہرست سے ترجیح منتخب کریں۔',
  'errors.field.unknown_question': 'اس فارم میں یہ سوال نہیں ہے۔',
  'errors.field.unknown_recipient': 'منتخب کردہ کوئی شخص اب فعال نہیں یا کوئی گروپ اب موجود نہیں۔',
  'errors.field.unknown_record_type': 'منتخب کریں کہ قاعدہ کس پر لاگو ہو۔',
  'errors.field.unknown_reference': 'یہاں بتایا گیا کوئی شخص یا گروپ اب موجود نہیں۔',
  'errors.field.unknown_sort_field': 'فہرست کو اس فیلڈ کے لحاظ سے ترتیب نہیں دیا جا سکتا۔',
  'errors.field.unknown_stage': 'اس قسم میں ایسا کوئی مرحلہ نہیں۔',
  'errors.field.unknown_time_zone': 'فہرست سے ٹائم زون منتخب کریں۔',
  'errors.field.unknown_value': 'یہ قدر موجود نہیں (اب نہیں رہی)۔',
  'errors.field.url_not_valid': 'https:// یا http:// سے شروع ہونے والا ویب پتہ درج کریں۔',
  'errors.field.user_not_found': 'یہ شخص آپ کی تنظیم میں موجود نہیں۔',
  'errors.field.value_no_longer_valid': 'یہ قدر اب دستیاب نہیں۔',
  'errors.field.value_not_allowed': 'یہ موازنہ کوئی قدر نہیں لیتا۔',
  'errors.field.value_required_by_system':
    '"دیگر" ریٹائر نہیں ہو سکتا: جب کوئی وجہ موزوں نہ ہو تو یہی راستہ ہے۔',
  'errors.field.value_too_long': 'یہ قدر بہت لمبی ہے۔',
  'errors.field.value_too_long_max': 'زیادہ سے زیادہ {{max_length}} حروف استعمال کریں۔',
  'errors.field.value_too_short': 'کم از کم {{min}} حروف استعمال کریں۔',
  'errors.field.vendor_inactive': 'یہ وینڈر غیر فعال ہے اور منتخب نہیں ہو سکتا۔',
  'errors.field.vendor_name_taken': 'کسی اور وینڈر کا یہی نام ہے۔',
  'errors.field.vendor_not_found': 'یہ وینڈر اب موجود نہیں۔',
  'errors.field.week_empty': 'کم از کم ایک کام کا دورانیہ شامل کریں۔',
  'errors.field.week_start_unknown': 'ہفتہ شروع ہونے کا دن چنیں۔',
  'errors.field.week_too_many_periods':
    'ایک ہفتے میں زیادہ سے زیادہ 28 کام کے دورانیے ہو سکتے ہیں۔',
  'errors.field.whole_number_required': 'مکمل عدد درج کریں۔',
  'errors.field.wider_than_topic': 'مضمون اپنے موضوع کے سامعین کو صرف محدود کر سکتا ہے، وسیع نہیں۔',
  'errors.field.window_end_before_start': 'شروع کے بعد ہونا چاہیے۔',
  'errors.field.workflow_disabled': 'یہ ورک فلو بند ہے۔ پہلے اسے چالو کریں۔',
  'errors.field.workflow_not_found': 'ایسا ورک فلو چنیں جو موجود ہو۔',
  'errors.field.workflow_not_published': 'پہلے یہ ورک فلو شائع کریں۔',
  'errors.field.workflow_wrong_record_type': 'یہ ورک فلو کسی اور قسم کے ریکارڈ کے لیے ہے۔',
  'errors.field.would_loop': 'کوئی ریلیز خود اپنا حصہ نہیں بن سکتی، براہ راست یا دوسروں کے ذریعے۔',
  'errors.file_link_expired': 'لنک کی میعاد ختم ہو گئی۔ فائل دوبارہ کھولیں۔',
  'errors.file_not_an_image': 'یہ فائل تصویر نہیں ہے۔',
  'errors.file_not_found': 'یہ فائل موجود نہیں یا آپ اسے نہیں دیکھ سکتے۔',
  'errors.file_not_ready': 'یہ فائل کھولنے کے لیے تیار نہیں۔',
  'errors.file_not_rescannable': 'اس فائل کی دوبارہ جانچ نہیں ہو سکتی۔',
  'errors.file_owner_not_allowed': 'وہاں فائلیں منسلک نہیں کی جا سکتیں۔',
  'errors.file_owner_not_found':
    'جس چیز سے آپ منسلک کر رہے ہیں وہ موجود نہیں یا آپ اسے نہیں دیکھ سکتے۔',
  'errors.file_staff_only':
    'صرف سروس ڈیسک فائلیں ہٹا سکتا ہے یا کسی اور کے پیغام میں شامل کر سکتا ہے۔',
  'errors.file_thumbnail_not_found': 'اس فائل کا کوئی پیش منظر نہیں۔',
  'errors.file_too_large': 'فائل {{limit_mb}} MB کی حد سے بڑی ہے۔',
  'errors.file_type_blocked': 'اس قسم کی فائلوں کی اجازت نہیں (.{{extension}})۔',
  'errors.files_not_configured': 'فائلیں محفوظ نہیں ہو سکتیں: انکرپشن کیز ترتیب نہیں دی گئیں۔',
  'errors.follower_not_found': 'یہ شخص اسے فالو نہیں کر رہا۔',
  'errors.group_not_found': 'سپورٹ گروپ نہیں ملا۔',
  'errors.group_not_led': 'آپ صرف ان گروپس کا انتظام کر سکتے ہیں جن کی آپ قیادت کرتے ہیں۔',
  'errors.holiday_list_not_found': 'تعطیلات کی یہ فہرست موجود نہیں یا حذف ہو چکی ہے۔',
  'errors.holiday_not_found': 'یہ تعطیل موجود نہیں یا حذف ہو چکی ہے۔',
  'errors.ical_too_large': 'فائل 1 MB سے بڑی ہے۔',
  'errors.idempotency_key_reused':
    'یہ درخواست پہلے ہی مختلف ڈیٹا کے لیے استعمال ہو چکی ہے۔ نئی درخواست شروع کریں۔',
  'errors.idempotency_request_in_progress':
    'یہی درخواست ابھی زیرِ کارروائی ہے۔ براہِ کرم ذرا انتظار کریں۔',
  'errors.identity_admin_not_configured':
    'اس انسٹالیشن پر سائن اِن کی ترتیبات ابھی تیار نہیں۔ اپنے ایڈمنسٹریٹر سے شناخت کے سیٹ اپ کا مرحلہ چلانے کو کہیں۔',
  'errors.identity_admin_unavailable':
    'سائن اِن کی سروس سے ابھی رابطہ نہیں ہو پا رہا۔ تھوڑی دیر میں دوبارہ کوشش کریں۔',
  'errors.identity_organization_missing':
    'آپ کی تنظیم ابھی سائن اِن کے لیے تیار نہیں۔ اپنے ایڈمنسٹریٹر سے پوچھیں۔',
  'errors.identity_provider_unavailable':
    'سائن اِن عارضی طور پر دستیاب نہیں۔ براہِ کرم تھوڑی دیر بعد دوبارہ کوشش کریں۔',
  'errors.incident_has_problem':
    'یہ واقعہ پہلے سے {{display_id}} سے جڑا ہے۔ تصدیق کے لیے اسے منتقل کریں۔',
  'errors.insert_too_large':
    'مضمون کی تصاویر ایک ساتھ شامل کرنے کے لیے بہت بڑی ہیں: زیادہ سے زیادہ {{limit_mb}} MB۔',
  'errors.internal_error': 'ہماری طرف کچھ غلط ہو گیا۔ براہِ کرم دوبارہ کوشش کریں۔',
  'errors.invalid_choice': 'یہ قدر دستیاب انتخاب میں سے نہیں۔',
  'errors.invalid_cursor': 'یہ صفحہ لنک اب درست نہیں۔ پہلے صفحے سے شروع کریں۔',
  'errors.invalid_etag':
    'اس تبدیلی کے ساتھ بھیجا گیا آئٹم کا ورژن درست نہیں۔ دوبارہ لوڈ کر کے پھر کوشش کریں۔',
  'errors.invalid_filter': 'فلٹر لاگو نہیں ہو سکا۔ نمایاں کی گئی شرط دیکھیں۔',
  'errors.invalid_idempotency_key': 'درخواست کا شناخت کنندہ درست نہیں۔',
  'errors.invalid_login_state':
    'اس سائن اِن لنک کی میعاد ختم ہو گئی ہے۔ براہِ کرم دوبارہ شروع کریں۔',
  'errors.invalid_page_size': 'ایک صفحے کے لیے بہت زیادہ قطاریں مانگی گئیں۔',
  'errors.invalid_report': 'یہ رپورٹ اس حالت میں نہیں چل سکتی۔ نمایاں حصے چیک کریں۔',
  'errors.invalid_sort': 'فہرست کو اس طرح ترتیب نہیں دیا جا سکتا۔',
  'errors.invalid_tenant_id': 'ادارے کا شناخت کنندہ درست نہیں۔',
  'errors.invalid_transition':
    'موجودہ حیثیت میں یہ ممکن نہیں۔ تازہ ترین دیکھنے کے لیے دوبارہ لوڈ کریں۔',
  'errors.investigator_not_found': 'یہ شخص اس مسئلے کا تفتیش کار نہیں ہے۔',
  'errors.invitation_already_signed_in':
    'یہ شخص پہلے ہی سائن اِن کر چکا ہے، اس لیے دعوت کی ضرورت نہیں۔',
  'errors.invitation_needs_email': 'پہلے اس شخص کا ای میل پتا شامل کریں۔',
  'errors.invitation_not_found': 'یہ دعوت نامہ نہیں ملا۔',
  'errors.invitation_not_pending': 'یہ دعوت نامہ اب منتظر نہیں: قبول ہو چکا یا واپس لیا جا چکا۔',
  'errors.invitation_pending': 'اس شخص کا ایک دعوت نامہ منتظر ہے۔ اس کے بجائے اسے دوبارہ بھیجیں۔',
  'errors.invitation_person_cannot_sign_in': 'یہ شخص غیر فعال ہے یا اسے سائن اِن کی اجازت نہیں۔',
  'errors.kb_article_not_editable':
    'آپ یہ مضمون نہیں بدل سکتے۔ اس کا مالک یا نالج مینیجر بدل سکتا ہے۔',
  'errors.kb_article_not_found': 'یہ مضمون موجود نہیں یا آپ کے ساتھ شیئر نہیں ہے۔',
  'errors.kb_article_not_published': 'اس مضمون کا ابھی کوئی شائع شدہ ورژن نہیں جو شامل کیا جا سکے۔',
  'errors.kb_article_withdrawn': 'یہ مضمون اب دستیاب نہیں ہے۔',
  'errors.kb_cannot_approve':
    'آپ یہ مضمون منظور نہیں کر سکتے۔ موضوع کا مالک یا منظور کنندہ کر سکتا ہے۔',
  'errors.kb_cannot_delete': 'آپ یہ مضمون ردی میں نہیں ڈال سکتے۔',
  'errors.kb_cannot_withdraw': 'آپ یہ مضمون واپس نہیں لے سکتے۔',
  'errors.kb_draft_exists': 'اس زبان میں ایک مسودہ پہلے سے کھلا ہے۔ اسی پر کام جاری رکھیں۔',
  'errors.kb_draft_in_review': 'یہ نسخہ جائزے میں ہے اور ابھی بدلا نہیں جا سکتا۔',
  'errors.kb_draft_not_found': 'اس زبان میں اس مضمون کا کوئی مسودہ نہیں۔',
  'errors.kb_link_not_found': 'یہ ربط اب موجود نہیں۔',
  'errors.kb_not_a_draft': 'صرف مسودہ جائزے کے لیے بھیجا جا سکتا ہے۔',
  'errors.kb_not_in_review': 'یہ ورژن جائزے کا منتظر نہیں ہے۔',
  'errors.kb_not_published': 'یہ مضمون ابھی شائع نہیں ہوا۔',
  'errors.kb_record_has_no_resolution': 'اس ریکارڈ کا ابھی کوئی حل نہیں جسے نالج بنایا جا سکے۔',
  'errors.kb_record_not_found': 'یہ ریکارڈ موجود نہیں یا آپ کے ساتھ شیئر نہیں ہے۔',
  'errors.kb_requesters_off': 'علمی مضامین یہاں دستیاب نہیں ہیں۔',
  'errors.kb_self_approval_off':
    'یہاں مصنف اپنے مضامین منظور نہیں کر سکتے۔ کسی اور منظور کنندہ سے کہیں۔',
  'errors.kb_topic_in_trash':
    'اس کا موضوع ردی میں ہے۔ پہلے موضوع بحال کریں یا کوئی اور موضوع چنیں۔',
  'errors.kb_topic_not_found': 'یہ موضوع موجود نہیں یا آپ کے ساتھ شیئر نہیں ہے۔',
  'errors.kb_type_not_found': 'مضمون کی یہ قسم موجود نہیں۔',
  'errors.kb_version_not_published':
    'یہ ورژن اب وہ نہیں جو قارئین دیکھتے ہیں۔ مضمون دوبارہ لوڈ کریں اور پھر کوشش کریں۔',
  'errors.kb_vote_comment_too_long': 'تبصرہ 1,000 حروف تک رکھیں۔',
  'errors.kb_vote_reason_for_no_only': 'وجہ صرف «نہیں» کے ساتھ دی جاتی ہے۔',
  'errors.kb_vote_reason_unknown': 'پیش کردہ وجوہات میں سے ایک منتخب کریں۔',
  'errors.last_tenant_admin': 'ادارے میں کم از کم ایک ادارہ منتظم ہونا ضروری ہے۔',
  'errors.ldap_attribute_invalid': 'ڈائریکٹری خصوصیت کا نام درج کریں: حروف، ہندسے اور خط فاصل۔',
  'errors.ldap_bind_password_missing': 'کوئی بائنڈ پاس ورڈ محفوظ نہیں ہے۔ اسے دوبارہ درج کریں۔',
  'errors.ldap_dn_invalid': 'ایک ممتاز نام درج کریں، جیسے OU=People,DC=example,DC=com۔',
  'errors.ldap_federation_keycloak_unavailable':
    'شناختی سروس نے جواب نہیں دیا۔ واپس آنے پر ڈائریکٹری جوڑ دی جائے گی۔',
  'errors.ldap_federation_not_installed':
    'اس تنصیب پر AD/LDAP فعال نہیں ہے۔ اپنے منتظم سے اسے فعال کرنے کو کہیں۔',
  'errors.ldap_federation_refused':
    'شناختی سروس نے ڈائریکٹری کی ترتیبات مسترد کر دیں۔ سرور، بائنڈ اکاؤنٹ اور راستے چیک کریں۔',
  'errors.ldap_filter_invalid': 'قوسین میں LDAP فلٹر درج کریں، جیسے (objectClass=person)۔',
  // WP-040 AD/LDAP (D-130)
  'errors.ldap_host_invalid': 'ڈائریکٹری سرور کا نام یا IP پتہ درج کریں، ldap:// یا راستے کے بغیر۔',
  'errors.ldap_single_tenant_only':
    'AD/LDAP ڈائریکٹریز صرف اس تنصیب پر جوڑی جا سکتی ہیں جو ایک ادارے کے لیے ہو۔',
  'errors.limit_reached':
    'آپ کے پلان کی اس کے لیے حد پوری ہو چکی ہے۔ پلان بڑھانے کے لیے اپنے منتظم سے کہیں۔',
  'errors.link_has_own_route':
    'یہ لنک اپنی جگہ سے ہٹایا جاتا ہے: واقعے کو الگ کریں، یا ضم کرنا واپس لیں۔',
  'errors.login_failed': 'سائن اِن مکمل نہیں ہوا۔ براہِ کرم دوبارہ کوشش کریں۔',
  'errors.mail_address_invalid': 'ایک ای میل پتا درست نہیں۔',
  'errors.mail_attachment_name': 'ایک منسلکہ کا نام درست نہیں۔',
  'errors.mail_attachment_type': 'اس قسم کی فائل ای میل سے نہیں بھیجی جا سکتی۔',
  'errors.mail_attachments_too_large': 'منسلکات مل کر 10 MB سے بڑی ہیں۔',
  'errors.mail_content_gone': 'اس ای میل کا متن اب محفوظ نہیں۔ جواب دوبارہ لکھیں۔',
  'errors.mail_kind_invalid': 'اس قسم کی ای میل معلوم نہیں۔',
  'errors.mail_language_invalid': 'یہ زبان ای میل کے لیے دستیاب نہیں۔',
  'errors.mail_not_configured':
    'اس انسٹالیشن پر باہر جانے والی ای میل سیٹ اپ نہیں۔ اپنے آپریٹر سے اسے ترتیب دینے کو کہیں۔',
  'errors.mail_not_waiting': 'یہ پیغام اب منتظر نہیں: کسی نے پہلے ہی اسے نمٹا دیا۔',
  'errors.mail_recipients': '1 سے 50 وصول کنندگان کو بھیجیں۔',
  'errors.mail_sender_invalid': 'بھیجنے والے کا نام یا جواب کا پتا درست نہیں۔',
  'errors.mail_status_staff_only': 'یہ صرف وہ لوگ دیکھ سکتے ہیں جو ریکارڈز پر جواب دیتے ہیں۔',
  'errors.mail_subject_invalid': 'موضوع ایک سطر کا ہو، زیادہ سے زیادہ 300 حروف۔',
  'errors.mailbox_address_taken': 'کوئی اور میل باکس یہ پتہ پہلے سے پڑھتا ہے۔',
  'errors.mailbox_credential_unreadable':
    'ایپ کا سیکرٹ یا سرٹیفکیٹ موجود نہیں یا پڑھا نہیں جا سکتا۔ دوبارہ درج کریں۔',
  'errors.mailbox_key_ring_missing':
    'میل باکس کے پاس ورڈ ابھی محفوظ طریقے سے نہیں رکھے جا سکتے: انسٹالیشن کی کلیدی رنگ سیٹ نہیں ہے۔',
  'errors.mailbox_not_found': 'یہ میل باکس موجود نہیں۔',
  'errors.mailbox_sign_in_not_needed': 'اس میل باکس کے لیے کسی کو سائن اِن کرنے کی ضرورت نہیں۔',
  // WP-040 session 2: directory sync.
  'errors.managed_by_directory': 'یہ فیلڈ آپ کی ڈائریکٹری رکھتی ہے۔ اسے وہیں تبدیل کریں۔',
  'errors.message_refused': 'میل سرور نے پیغام رد کر دیا۔',
  'errors.method_not_allowed': 'یہ کارروائی یہاں دستیاب نہیں۔',
  'errors.mfa_enrolment_unavailable':
    'پہلے دو مرحلہ سائن اِن سیٹ اپ کرنا ہے، لیکن سائن اِن سروس تک رسائی نہیں ہو سکی۔ کچھ دیر بعد دوبارہ کوشش کریں۔',
  'errors.mfa_reset_not_signed_in':
    'اس شخص نے ابھی سائن اِن نہیں کیا، اس لیے ری سیٹ کرنے کو کچھ نہیں۔',
  'errors.mfa_reset_own':
    'آپ اپنا دو مرحلہ سائن اِن خود ری سیٹ نہیں کر سکتے۔ کسی دوسرے ایڈمنسٹریٹر سے کہیں۔',
  'errors.name_taken': 'یہ نام پہلے سے استعمال میں ہے۔',
  'errors.network_error':
    'SupportX تک ابھی رسائی نہیں ہو رہی۔ اپنا کنکشن چیک کریں؛ ہم کوشش جاری رکھیں گے۔',
  'errors.no_organization':
    'آپ کا اکاؤنٹ ابھی کسی ادارے سے منسلک نہیں۔ براہِ کرم اپنے منتظم سے رابطہ کریں۔',
  'errors.not_a_member': 'آپ اس ادارے کے رکن نہیں ہیں۔',
  'errors.not_acceptable': 'مطلوبہ فارمیٹ معاون نہیں ہے۔',
  'errors.not_an_approver': 'آپ اس درخواست کے منظوری دہندہ نہیں ہیں۔',
  'errors.not_found': 'آئٹم نہیں ملا۔',
  'errors.not_known_error': '{{display_id}} معلوم خرابی نہیں ہے۔',
  'errors.not_merged': '{{display_id}} ضم شدہ نہیں، اس لیے واپس لینے کو کچھ نہیں۔',
  'errors.not_resolved': 'یہ اب آپ کے جواب کا منتظر نہیں: یہ اب حل شدہ نہیں ہے۔',
  'errors.nothing_to_override':
    'یہ تبدیلی دوبارہ منظوری کی منتظر نہیں، اس لیے نظر انداز کرنے کو کچھ نہیں۔',
  'errors.notification_event_not_found': 'اطلاع کا یہ واقعہ موجود نہیں۔',
  'errors.notification_not_found': 'یہ اطلاع موجود نہیں یا آپ کی نہیں۔',
  'errors.notification_record_not_found': 'یہ ریکارڈ موجود نہیں یا آپ کے لیے دستیاب نہیں۔',
  'errors.on_behalf_out_of_scope': 'آپ اس شخص کے لیے درخواست نہیں دے سکتے۔ سروس ڈیسک سے پوچھیں۔',
  'errors.open_work_blocked': 'یہ کام کھلا ہونے تک یہ نہیں ہو سکتا: {{items}}۔',
  'errors.open_work_unconfirmed':
    'کام ابھی کھلا ہے: {{items}}۔ پھر بھی آگے بڑھنے کے لیے تصدیق کریں۔',
  'errors.order_out_of_date': 'اس دوران فہرست بدل گئی۔ دوبارہ لوڈ کر کے ترتیب دیں۔',
  'errors.out_of_range': 'یہ قدر اجازت شدہ حد سے باہر ہے۔',
  'errors.own_profile_only': 'آپ صرف اپنی ترجیحات تبدیل کر سکتے ہیں۔',
  'errors.password_policy_not_saved': 'پہلے پاس ورڈ پالیسی محفوظ کریں۔',
  'errors.password_policy_platform': 'اس انسٹالیشن پر پاس ورڈ پالیسی پلیٹ فارم طے کرتا ہے۔',
  'errors.password_reset_not_signed_in':
    'اس شخص نے ابھی سائن اِن نہیں کیا۔ اس کے بجائے دعوت نامہ بھیجیں۔',
  'errors.payload_too_large': 'اپ لوڈ بہت بڑا ہے۔',
  'errors.people_import_file_not_readable': 'CSV فائل یا Excel ورک بُک ({{xlsx}}) استعمال کریں۔',
  'errors.people_import_file_too_large': 'فائل 5 MB سے بڑی ہے۔',
  'errors.people_import_file_unsafe':
    'ورک بُک نہیں کھولی گئی: یہ اپنے سائز سے کہیں بڑی ہو جاتی ہے۔',
  'errors.permission_denied': 'آپ کو یہ کرنے کی اجازت نہیں ہے۔',
  'errors.pick_list_not_found': 'یہ فہرست موجود نہیں۔',
  'errors.pick_list_value_not_found': 'یہ قدر اب موجود نہیں۔',
  'errors.plain_connection_refused':
    'بغیر انکرپشن کا کنکشن مسترد کیا جاتا ہے جب تک آپ اس کی اجازت نہ دیں۔',
  'errors.plan_section_not_found': 'منصوبے کا یہ حصہ موجود نہیں۔',
  'errors.precondition_required':
    'اس تبدیلی کے لیے وہ ورژن درکار ہے جس میں آپ ترمیم کر رہے ہیں۔ آئٹم دوبارہ لوڈ کر کے پھر کوشش کریں۔',
  'errors.private_key_unreadable':
    'نجی کلید پڑھی نہیں جا سکی: اسے غیر خفیہ PEM فارمیٹ میں چسپاں کریں۔',
  'errors.privilege_escalation': 'آپ وہ رسائی نہیں دے سکتے جو خود آپ کے پاس نہیں۔',
  'errors.problem_closed': '{{display_id}} بند ہے، اس لیے ضم نہیں ہو سکتا۔',
  'errors.quick_sign_in_not_configured':
    'اس اسٹیک پر فوری سائن اِن سیٹ اپ نہیں: make dev-quick-sign-in چلائیں۔',
  'errors.quick_sign_in_refused': 'Keycloak نے یہ فوری سائن اِن مسترد کر دیا۔',
  'errors.quick_sign_in_wait':
    'اس کردار نے پچھلے 30 سیکنڈ میں دو بار سائن اِن کیا۔ {{seconds}} سیکنڈ بعد دوبارہ کوشش کریں۔',
  'errors.range_not_satisfiable': 'فائل کا یہ حصہ موجود نہیں۔',
  'errors.rate_limited': 'بہت زیادہ درخواستیں۔ براہِ کرم ذرا انتظار کر کے دوبارہ کوشش کریں۔',
  'errors.read_only_mode':
    'آپ کا ادارہ صرف پڑھنے کی حالت میں ہے۔ آپ ڈیٹا دیکھ اور برآمد کر سکتے ہیں، لیکن لائسنس کی تجدید تک تبدیلیاں رکی ہوئی ہیں۔',
  'errors.realtime_channel_denied':
    'آپ اب اسے براہِ راست نہیں دیکھ سکتے۔ تازہ ترین ڈیٹا دیکھنے کے لیے صفحہ دوبارہ لوڈ کریں۔',
  'errors.realtime_not_configured':
    'اس سرور پر براہِ راست اپ ڈیٹس ترتیب نہیں دی گئیں۔ تازہ ترین ڈیٹا دیکھنے کے لیے صفحہ دوبارہ لوڈ کریں۔',
  'errors.recipient_deferred': 'وصول کنندہ کے میل سرور نے بعد میں کوشش کرنے کو کہا۔',
  'errors.recipient_refused': 'میل سرور نے وصول کنندہ رد کر دیا۔',
  'errors.record_closed': 'بند یا منسوخ ریکارڈ تبدیل نہیں ہو سکتے۔',
  'errors.reference_copied': 'حوالہ کاپی ہو گیا',
  'errors.reference_is': 'حوالہ: {{reference}}',
  'errors.repeat_hit_not_found': 'بار بار واقعات کا یہ مجموعہ اب موجود نہیں۔',
  'errors.repeat_rule_not_found': 'بار بار واقعات کا یہ اصول اب موجود نہیں۔',
  'errors.reply_template_not_found': 'جواب کا یہ سانچہ اب موجود نہیں ہے۔',
  'errors.report_entity_not_found': 'اس قسم کی کوئی چیز رپورٹ کے لیے موجود نہیں۔',
  'errors.report_export_not_found': 'یہ ایکسپورٹ موجود نہیں یا آپ کا نہیں۔',
  'errors.report_export_not_ready':
    'یہ فائل تیار نہیں یا اس کا لنک ختم ہو گیا ہے۔ رپورٹ دوبارہ ایکسپورٹ کریں۔',
  'errors.report_not_allowed': 'آپ کو ان ریکارڈز پر رپورٹس چلانے کی اجازت نہیں۔',
  'errors.report_not_editable':
    'اس رپورٹ کو صرف اس کا مالک یا مشترکہ فولڈرز کا منتظم بدل سکتا ہے۔ اپنی نقل بنانے کے لیے اسے کاپی کریں۔',
  'errors.report_not_found': 'یہ رپورٹ موجود نہیں یا آپ کے ساتھ شیئر نہیں کی گئی۔',
  'errors.report_queue_full':
    'آپ کی تنظیم اس وقت بہت سی رپورٹس چلا رہی ہے۔ چند سیکنڈ بعد دوبارہ کوشش کریں۔',
  // Reports (WP-035)
  'errors.report_schedule_not_found': 'یہ شیڈول موجود نہیں یا آپ کا نہیں۔',
  'errors.report_timeout':
    'رپورٹ {{seconds}} سیکنڈ سے زیادہ لے گئی اور روک دی گئی۔ تاریخ کی حد یا فلٹر محدود کریں اور دوبارہ کوشش کریں۔',
  'errors.required': 'یہ فیلڈ لازمی ہے۔',
  'errors.role_in_use':
    'یہ کردار ابھی صارفین کو تفویض ہے۔ پہلے وہ کردار منتخب کریں جس میں انہیں منتقل کرنا ہے۔',
  'errors.role_not_found': 'یہ رول نہیں ملا۔',
  'errors.rule_not_found': 'یہ قاعدہ اب موجود نہیں۔',
  'errors.rule_refused': '{{message_ur}}',
  'errors.saved_search_limit': 'آپ محفوظ تلاشوں کی حد تک پہنچ گئے ہیں۔ پہلے ایک حذف کریں۔',
  'errors.saved_search_not_found': 'یہ محفوظ تلاش موجود نہیں ہے۔',
  'errors.scale_value_not_found': 'یہ قدر موجود نہیں۔',
  'errors.server_busy': 'میل سرور مصروف تھا۔',
  'errors.service_category_in_use':
    'اس کیٹیگری میں ابھی آئٹمز یا کیٹیگریز موجود ہیں۔ پہلے انہیں منتقل یا حذف کریں۔',
  'errors.service_category_not_found': 'یہ کیٹیگری موجود نہیں۔',
  'errors.service_identity_managed':
    'یہ ایک کنیکٹر کی اپنی شناخت ہے۔ اسے ایڈمن › انٹیگریشنز سے تبدیل کریں۔',
  'errors.service_unavailable':
    'سروس عارضی طور پر دستیاب نہیں۔ براہِ کرم تھوڑی دیر بعد دوبارہ کوشش کریں۔',
  'errors.session_expired': 'آپ کا سیشن ختم ہو گیا ہے۔ براہِ کرم دوبارہ سائن اِن کریں۔',
  'errors.session_not_found': 'یہ سیشن پہلے ہی ختم ہو چکا ہے یا آپ کا نہیں ہے۔',
  'errors.sign_in_not_allowed': 'آپ کے اکاؤنٹ کے لیے سائن اِن بند ہے۔ اپنے منتظم سے رابطہ کریں۔',
  'errors.sign_in_unknown_person':
    'آپ کی تنظیم نے ابھی آپ کو SupportX میں شامل نہیں کیا۔ رسائی کے لیے اپنے سروس ڈیسک سے رابطہ کریں۔',
  'errors.site_not_found': 'سائٹ نہیں ملی۔',
  'errors.sla_fallback_required':
    'ڈیفالٹ پالیسی حذف نہیں ہو سکتی: یہ تب لاگو ہوتی ہے جب کوئی اور پالیسی لاگو نہ ہو۔',
  'errors.sla_policy_not_found': 'یہ ایس ایل اے پالیسی موجود نہیں یا حذف کر دی گئی ہے۔',
  'errors.sla_record_type_not_found': 'اس قسم کے ریکارڈ کے لیے سروس کے اہداف دستیاب نہیں۔',
  'errors.sla_target_done':
    'یہ SLA ہدف پورا ہو چکا ہے یا رک چکا ہے، اس لیے اس کی مقررہ تاریخ اب نہیں بدل سکتی۔',
  'errors.sla_target_not_found': 'اس واقعے کا ایسا کوئی SLA ہدف نہیں ہے۔',
  'errors.special_hours_not_found': 'یہ مخصوص اوقات موجود نہیں یا ہٹا دیے گئے ہیں۔',
  'errors.sso_not_tested': 'چالو کرنے سے پہلے سیٹ اپ کو ایک سائن اِن سے آزمائیں۔',
  'errors.sso_provider_limit': 'آپ زیادہ سے زیادہ {{max}} سنگل سائن آن سیٹ اپ رکھ سکتے ہیں۔',
  'errors.sso_provider_missing':
    'یہ سیٹ اپ سائن اِن کی سروس میں موجود نہیں۔ اسے ہٹا کر دوبارہ شامل کریں۔',
  'errors.sso_provider_not_found': 'یہ سنگل سائن آن سیٹ اپ نہیں ملا۔',
  'errors.sso_provider_refused':
    'سائن اِن کی سروس نے یہ ترتیبات قبول نہیں کیں۔ انہیں جانچ کر دوبارہ کوشش کریں۔',
  'errors.sso_switch_off_first':
    'رابطے کا طریقہ بدلنے سے پہلے سیٹ اپ بند کریں، تاکہ کوئی باہر نہ رہ جائے۔',
  'errors.sso_switched_off': 'آزمانے سے پہلے سیٹ اپ چالو کریں یا اسے بدلیں۔',
  'errors.sso_test_not_found': 'یہ آزمائش ختم ہو گئی۔ نئی شروع کریں۔',
  'errors.stage_move_not_allowed':
    'موجودہ حیثیت سے یہ منتقلی ممکن نہیں۔ تازہ ترین دیکھنے کے لیے دوبارہ لوڈ کریں۔',
  'errors.stage_move_refused': 'اس منتقلی سے پہلے کچھ کام باقی ہے۔ ریکارڈ پر وجوہات دیکھیں۔',
  'errors.stage_not_found': 'یہ مرحلہ موجود نہیں۔',
  'errors.stage_path_disabled': 'یہ راستہ نئے ریکارڈز کے لیے بند ہے۔',
  'errors.stage_status_system_only': 'یہ حیثیت صرف منظوری کے فیصلے سے لگتی ہے۔',
  'errors.standard_change_locked':
    'معیاری تبدیلی اپنا منصوبہ منظور شدہ حالت میں رکھتی ہے۔ اسے بدلنے سے یہ عام تبدیلی بن جائے گی، جسے عام منظوری درکار ہے۔',
  'errors.status_not_found': 'یہ حالت اب موجود نہیں۔',
  'errors.storage_not_configured': 'اس تنصیب کے لیے فائل اسٹوریج ترتیب نہیں دی گئی۔',
  'errors.storage_quota_exceeded':
    'آپ کی تنظیم کا فائل اسٹوریج بھر گیا ہے ({{used_gb}} از {{limit_gb}} GB)۔',
  'errors.storage_unavailable':
    'فائل اسٹوریج تک رسائی نہیں ہو سکی۔ بعد میں کوشش کریں یا منتظم سے رابطہ کریں۔',
  'errors.system_calendar_required':
    'ہر ادارہ یہ کیلنڈر رکھتا ہے، اس لیے اسے حذف نہیں کیا جا سکتا۔',
  'errors.system_role_immutable': 'پہلے سے موجود کردار تبدیل یا حذف نہیں کیے جا سکتے۔',
  'errors.system_role_not_deletable':
    'بلٹ ان رولز حذف نہیں کیے جا سکتے۔ اپنا ورژن بنانے کے لیے رول کی نقل بنائیں۔',
  'errors.technician_limit_reached':
    'آپ کے ادارے کے پلان میں ٹیکنیشن کی تمام نشستیں استعمال میں ہیں۔ نشست خالی کرنے یا مزید شامل کرنے کے لیے اپنے منتظم سے کہیں۔',
  'errors.technicians_only': 'صرف ٹیکنیشن دوسرے صارفین کو دیکھ سکتا ہے۔',
  'errors.template_not_found': 'یہ سانچہ اب موجود نہیں۔',
  'errors.tenant_admin_is_technician':
    'ٹیننٹ منتظم ٹیکنیشن ہی رہتا ہے۔ پہلے منتظم کا کردار ہٹائیں۔',
  'errors.tenant_not_found': 'آپ کا ادارہ نہیں مل سکا۔',
  'errors.tenant_not_provisioned':
    'آپ کا ادارہ ابھی SupportX میں ترتیب نہیں دیا گیا۔ براہِ کرم اپنے منتظم سے رابطہ کریں۔',
  'errors.tenant_suspended': 'آپ کے ادارے کی رسائی معطل ہے۔',
  'errors.too_many_favourites': 'آپ زیادہ سے زیادہ {{max}} رپورٹس کو ستارہ لگا سکتے ہیں۔',
  'errors.too_many_files': 'ایک ساتھ بہت زیادہ فائلیں: زیادہ سے زیادہ {{max}}۔',
  'errors.too_many_rules': 'ہر ریکارڈ قسم کے لیے زیادہ سے زیادہ {{max}} قاعدے۔',
  'errors.transition_not_allowed': 'حالت کی یہ تبدیلی اس ریکارڈ پر آپ کے لیے دستیاب نہیں۔',
  'errors.transition_not_found': 'حالت کی یہ تبدیلی لائف سائیکل کا حصہ نہیں۔',
  'errors.unauthenticated': 'جاری رکھنے کے لیے براہِ کرم سائن اِن کریں۔',
  'errors.unknown_record_type': 'اس قسم کے ریکارڈ کے لیے آٹومیشن دستیاب نہیں۔',
  'errors.unsupported_media_type': 'یہ فائل یا مواد کی قسم معاون نہیں۔',
  'errors.user_disabled':
    'آپ کا اکاؤنٹ غیر فعال کر دیا گیا ہے۔ براہِ کرم اپنے منتظم سے رابطہ کریں۔',
  'errors.user_email_conflict':
    'آپ کے ادارے میں ایک اور اکاؤنٹ پہلے سے یہ ای میل پتہ استعمال کرتا ہے۔',
  'errors.user_not_found': 'صارف نہیں ملا۔',
  'errors.validation_failed': 'کچھ فیلڈز پر توجہ درکار ہے۔',
  'errors.vendor_in_use':
    'ریکارڈز ابھی بھی اس وینڈر کا نام لیتے ہیں ({{used}})۔ اس کے بجائے اسے غیر فعال کریں۔',
  'errors.vendor_not_found': 'یہ وینڈر اب موجود نہیں۔',
  'errors.version_conflict':
    'آپ کے کھولنے کے بعد کسی اور نے یہ آئٹم محفوظ کر دیا۔ ان کی تبدیلیاں دیکھنے کے لیے دوبارہ لوڈ کریں۔',
  'errors.withdraw_not_allowed': 'صرف درخواست گزار یہ درخواست واپس لے سکتا ہے۔',
  'errors.withdraw_not_pending': 'صرف منظوری کی منتظر درخواست واپس لی جا سکتی ہے۔',
  'errors.work_item_link_not_found': 'یہ ربط اب موجود نہیں۔',
  'errors.work_item_not_found': 'یہ ریکارڈ موجود نہیں یا آپ اسے نہیں دیکھ سکتے۔',
  'errors.work_item_task_not_found': 'یہ کام اب موجود نہیں۔',
  'errors.work_item_view_not_found': 'یہ محفوظ ویو اب موجود نہیں، یا آپ کے ساتھ شیئر نہیں کیا گیا۔',
  'errors.work_item_worklog_not_found': 'یہ ورک لاگ اب موجود نہیں۔',
  'errors.would_lose_access':
    'اس تبدیلی کے بعد آپ {{display_id}} نہیں دیکھ سکیں گے۔ حوالے کرنے کے لیے تصدیق کریں۔',
};
