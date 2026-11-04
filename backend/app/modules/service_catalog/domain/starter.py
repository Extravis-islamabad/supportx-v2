# ruff: noqa: RUF001 - Urdu text ends sentences with the Urdu full stop (U+06D4), as it should.
"""The starter catalog (WP-031, D-138; REQ-CAT-007). Data only, no I/O.

What a new tenant starts with: 6 categories and 14 items, in English, Arabic and Urdu, in
SupportX's own words (approved by the product owner on 2026-11-04; Arabic and Urdu flagged for
native-speaker review in docs/guides/urdu-review.md). Every item is seeded as a draft: the admin
chooses the fulfilment group and publishes (plan D9). All of it can be changed or deleted.

"Manager approval" is the manager of the person the request is for. Internal tasks show
requesters only "step n of m".
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

Texts = Mapping[str, str]


def t(en: str, ar: str, ur: str) -> dict[str, str]:
    """One text in the three languages."""
    return {"en": en, "ar": ar, "ur": ur}


@dataclass(frozen=True)
class StarterQuestion:
    """One form question."""

    key: str
    label: Texts
    kind: str
    required: bool = False
    options: Sequence[tuple[str, Texts]] = ()
    default: Any = None

    def as_values(self) -> dict[str, Any]:
        """As the catalog API takes it."""
        return {
            "key": self.key,
            "label": dict(self.label),
            "kind": self.kind,
            "required": self.required,
            "options": [code for code, _ in self.options],
            "option_labels": {code: dict(words) for code, words in self.options},
            "default": self.default,
        }


@dataclass(frozen=True)
class StarterTask:
    """One fulfilment task."""

    title: Texts
    internal: bool = False


@dataclass(frozen=True)
class StarterItem:
    """One item: where it sits, what it asks, who approves, what gets done."""

    key: str
    category: str
    icon: str
    names: Texts
    summaries: Texts
    questions: Sequence[StarterQuestion]
    tasks: Sequence[StarterTask]
    manager_approval: bool
    priority: str = "p3"
    descriptions: Texts = field(default_factory=dict)
    keywords: Mapping[str, Sequence[str]] = field(default_factory=dict)
    subject_template: str | None = None
    also_in: Sequence[str] = ()

    def as_values(self) -> dict[str, Any]:
        """As the catalog API takes it (category IDs are filled in by the seed)."""
        return {
            "names": dict(self.names),
            "summaries": dict(self.summaries),
            "descriptions": dict(self.descriptions),
            "keywords": {lang: list(words) for lang, words in self.keywords.items()},
            "icon": self.icon,
            "questions": [q.as_values() for q in self.questions],
            "approval": (
                {"approvers": [{"kind": "requested_for_manager"}]}
                if self.manager_approval
                else None
            ),
            "plan": [
                {"title": dict(task.title), "required": True, "internal": task.internal}
                for task in self.tasks
            ],
            "default_priority": self.priority,
            "subject_template": self.subject_template,
        }


@dataclass(frozen=True)
class StarterCategory:
    """One category."""

    key: str
    icon: str
    names: Texts


# --- shared wording -------------------------------------------------------------------------------

WHY = t("Why you need it", "سبب الحاجة", "ضرورت کی وجہ")
HAND_OVER = StarterTask(t("Hand it over", "التسليم", "حوالے کریں"))
FULL_NAME = StarterQuestion(
    "full_name",
    t("Full name of the new person", "الاسم الكامل للشخص الجديد", "نئے فرد کا پورا نام"),
    "text",
    required=True,
)
START_DATE = StarterQuestion(
    "start_date", t("Start date", "تاريخ المباشرة", "کام شروع کرنے کی تاریخ"), "date", required=True
)
JOB_TITLE = StarterQuestion("job_title", t("Job title", "المسمى الوظيفي", "عہدہ"), "text")
CREATE_ACCOUNT = StarterTask(t("Create the account", "إنشاء الحساب", "اکاؤنٹ بنائیں"))

CATEGORIES: tuple[StarterCategory, ...] = (
    StarterCategory(
        "accounts", "account", t("Accounts and access", "الحسابات والصلاحيات", "اکاؤنٹس اور رسائی")
    ),
    StarterCategory("hardware", "laptop", t("Hardware", "الأجهزة", "ہارڈویئر")),
    StarterCategory("software", "software", t("Software", "البرامج", "سافٹ ویئر")),
    StarterCategory("workplace", "building", t("Workplace", "مكان العمل", "کام کی جگہ")),
    StarterCategory(
        "people", "people", t("People and HR", "الموارد البشرية", "عملہ اور انسانی وسائل")
    ),
    StarterCategory(
        "leaving", "offboarding", t("Leaving the organisation", "مغادرة المؤسسة", "ادارہ چھوڑنا")
    ),
)

ITEMS: tuple[StarterItem, ...] = (
    # --- 1. Accounts and access -------------------------------------------------------------------
    StarterItem(
        key="new_account",
        category="accounts",
        icon="account",
        names=t("New user account", "حساب مستخدم جديد", "نیا صارف اکاؤنٹ"),
        summaries=t(
            "An account for someone joining the organisation.",
            "حساب لموظف ينضم إلى المؤسسة.",
            "ادارے میں شامل ہونے والے فرد کے لیے اکاؤنٹ۔",
        ),
        questions=(
            FULL_NAME,
            START_DATE,
            JOB_TITLE,
            StarterQuestion("department", t("Department", "القسم", "شعبہ"), "text"),
        ),
        tasks=(
            CREATE_ACCOUNT,
            StarterTask(
                t(
                    "Add to the right groups",
                    "الإضافة إلى المجموعات المناسبة",
                    "مناسب گروپوں میں شامل کریں",
                )
            ),
            StarterTask(
                t("Send the sign-in details", "إرسال بيانات الدخول", "سائن اِن کی تفصیلات بھیجیں")
            ),
        ),
        manager_approval=True,
        subject_template="New user account: {full_name}",
    ),
    StarterItem(
        key="application_access",
        category="accounts",
        icon="access",
        names=t("Access to an application", "صلاحية الوصول إلى تطبيق", "کسی ایپلیکیشن تک رسائی"),
        summaries=t(
            "Ask for access to a system you need for your work.",
            "اطلب الوصول إلى نظام تحتاجه في عملك.",
            "اپنے کام کے لیے درکار سسٹم تک رسائی کی درخواست کریں۔",
        ),
        questions=(
            StarterQuestion(
                "application", t("Application", "التطبيق", "ایپلیکیشن"), "text", required=True
            ),
            StarterQuestion(
                "level",
                t("Level of access", "مستوى الصلاحية", "رسائی کی سطح"),
                "choice",
                required=True,
                options=(
                    ("read_only", t("Read only", "قراءة فقط", "صرف دیکھنا")),
                    ("change", t("Change", "تعديل", "تبدیلی")),
                    ("administer", t("Administer", "إدارة", "انتظام")),
                ),
            ),
            StarterQuestion("reason", WHY, "long_text", required=True),
        ),
        tasks=(
            StarterTask(t("Grant the access", "منح الصلاحية", "رسائی دیں")),
            StarterTask(t("Tell the requester", "إبلاغ مقدم الطلب", "درخواست گزار کو مطلع کریں")),
        ),
        manager_approval=True,
        subject_template="Access to {application} for {person}",
    ),
    StarterItem(
        key="password_reset",
        category="accounts",
        icon="security",
        names=t(
            "Password or MFA reset help",
            "المساعدة في إعادة تعيين كلمة المرور أو التحقق متعدد العوامل",
            "پاس ورڈ یا ایم ایف اے ری سیٹ میں مدد",
        ),
        summaries=t(
            'Locked out? Try "Forgot password?" first; we help if that does not work.',
            "هل تعذّر عليك الدخول؟ جرّب أولاً «نسيت كلمة المرور؟»، وسنساعدك إن لم ينجح ذلك.",
            'سائن اِن نہیں ہو پا رہا؟ پہلے "پاس ورڈ بھول گئے؟" آزمائیں؛'
            " کام نہ بنے تو ہم مدد کریں گے۔",
        ),
        # Self-service first (product owner, 2026-11-04): shown before the form.
        descriptions=t(
            "<p><strong>Before you ask:</strong> on the sign-in page choose"
            " <em>Forgot password?</em> and follow the e-mail. The help article on resetting your"
            " password shows each step,"
            " also for a new MFA device.</p><p>Still locked out? Fill in the form and we will help"
            " you.</p>",
            "<p><strong>قبل أن تطلب:</strong> اختر <em>نسيت كلمة المرور؟</em> في صفحة تسجيل الدخول"
            " واتبع الرسالة الإلكترونية. يشرح مقال المساعدة عن إعادة تعيين كلمة المرور كل خطوة،"
            " وكذلك تسجيل جهاز جديد للتحقق متعدد العوامل.</p><p>ما زلت لا تستطيع الدخول؟ املأ"
            " النموذج وسنساعدك.</p>",
            "<p><strong>درخواست سے پہلے:</strong> سائن اِن کے صفحے پر <em>پاس ورڈ بھول گئے؟</em>"
            " منتخب کریں اور ای میل میں دی گئی ہدایات پر عمل کریں۔ پاس ورڈ ری سیٹ کرنے کا مددگار"
            " مضمون ہر قدم بتاتا ہے، نئے ایم ایف اے آلے کے لیے بھی۔</p><p>اب بھی سائن اِن نہیں ہو"
            " پا رہا؟ فارم پُر کریں، ہم آپ کی مدد کریں گے۔</p>",
        ),
        keywords={
            "en": ["locked out", "sign in", "login", "2FA", "authenticator"],
            "ar": ["كلمة السر", "تسجيل الدخول", "قفل الحساب"],
            "ur": ["لاگ اِن", "سائن اِن", "اکاؤنٹ بند"],
        },
        questions=(
            StarterQuestion(
                "account", t("Which account", "أي حساب", "کون سا اکاؤنٹ"), "text", required=True
            ),
            StarterQuestion(
                "reset",
                t("What needs resetting", "ما الذي يحتاج إلى إعادة تعيين", "کیا ری سیٹ کرنا ہے"),
                "choice",
                required=True,
                options=(
                    ("password", t("Password", "كلمة المرور", "پاس ورڈ")),
                    (
                        "mfa",
                        t(
                            "MFA (sign-in check)",
                            "التحقق متعدد العوامل",
                            "ایم ایف اے (دوہری تصدیق)",
                        ),
                    ),
                ),
            ),
        ),
        tasks=(
            StarterTask(
                t(
                    "Confirm who is asking",
                    "التحقق من هوية مقدم الطلب",
                    "درخواست گزار کی شناخت کی تصدیق کریں",
                ),
                internal=True,
            ),
            StarterTask(
                t(
                    "Reset and tell the requester",
                    "إعادة التعيين وإبلاغ مقدم الطلب",
                    "ری سیٹ کریں اور درخواست گزار کو بتائیں",
                )
            ),
        ),
        manager_approval=False,
        priority="p2",  # quick fulfilment: the person cannot work meanwhile
    ),
    StarterItem(
        key="vpn",
        category="accounts",
        icon="vpn",
        names=t("VPN / remote access", "الوصول عن بُعد (VPN)", "وی پی این / دور سے رسائی"),
        summaries=t(
            "Work from outside the office over a secure connection.",
            "اعمل من خارج المكتب عبر اتصال آمن.",
            "محفوظ کنکشن کے ذریعے دفتر سے باہر کام کریں۔",
        ),
        questions=(
            StarterQuestion(
                "until",
                t(
                    "Needed until (leave empty if ongoing)",
                    "مطلوب حتى (اتركه فارغاً إن كان مستمراً)",
                    "کب تک درکار ہے (مستقل ہو تو خالی چھوڑ دیں)",
                ),
                "date",
            ),
            StarterQuestion("reason", WHY, "long_text", required=True),
        ),
        tasks=(
            StarterTask(t("Grant VPN access", "منح صلاحية VPN", "وی پی این رسائی دیں")),
            StarterTask(t("Send the set-up guide", "إرسال دليل الإعداد", "سیٹ اپ گائیڈ بھیجیں")),
        ),
        # On by default: remote access is a security-sensitive grant. A tenant removes the
        # approval on the item if it wants to (product owner, 2026-11-04).
        manager_approval=True,
    ),
    # --- 2. Hardware ------------------------------------------------------------------------------
    StarterItem(
        key="laptop",
        category="hardware",
        icon="laptop",
        names=t("New laptop", "حاسوب محمول جديد", "نیا لیپ ٹاپ"),
        summaries=t(
            "A laptop for a new starter or to replace one that is past its life.",
            "حاسوب لموظف جديد أو بديل لجهاز انتهى عمره.",
            "نئے ملازم کے لیے، یا پرانے لیپ ٹاپ کی جگہ نیا لیپ ٹاپ۔",
        ),
        keywords={"en": ["notebook", "computer"], "ar": ["لابتوب", "كمبيوتر"], "ur": ["کمپیوٹر"]},
        questions=(
            StarterQuestion(
                "model",
                t("Model", "الطراز", "ماڈل"),
                "choice",
                required=True,
                options=(
                    ("standard", t("Standard", "قياسي", "معیاری")),
                    ("performance", t("Performance", "عالي الأداء", "زیادہ کارکردگی والا")),
                ),
            ),
            StarterQuestion("needed_by", t("Needed by", "مطلوب بحلول", "کب تک درکار ہے"), "date"),
            StarterQuestion(
                "reason",
                t("Reason", "السبب", "وجہ"),
                "choice",
                options=(
                    ("new_starter", t("New starter", "موظف جديد", "نیا ملازم")),
                    ("replacement", t("Replacement", "استبدال", "تبدیلی")),
                    ("broken", t("Broken", "عطل", "خراب")),
                ),
            ),
        ),
        tasks=(
            StarterTask(
                t(
                    "Order or take from stock",
                    "الطلب أو الصرف من المخزون",
                    "آرڈر کریں یا اسٹاک سے لیں",
                ),
                internal=True,
            ),
            StarterTask(
                t(
                    "Prepare and install the standard software",
                    "التجهيز وتثبيت البرامج القياسية",
                    "تیار کریں اور معیاری سافٹ ویئر انسٹال کریں",
                )
            ),
            HAND_OVER,
        ),
        manager_approval=True,
    ),
    StarterItem(
        key="accessories",
        category="hardware",
        icon="monitor",
        names=t(
            "Monitor, keyboard or mouse", "شاشة أو لوحة مفاتيح أو فأرة", "مانیٹر، کی بورڈ یا ماؤس"
        ),
        summaries=t("Accessories for your desk.", "ملحقات لمكتبك.", "آپ کی میز کے لیے لوازمات۔"),
        questions=(
            StarterQuestion(
                "item",
                t("Item", "الصنف", "چیز"),
                "choice",
                required=True,
                options=(
                    ("monitor", t("Monitor", "شاشة", "مانیٹر")),
                    ("keyboard", t("Keyboard", "لوحة مفاتيح", "کی بورڈ")),
                    ("mouse", t("Mouse", "فأرة", "ماؤس")),
                    ("headset", t("Headset", "سماعة رأس", "ہیڈ سیٹ")),
                ),
            ),
        ),
        tasks=(HAND_OVER,),
        manager_approval=False,
    ),
    StarterItem(
        key="mobile_phone",
        category="hardware",
        icon="phone",
        names=t("Mobile phone", "هاتف محمول", "موبائل فون"),
        summaries=t(
            "A work phone, with a number and e-mail set up.",
            "هاتف للعمل مع رقم وبريد إلكتروني جاهزين.",
            "کام کے لیے فون، نمبر اور ای میل کے ساتھ تیار۔",
        ),
        questions=(StarterQuestion("reason", WHY, "long_text", required=True),),
        tasks=(
            StarterTask(
                t("Order the phone and SIM", "طلب الهاتف وشريحة الاتصال", "فون اور سم منگوائیں"),
                internal=True,
            ),
            StarterTask(
                t(
                    "Set up mail and security",
                    "إعداد البريد والحماية",
                    "ای میل اور سیکیورٹی سیٹ اپ کریں",
                )
            ),
            HAND_OVER,
        ),
        manager_approval=True,
    ),
    # --- 3. Software ------------------------------------------------------------------------------
    StarterItem(
        key="install_software",
        category="software",
        icon="software",
        names=t("Install software", "تثبيت برنامج", "سافٹ ویئر انسٹال کرنا"),
        summaries=t(
            "Software you need on your computer.",
            "برنامج تحتاجه على جهازك.",
            "آپ کے کمپیوٹر پر درکار سافٹ ویئر۔",
        ),
        questions=(
            StarterQuestion(
                "software",
                t("Software name", "اسم البرنامج", "سافٹ ویئر کا نام"),
                "text",
                required=True,
            ),
            StarterQuestion(
                "licence",
                t("Is a licence needed?", "هل يحتاج إلى ترخيص؟", "کیا لائسنس درکار ہے؟"),
                "yes_no",
            ),
        ),
        tasks=(
            StarterTask(
                t("Check the licence", "التحقق من الترخيص", "لائسنس چیک کریں"), internal=True
            ),
            StarterTask(t("Install", "التثبيت", "انسٹال کریں")),
        ),
        manager_approval=True,
        subject_template="Install {software}",
    ),
    StarterItem(
        key="shared_mailbox",
        category="software",
        icon="mail",
        names=t(
            "Shared mailbox or distribution list",
            "صندوق بريد مشترك أو قائمة توزيع",
            "مشترکہ میل باکس یا ڈسٹری بیوشن لسٹ",
        ),
        summaries=t(
            "A mailbox a team shares, or one address that reaches a group.",
            "صندوق بريد يتشاركه فريق، أو عنوان واحد يصل إلى مجموعة.",
            "ٹیم کا مشترکہ میل باکس، یا ایک پتہ جو پورے گروپ تک پہنچے۔",
        ),
        questions=(
            StarterQuestion(
                "type",
                t("Type", "النوع", "قسم"),
                "choice",
                required=True,
                options=(
                    ("shared_mailbox", t("Shared mailbox", "صندوق بريد مشترك", "مشترکہ میل باکس")),
                    ("distribution_list", t("Distribution list", "قائمة توزيع", "ڈسٹری بیوشن لسٹ")),
                ),
            ),
            StarterQuestion(
                "address",
                t("Address wanted", "العنوان المطلوب", "مطلوبہ پتہ"),
                "text",
                required=True,
            ),
            StarterQuestion("members", t("Members", "الأعضاء", "اراکین"), "long_text"),
        ),
        tasks=(
            StarterTask(t("Create it", "الإنشاء", "بنائیں")),
            StarterTask(t("Add the members", "إضافة الأعضاء", "اراکین شامل کریں")),
        ),
        manager_approval=True,
    ),
    # --- 4. Workplace -----------------------------------------------------------------------------
    StarterItem(
        key="desk_move",
        category="workplace",
        icon="desk",
        names=t("Desk or room move", "نقل مكتب أو غرفة", "میز یا کمرے کی منتقلی"),
        summaries=t(
            "Moving to another desk or room, with your equipment.",
            "الانتقال إلى مكتب أو غرفة أخرى مع أجهزتك.",
            "اپنے آلات کے ساتھ کسی اور میز یا کمرے میں منتقلی۔",
        ),
        questions=(
            StarterQuestion("from_place", t("From", "من", "کہاں سے"), "text", required=True),
            StarterQuestion("to_place", t("To", "إلى", "کہاں"), "text", required=True),
            StarterQuestion("move_date", t("Date", "التاريخ", "تاریخ"), "date", required=True),
        ),
        tasks=(
            StarterTask(t("Move the equipment", "نقل الأجهزة", "آلات منتقل کریں")),
            StarterTask(
                t(
                    "Check the network at the new place",
                    "فحص الشبكة في المكان الجديد",
                    "نئی جگہ پر نیٹ ورک چیک کریں",
                )
            ),
        ),
        manager_approval=True,
    ),
    StarterItem(
        key="access_card",
        category="workplace",
        icon="badge",
        names=t("Building access card", "بطاقة دخول المبنى", "عمارت میں داخلے کا کارڈ"),
        summaries=t(
            "A new or replacement access card.",
            "بطاقة دخول جديدة أو بديلة.",
            "نیا یا متبادل داخلہ کارڈ۔",
        ),
        questions=(
            StarterQuestion(
                "card",
                t("New or replacement", "جديدة أو بديلة", "نیا یا متبادل"),
                "choice",
                required=True,
                options=(
                    ("new", t("New card", "بطاقة جديدة", "نیا کارڈ")),
                    ("replacement", t("Replacement", "بطاقة بديلة", "متبادل کارڈ")),
                ),
            ),
        ),
        tasks=(StarterTask(t("Issue the card", "إصدار البطاقة", "کارڈ جاری کریں")),),
        manager_approval=False,
    ),
    # --- 5. People and HR -------------------------------------------------------------------------
    StarterItem(
        key="employment_letter",
        category="people",
        icon="document",
        names=t("Employment letter", "خطاب تعريف بالعمل", "ملازمت کا تصدیقی خط"),
        summaries=t(
            "A letter confirming your employment, for a bank or an embassy.",
            "خطاب يؤكد عملك لدى البنك أو السفارة.",
            "بینک یا سفارت خانے کے لیے آپ کی ملازمت کی تصدیق کا خط۔",
        ),
        questions=(
            StarterQuestion(
                "addressed_to", t("Addressed to", "موجّه إلى", "کس کے نام"), "text", required=True
            ),
            StarterQuestion(
                "language",
                t("Language", "اللغة", "زبان"),
                "choice",
                required=True,
                options=(
                    ("english", t("English", "الإنجليزية", "انگریزی")),
                    ("arabic", t("Arabic", "العربية", "عربی")),
                ),
            ),
        ),
        tasks=(
            StarterTask(
                t(
                    "Prepare and sign the letter",
                    "إعداد الخطاب وتوقيعه",
                    "خط تیار کریں اور دستخط کریں",
                )
            ),
        ),
        manager_approval=False,
    ),
    StarterItem(
        key="new_joiner",
        category="people",
        also_in=("accounts",),
        icon="onboarding",
        names=t("New joiner (onboarding)", "موظف جديد (التهيئة)", "نیا ملازم (آن بورڈنگ)"),
        summaries=t(
            "Everything a new colleague needs on day one, in one request.",
            "كل ما يحتاجه الزميل الجديد في يومه الأول، في طلب واحد.",
            "نئے ساتھی کو پہلے دن درکار ہر چیز، ایک ہی درخواست میں۔",
        ),
        questions=(
            FULL_NAME,
            START_DATE,
            JOB_TITLE,
            StarterQuestion(
                "laptop",
                t("Needs a laptop", "يحتاج إلى حاسوب محمول", "لیپ ٹاپ درکار ہے"),
                "yes_no",
                default=True,
            ),
            StarterQuestion(
                "applications",
                t("Applications they need", "التطبيقات التي يحتاجها", "درکار ایپلیکیشنز"),
                "long_text",
            ),
        ),
        tasks=(
            CREATE_ACCOUNT,
            StarterTask(t("Prepare the laptop", "تجهيز الحاسوب المحمول", "لیپ ٹاپ تیار کریں")),
            StarterTask(
                t(
                    "Grant access to the applications",
                    "منح الوصول إلى التطبيقات",
                    "ایپلیکیشنز تک رسائی دیں",
                )
            ),
            StarterTask(
                t("Welcome on the first day", "الاستقبال في اليوم الأول", "پہلے دن خوش آمدید")
            ),
        ),
        manager_approval=True,
        subject_template="New joiner: {full_name}",
    ),
    # --- 6. Leaving the organisation --------------------------------------------------------------
    StarterItem(
        key="leaver",
        category="leaving",
        icon="offboarding",
        names=t("Someone is leaving", "موظف سيغادر", "کوئی ملازم ادارہ چھوڑ رہا ہے"),
        summaries=t(
            "Tell us when someone leaves, so access and equipment are handled on time.",
            "أخبرنا عند مغادرة موظف حتى تُعالَج الصلاحيات والأجهزة في وقتها.",
            "کسی کے جانے کی اطلاع دیں تاکہ رسائی اور آلات کا بروقت انتظام ہو سکے۔",
        ),
        questions=(
            StarterQuestion(
                "leaver", t("Who is leaving", "من سيغادر", "کون جا رہا ہے"), "person", required=True
            ),
            StarterQuestion(
                "last_day", t("Last day", "آخر يوم عمل", "آخری دن"), "date", required=True
            ),
        ),
        tasks=(
            StarterTask(t("Collect the equipment", "استلام الأجهزة", "آلات واپس لیں")),
            StarterTask(
                t(
                    "Close the accounts on the last day",
                    "إغلاق الحسابات في آخر يوم",
                    "آخری دن اکاؤنٹس بند کریں",
                )
            ),
            StarterTask(
                t(
                    "Remove building access",
                    "إلغاء صلاحية دخول المبنى",
                    "عمارت میں داخلے کی اجازت ختم کریں",
                )
            ),
        ),
        manager_approval=True,
    ),
)

__all__ = [
    "CATEGORIES",
    "ITEMS",
    "StarterCategory",
    "StarterItem",
    "StarterQuestion",
    "StarterTask",
]
