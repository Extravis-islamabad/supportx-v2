# Urdu review: what to check and how

A native speaker reviews SupportX's Urdu before the pilot (product owner, 2026-11-04). Every
label has an Urdu translation, except one key kept in English on purpose (a test proves the
English fallback with it). Most of the older keys were translated in one batch (#190), so
wording, consistency and tone are what need a human eye.

## Switching the console to Urdu (shared stack)

1. Open the console on the shared stack: <http://localhost:5273>. The portal is on
   <http://localhost:5174>.
2. Sign in with the account the coordinator gives you. Use a reviewer account, never a
   colleague's.
3. Top right, open **Appearance** (the paint-bucket icon) and choose **اردو** under Language. The
   whole console switches to Urdu, right to left, and the choice is saved with your account, so
   it follows you to other browsers.
4. If اردو is missing from the list, the tenant does not offer Urdu: an admin switches it on in
   Admin › Instance settings › Languages offered.
5. To go back to English, choose **English** in the same place.

Note any wrong, unclear or inconsistent wording with the screen, the exact text and your
suggestion. A screenshot helps.

## Screens to check

| Area                   | Where                                                 | What to look at                                                                                       |
| ---------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Shell                  | Every page                                            | Navigation menu, header, breadcrumbs, notices, the command palette (Ctrl K)                           |
| Home                   | Home                                                  | Welcome, plan and seats, dashboard titles                                                             |
| Incidents              | Incidents list, an incident record                    | Columns, filters, statuses, priorities, the conversation (reply, note), history, SLA timers           |
| New incident           | Incidents › New                                       | Field names, help texts, required-field messages                                                      |
| Knowledge              | Knowledge, an article, the editor, the approval inbox | Article states, the editor's buttons, votes and feedback                                              |
| Reports and dashboards | Reports, Dashboards                                   | Report names, chart titles, time ranges                                                               |
| Announcements          | Announcements                                         | Severities, audiences, the publish window                                                             |
| My profile             | Avatar › My profile                                   | Display and region (theme, text size, formats, digits), notifications, signature                      |
| Admin                  | Admin (setup home)                                    | Every setup page's name and explanation, the search, roles and permissions, people, instance settings |
| Errors                 | Anywhere                                              | Messages after a refused or invalid action (e.g. save a form with a required field empty)             |
| Portal                 | <http://localhost:5174>                               | Home, catalog, my requests                                                                            |

## Label files

The Urdu text lives in `frontend/packages/labels/src/resources/<module>/ur.ts`, one file per
module, next to the English (`en.ts`) and Arabic (`ar.ts`) of the same keys:

| Module            |   Urdu labels | What it covers                                               |
| ----------------- | ------------: | ------------------------------------------------------------ |
| `shared`          |           462 | Shell, navigation, actions, filters, appearance, setup home  |
| `errors`          |           559 | Every error message                                          |
| `identity_access` |           730 | Sign-in, people, roles, permissions, profile and preferences |
| `work_items`      |           809 | Incidents: fields, statuses, conversation, history, tasks    |
| `knowledge`       |           292 | Knowledge base                                               |
| `analytics`       |           462 | Reports and dashboards                                       |
| `audit`           |           511 | Audit log, event names                                       |
| `automation`      |           210 | Rules and triggers                                           |
| `sla`             |           179 | Service levels                                               |
| `notifications`   |           220 | Notifications and preferences                                |
| `integrations`    |           304 | Mail, directories, connectors                                |
| `organization`    |           151 | Sites, groups, branding, instance settings                   |
| `announcements`   |            72 | Announcements                                                |
| `licensing`       |            72 | Plan, licence, features                                      |
| `metadata`        |           104 | Custom fields                                                |
| `files`           |            66 | Attachments                                                  |
| `ai`              | (with WP-037) | AI settings and assistance                                   |

Suggested corrections can come as notes or as a list of `key: new text`. A developer applies
them, and `make labels-sort` keeps each file in order.

## Service catalog starter (WP-031, D-138)

The starter catalog every new tenant gets (`backend/app/modules/service_catalog/domain/starter.py`).
Arabic (Modern Standard Arabic) and Urdu are both drafts for native-speaker review: correct the
wording in that file; the English is approved. Each row: English | Arabic | Urdu.

### Categories

| English                  | Arabic              | Urdu                  |
| ------------------------ | ------------------- | --------------------- |
| Accounts and access      | الحسابات والصلاحيات | اکاؤنٹس اور رسائی     |
| Hardware                 | الأجهزة             | ہارڈویئر              |
| Software                 | البرامج             | سافٹ ویئر             |
| Workplace                | مكان العمل          | کام کی جگہ            |
| People and HR            | الموارد البشرية     | عملہ اور انسانی وسائل |
| Leaving the organisation | مغادرة المؤسسة      | ادارہ چھوڑنا          |

### New user account

| English                                          | Arabic                         | Urdu                                        |
| ------------------------------------------------ | ------------------------------ | ------------------------------------------- |
| New user account                                 | حساب مستخدم جديد               | نیا صارف اکاؤنٹ                             |
| An account for someone joining the organisation. | حساب لموظف ينضم إلى المؤسسة.   | ادارے میں شامل ہونے والے فرد کے لیے اکاؤنٹ۔ |
| Full name of the new person                      | الاسم الكامل للشخص الجديد      | نئے فرد کا پورا نام                         |
| Start date                                       | تاريخ المباشرة                 | کام شروع کرنے کی تاریخ                      |
| Job title                                        | المسمى الوظيفي                 | عہدہ                                        |
| Department                                       | القسم                          | شعبہ                                        |
| Create the account                               | إنشاء الحساب                   | اکاؤنٹ بنائیں                               |
| Add to the right groups                          | الإضافة إلى المجموعات المناسبة | مناسب گروپوں میں شامل کریں                  |
| Send the sign-in details                         | إرسال بيانات الدخول            | سائن اِن کی تفصیلات بھیجیں                  |

### Access to an application

| English                                            | Arabic                               | Urdu                                                 |
| -------------------------------------------------- | ------------------------------------ | ---------------------------------------------------- |
| Access to an application                           | صلاحية الوصول إلى تطبيق              | کسی ایپلیکیشن تک رسائی                               |
| Ask for access to a system you need for your work. | اطلب الوصول إلى نظام تحتاجه في عملك. | اپنے کام کے لیے درکار سسٹم تک رسائی کی درخواست کریں۔ |
| Application                                        | التطبيق                              | ایپلیکیشن                                            |
| Level of access                                    | مستوى الصلاحية                       | رسائی کی سطح                                         |
| Why you need it                                    | سبب الحاجة                           | ضرورت کی وجہ                                         |
| Read only                                          | قراءة فقط                            | صرف دیکھنا                                           |
| Change                                             | تعديل                                | تبدیلی                                               |
| Administer                                         | إدارة                                | انتظام                                               |
| Grant the access                                   | منح الصلاحية                         | رسائی دیں                                            |
| Tell the requester                                 | إبلاغ مقدم الطلب                     | درخواست گزار کو مطلع کریں                            |

### Password or MFA reset help

| English                                                                  | Arabic                                                                         | Urdu                                                                                     |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- |
| Password or MFA reset help                                               | المساعدة في إعادة تعيين كلمة المرور أو التحقق متعدد العوامل                    | پاس ورڈ یا ایم ایف اے ری سیٹ میں مدد                                                     |
| Locked out? Try "Forgot password?" first; we help if that does not work. | هل تعذّر عليك الدخول؟ جرّب أولاً «نسيت كلمة المرور؟»، وسنساعدك إن لم ينجح ذلك. | سائن اِن نہیں ہو پا رہا؟ پہلے "پاس ورڈ بھول گئے؟" آزمائیں؛ کام نہ بنے تو ہم مدد کریں گے۔ |
| Which account                                                            | أي حساب                                                                        | کون سا اکاؤنٹ                                                                            |
| What needs resetting                                                     | ما الذي يحتاج إلى إعادة تعيين                                                  | کیا ری سیٹ کرنا ہے                                                                       |
| Password                                                                 | كلمة المرور                                                                    | پاس ورڈ                                                                                  |
| MFA (sign-in check)                                                      | التحقق متعدد العوامل                                                           | ایم ایف اے (دوہری تصدیق)                                                                 |
| Confirm who is asking                                                    | التحقق من هوية مقدم الطلب                                                      | درخواست گزار کی شناخت کی تصدیق کریں                                                      |
| Reset and tell the requester                                             | إعادة التعيين وإبلاغ مقدم الطلب                                                | ری سیٹ کریں اور درخواست گزار کو بتائیں                                                   |

Description (shown before the form):

- en: <p><strong>Before you ask:</strong> on the sign-in page choose <em>Forgot password?</em> and follow the e-mail. The help article on resetting your password shows each step, also for a new MFA device.</p><p>Still locked out? Fill in the form and we will help you.</p>
- ar: <p><strong>قبل أن تطلب:</strong> اختر <em>نسيت كلمة المرور؟</em> في صفحة تسجيل الدخول واتبع الرسالة الإلكترونية. يشرح مقال المساعدة عن إعادة تعيين كلمة المرور كل خطوة، وكذلك تسجيل جهاز جديد للتحقق متعدد العوامل.</p><p>ما زلت لا تستطيع الدخول؟ املأ النموذج وسنساعدك.</p>
- ur: <p><strong>درخواست سے پہلے:</strong> سائن اِن کے صفحے پر <em>پاس ورڈ بھول گئے؟</em> منتخب کریں اور ای میل میں دی گئی ہدایات پر عمل کریں۔ پاس ورڈ ری سیٹ کرنے کا مددگار مضمون ہر قدم بتاتا ہے، نئے ایم ایف اے آلے کے لیے بھی۔</p><p>اب بھی سائن اِن نہیں ہو پا رہا؟ فارم پُر کریں، ہم آپ کی مدد کریں گے۔</p>

### VPN / remote access

| English                                                | Arabic                                  | Urdu                                        |
| ------------------------------------------------------ | --------------------------------------- | ------------------------------------------- |
| VPN / remote access                                    | الوصول عن بُعد (VPN)                    | وی پی این / دور سے رسائی                    |
| Work from outside the office over a secure connection. | اعمل من خارج المكتب عبر اتصال آمن.      | محفوظ کنکشن کے ذریعے دفتر سے باہر کام کریں۔ |
| Needed until (leave empty if ongoing)                  | مطلوب حتى (اتركه فارغاً إن كان مستمراً) | کب تک درکار ہے (مستقل ہو تو خالی چھوڑ دیں)  |
| Why you need it                                        | سبب الحاجة                              | ضرورت کی وجہ                                |
| Grant VPN access                                       | منح صلاحية VPN                          | وی پی این رسائی دیں                         |
| Send the set-up guide                                  | إرسال دليل الإعداد                      | سیٹ اپ گائیڈ بھیجیں                         |

### New laptop

| English                                                             | Arabic                                     | Urdu                                                   |
| ------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------------------ |
| New laptop                                                          | حاسوب محمول جديد                           | نیا لیپ ٹاپ                                            |
| A laptop for a new starter or to replace one that is past its life. | حاسوب لموظف جديد أو بديل لجهاز انتهى عمره. | نئے ملازم کے لیے، یا پرانے لیپ ٹاپ کی جگہ نیا لیپ ٹاپ۔ |
| Model                                                               | الطراز                                     | ماڈل                                                   |
| Needed by                                                           | مطلوب بحلول                                | کب تک درکار ہے                                         |
| Reason                                                              | السبب                                      | وجہ                                                    |
| Standard                                                            | قياسي                                      | معیاری                                                 |
| Performance                                                         | عالي الأداء                                | زیادہ کارکردگی والا                                    |
| New starter                                                         | موظف جديد                                  | نیا ملازم                                              |
| Replacement                                                         | استبدال                                    | تبدیلی                                                 |
| Broken                                                              | عطل                                        | خراب                                                   |
| Order or take from stock                                            | الطلب أو الصرف من المخزون                  | آرڈر کریں یا اسٹاک سے لیں                              |
| Prepare and install the standard software                           | التجهيز وتثبيت البرامج القياسية            | تیار کریں اور معیاری سافٹ ویئر انسٹال کریں             |
| Hand it over                                                        | التسليم                                    | حوالے کریں                                             |

### Monitor, keyboard or mouse

| English                    | Arabic                      | Urdu                      |
| -------------------------- | --------------------------- | ------------------------- |
| Monitor, keyboard or mouse | شاشة أو لوحة مفاتيح أو فأرة | مانیٹر، کی بورڈ یا ماؤس   |
| Accessories for your desk. | ملحقات لمكتبك.              | آپ کی میز کے لیے لوازمات۔ |
| Item                       | الصنف                       | چیز                       |
| Monitor                    | شاشة                        | مانیٹر                    |
| Keyboard                   | لوحة مفاتيح                 | کی بورڈ                   |
| Mouse                      | فأرة                        | ماؤس                      |
| Headset                    | سماعة رأس                   | ہیڈ سیٹ                   |
| Hand it over               | التسليم                     | حوالے کریں                |

### Mobile phone

| English                                        | Arabic                                   | Urdu                                          |
| ---------------------------------------------- | ---------------------------------------- | --------------------------------------------- |
| Mobile phone                                   | هاتف محمول                               | موبائل فون                                    |
| A work phone, with a number and e-mail set up. | هاتف للعمل مع رقم وبريد إلكتروني جاهزين. | کام کے لیے فون، نمبر اور ای میل کے ساتھ تیار۔ |
| Why you need it                                | سبب الحاجة                               | ضرورت کی وجہ                                  |
| Order the phone and SIM                        | طلب الهاتف وشريحة الاتصال                | فون اور سم منگوائیں                           |
| Set up mail and security                       | إعداد البريد والحماية                    | ای میل اور سیکیورٹی سیٹ اپ کریں               |
| Hand it over                                   | التسليم                                  | حوالے کریں                                    |

### Install software

| English                             | Arabic                   | Urdu                              |
| ----------------------------------- | ------------------------ | --------------------------------- |
| Install software                    | تثبيت برنامج             | سافٹ ویئر انسٹال کرنا             |
| Software you need on your computer. | برنامج تحتاجه على جهازك. | آپ کے کمپیوٹر پر درکار سافٹ ویئر۔ |
| Software name                       | اسم البرنامج             | سافٹ ویئر کا نام                  |
| Is a licence needed?                | هل يحتاج إلى ترخيص؟      | کیا لائسنس درکار ہے؟              |
| Check the licence                   | التحقق من الترخيص        | لائسنس چیک کریں                   |
| Install                             | التثبيت                  | انسٹال کریں                       |

### Shared mailbox or distribution list

| English                                                       | Arabic                                                 | Urdu                                                      |
| ------------------------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------------- |
| Shared mailbox or distribution list                           | صندوق بريد مشترك أو قائمة توزيع                        | مشترکہ میل باکس یا ڈسٹری بیوشن لسٹ                        |
| A mailbox a team shares, or one address that reaches a group. | صندوق بريد يتشاركه فريق، أو عنوان واحد يصل إلى مجموعة. | ٹیم کا مشترکہ میل باکس، یا ایک پتہ جو پورے گروپ تک پہنچے۔ |
| Type                                                          | النوع                                                  | قسم                                                       |
| Address wanted                                                | العنوان المطلوب                                        | مطلوبہ پتہ                                                |
| Members                                                       | الأعضاء                                                | اراکین                                                    |
| Shared mailbox                                                | صندوق بريد مشترك                                       | مشترکہ میل باکس                                           |
| Distribution list                                             | قائمة توزيع                                            | ڈسٹری بیوشن لسٹ                                           |
| Create it                                                     | الإنشاء                                                | بنائیں                                                    |
| Add the members                                               | إضافة الأعضاء                                          | اراکین شامل کریں                                          |

### Desk or room move

| English                                              | Arabic                                    | Urdu                                              |
| ---------------------------------------------------- | ----------------------------------------- | ------------------------------------------------- |
| Desk or room move                                    | نقل مكتب أو غرفة                          | میز یا کمرے کی منتقلی                             |
| Moving to another desk or room, with your equipment. | الانتقال إلى مكتب أو غرفة أخرى مع أجهزتك. | اپنے آلات کے ساتھ کسی اور میز یا کمرے میں منتقلی۔ |
| From                                                 | من                                        | کہاں سے                                           |
| To                                                   | إلى                                       | کہاں                                              |
| Date                                                 | التاريخ                                   | تاریخ                                             |
| Move the equipment                                   | نقل الأجهزة                               | آلات منتقل کریں                                   |
| Check the network at the new place                   | فحص الشبكة في المكان الجديد               | نئی جگہ پر نیٹ ورک چیک کریں                       |

### Building access card

| English                           | Arabic                     | Urdu                      |
| --------------------------------- | -------------------------- | ------------------------- |
| Building access card              | بطاقة دخول المبنى          | عمارت میں داخلے کا کارڈ   |
| A new or replacement access card. | بطاقة دخول جديدة أو بديلة. | نیا یا متبادل داخلہ کارڈ۔ |
| New or replacement                | جديدة أو بديلة             | نیا یا متبادل             |
| New card                          | بطاقة جديدة                | نیا کارڈ                  |
| Replacement                       | بطاقة بديلة                | متبادل کارڈ               |
| Issue the card                    | إصدار البطاقة              | کارڈ جاری کریں            |

### Employment letter

| English                                                        | Arabic                               | Urdu                                                   |
| -------------------------------------------------------------- | ------------------------------------ | ------------------------------------------------------ |
| Employment letter                                              | خطاب تعريف بالعمل                    | ملازمت کا تصدیقی خط                                    |
| A letter confirming your employment, for a bank or an embassy. | خطاب يؤكد عملك لدى البنك أو السفارة. | بینک یا سفارت خانے کے لیے آپ کی ملازمت کی تصدیق کا خط۔ |
| Addressed to                                                   | موجّه إلى                            | کس کے نام                                              |
| Language                                                       | اللغة                                | زبان                                                   |
| English                                                        | الإنجليزية                           | انگریزی                                                |
| Arabic                                                         | العربية                              | عربی                                                   |
| Prepare and sign the letter                                    | إعداد الخطاب وتوقيعه                 | خط تیار کریں اور دستخط کریں                            |

### New joiner (onboarding)

| English                                                      | Arabic                                                 | Urdu                                                   |
| ------------------------------------------------------------ | ------------------------------------------------------ | ------------------------------------------------------ |
| New joiner (onboarding)                                      | موظف جديد (التهيئة)                                    | نیا ملازم (آن بورڈنگ)                                  |
| Everything a new colleague needs on day one, in one request. | كل ما يحتاجه الزميل الجديد في يومه الأول، في طلب واحد. | نئے ساتھی کو پہلے دن درکار ہر چیز، ایک ہی درخواست میں۔ |
| Full name of the new person                                  | الاسم الكامل للشخص الجديد                              | نئے فرد کا پورا نام                                    |
| Start date                                                   | تاريخ المباشرة                                         | کام شروع کرنے کی تاریخ                                 |
| Job title                                                    | المسمى الوظيفي                                         | عہدہ                                                   |
| Needs a laptop                                               | يحتاج إلى حاسوب محمول                                  | لیپ ٹاپ درکار ہے                                       |
| Applications they need                                       | التطبيقات التي يحتاجها                                 | درکار ایپلیکیشنز                                       |
| Create the account                                           | إنشاء الحساب                                           | اکاؤنٹ بنائیں                                          |
| Prepare the laptop                                           | تجهيز الحاسوب المحمول                                  | لیپ ٹاپ تیار کریں                                      |
| Grant access to the applications                             | منح الوصول إلى التطبيقات                               | ایپلیکیشنز تک رسائی دیں                                |
| Welcome on the first day                                     | الاستقبال في اليوم الأول                               | پہلے دن خوش آمدید                                      |

### Someone is leaving

| English                                                                   | Arabic                                                          | Urdu                                                                 |
| ------------------------------------------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------- |
| Someone is leaving                                                        | موظف سيغادر                                                     | کوئی ملازم ادارہ چھوڑ رہا ہے                                         |
| Tell us when someone leaves, so access and equipment are handled on time. | أخبرنا عند مغادرة موظف حتى تُعالَج الصلاحيات والأجهزة في وقتها. | کسی کے جانے کی اطلاع دیں تاکہ رسائی اور آلات کا بروقت انتظام ہو سکے۔ |
| Who is leaving                                                            | من سيغادر                                                       | کون جا رہا ہے                                                        |
| Last day                                                                  | آخر يوم عمل                                                     | آخری دن                                                              |
| Collect the equipment                                                     | استلام الأجهزة                                                  | آلات واپس لیں                                                        |
| Close the accounts on the last day                                        | إغلاق الحسابات في آخر يوم                                       | آخری دن اکاؤنٹس بند کریں                                             |
| Remove building access                                                    | إلغاء صلاحية دخول المبنى                                        | عمارت میں داخلے کی اجازت ختم کریں                                    |
