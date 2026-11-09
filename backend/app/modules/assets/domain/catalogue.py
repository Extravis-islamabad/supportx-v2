"""The asset catalogue's rules: pure Python, no I/O (WP-049a session 1; parity 07 §2, §4; D-141).

- **Product types** form a tree. A type's category (`it` / `non_it`, D-141: only IT assets
  count toward the licence's asset limit) and kind (asset, component, consumable) are set on a
  top-level type and inherited by everything below it (REQ-AST-003).
- **States** each have one fixed category; rules, reports, the licence count and loans use the
  category, never the name (REQ-AST-012).
- **Life cycles** list the allowed moves between states (REQ-AST-013). Entering a state that
  needs a reason, or taking a move that does, needs one.

Names are data, not labels: `{"en": ..., "ar": ..., "ur": ...}`, English required. The defaults
(Appendix A) are seeded with all three, and an admin can change every one of them (D-041).
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

NAME_MAX = 120
NAME_LANGUAGES = ("en", "ar", "ur")
API_NAME = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
STATE_CODE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")
TAG_PATTERN_MAX = 40
TREE_DEPTH_MAX = 6
TYPES_MAX = 500
STATES_MAX = 50
LIFE_CYCLES_MAX = 50
AMOUNT_MAX = Decimal("999999999999.99")  # NUMERIC(14, 2)


class AssetTypeCategory(StrEnum):
    """D-141: only `it` asset types count toward the licence's asset limit."""

    IT = "it"
    NON_IT = "non_it"


class AssetTypeKind(StrEnum):
    """What the type's records are (REQ-AST-003); only `asset` records are managed assets."""

    ASSET = "asset"
    COMPONENT = "component"
    CONSUMABLE = "consumable"


class AssetStateCategory(StrEnum):
    """The fixed meaning of a state (REQ-AST-012)."""

    IN_STOCK = "in_stock"
    IN_USE = "in_use"
    IN_REPAIR = "in_repair"
    RETIRED = "retired"
    DISPOSED = "disposed"


class AssetDepreciationMethod(StrEnum):
    """REQ-AST-037; the calculation itself arrives in WP-049b."""

    STRAIGHT_LINE = "straight_line"
    DECLINING_BALANCE = "declining_balance"
    DOUBLE_DECLINING_BALANCE = "double_declining_balance"
    SUM_OF_YEARS_DIGITS = "sum_of_years_digits"


class AssetAgeBasis(StrEnum):
    """The date an asset's age counts from (REQ-AST-011)."""

    ACQUISITION_DATE = "acquisition_date"
    CREATED_DATE = "created_date"


@dataclass(frozen=True)
class Problem:
    """One field problem; the service turns it into an RFC 9457 field error."""

    field: str
    code: str
    params: tuple[tuple[str, int | str], ...] = ()


def clean_names(field: str, names: object) -> tuple[dict[str, str], list[Problem]]:
    """Trimmed names in the known languages; English required, each at most NAME_MAX long."""
    if not isinstance(names, Mapping):
        return {}, [Problem(f"{field}.en", "required")]
    cleaned = {
        lang: " ".join(str(value).split())
        for lang, value in names.items()
        if lang in NAME_LANGUAGES and isinstance(value, str)
    }
    problems = [
        Problem(f"{field}.{lang}", "value_too_long", (("max", NAME_MAX),))
        for lang, value in cleaned.items()
        if len(value) > NAME_MAX
    ]
    if not cleaned.get("en"):
        problems.append(Problem(f"{field}.en", "required"))
    return {lang: value for lang, value in cleaned.items() if value}, problems


def tag_pattern_problems(field: str, pattern: str | None) -> list[Problem]:
    """A tag pattern holds the counter `{n}` once, e.g. `AST-{n}` (REQ-AST-008)."""
    if pattern is None:
        return []
    if len(pattern) > TAG_PATTERN_MAX:
        return [Problem(field, "value_too_long", (("max", TAG_PATTERN_MAX),))]
    if pattern.count("{n}") != 1 or not pattern.replace("{n}", "").strip(" -_/."):
        return [Problem(field, "asset_tag_pattern_invalid")]
    return []


def amount_problems(field: str, value: Decimal | None) -> list[Problem]:
    """Money amounts: at least zero, two decimals, within NUMERIC(14, 2)."""
    if value is None:
        return []
    if value < 0 or value > AMOUNT_MAX:
        return [Problem(field, "out_of_range", (("min", 0), ("max", str(AMOUNT_MAX))))]
    if value != value.quantize(Decimal("0.01")):
        return [Problem(field, "too_many_decimals", (("max", 2),))]
    return []


def would_cycle(type_id: str, new_parent_id: str | None, parents: Mapping[str, str | None]) -> bool:
    """True when making `new_parent_id` the parent of `type_id` puts the type under itself."""
    seen: set[str] = set()
    current = new_parent_id
    while current is not None and current not in seen:
        if current == type_id:
            return True
        seen.add(current)
        current = parents.get(current)
    return current is not None  # a loop that doesn't pass through type_id: refuse it too


def depth(type_id: str | None, parents: Mapping[str, str | None]) -> int:
    """How many types sit above and including `type_id` (a top-level type has depth 1)."""
    count = 0
    current = type_id
    while current is not None and count <= TREE_DEPTH_MAX + 1:
        count += 1
        current = parents.get(current)
    return count


def descendants(type_id: str, parents: Mapping[str, str | None]) -> set[str]:
    """Every type below `type_id`."""
    children: dict[str, list[str]] = {}
    for child, parent in parents.items():
        if parent is not None:
            children.setdefault(parent, []).append(child)
    found: set[str] = set()
    stack = list(children.get(type_id, ()))
    while stack:
        node = stack.pop()
        if node not in found:
            found.add(node)
            stack.extend(children.get(node, ()))
    return found


@dataclass(frozen=True)
class Move:
    """One allowed move of a life cycle."""

    from_state: str
    to_state: str
    reason_required: bool = False
    permission: str | None = None


def reason_needed(move: Move, *, to_state_reason_required: bool) -> bool:
    """A move needs a reason when the move says so or when its target state does."""
    return move.reason_required or to_state_reason_required


def duplicate_moves(moves: Iterable[Move]) -> list[int]:
    """Indexes of moves that repeat an earlier (from, to) pair or go nowhere."""
    seen: set[tuple[str, str]] = set()
    bad: list[int] = []
    for index, move in enumerate(moves):
        pair = (move.from_state, move.to_state)
        if move.from_state == move.to_state or pair in seen:
            bad.append(index)
        seen.add(pair)
    return bad


# --- Appendix A: what a new tenant gets (D-041: an admin can change all of it) ----------------


@dataclass(frozen=True)
class SeedState:
    """A default state."""

    code: str
    names: Mapping[str, str]
    category: AssetStateCategory
    reason_required: bool = False
    default_for_category: bool = False
    system: bool = False  # loans and disposal rely on it: it can be renamed, never deleted


@dataclass(frozen=True)
class SeedType:
    """A default product type; children inherit the category and kind."""

    api_name: str
    names: Mapping[str, str]
    icon: str
    category: AssetTypeCategory | None = None  # top-level types only
    kind: AssetTypeKind | None = None
    children: tuple["SeedType", ...] = ()


def _n(en: str, ar: str, ur: str) -> Mapping[str, str]:
    return {"en": en, "ar": ar, "ur": ur}


SEED_STATES: tuple[SeedState, ...] = (
    SeedState(
        "in_stock",
        _n("In stock", "في المخزون", "اسٹاک میں"),
        AssetStateCategory.IN_STOCK,
        default_for_category=True,
    ),
    SeedState(
        "in_use",
        _n("In use", "قيد الاستخدام", "زیرِ استعمال"),
        AssetStateCategory.IN_USE,
        default_for_category=True,
    ),
    # Set by loans (WP-049a session 5), so it stays.
    SeedState("on_loan", _n("On loan", "مُعار", "ادھار پر"), AssetStateCategory.IN_USE, system=True),
    SeedState(
        "in_repair",
        _n("In repair", "قيد الإصلاح", "مرمت میں"),
        AssetStateCategory.IN_REPAIR,
        reason_required=True,
        default_for_category=True,
    ),
    SeedState(
        "missing", _n("Missing", "مفقود", "گمشدہ"), AssetStateCategory.RETIRED, reason_required=True
    ),
    SeedState(
        "retired",
        _n("Retired", "متقاعد", "ریٹائرڈ"),
        AssetStateCategory.RETIRED,
        reason_required=True,
        default_for_category=True,
    ),
    # Entered with the disposal record (REQ-AST-017); disposed assets stop counting.
    SeedState(
        "disposed",
        _n("Disposed", "تم التخلص منه", "تلف شدہ"),
        AssetStateCategory.DISPOSED,
        reason_required=True,
        default_for_category=True,
        system=True,
    ),
)

# Retired → in stock needs this permission (Appendix A: "in stock (permission)").
REINSTATE = "assets.reinstate"

SEED_MOVES: tuple[Move, ...] = (
    *(Move("in_stock", to) for to in ("in_use", "on_loan", "in_repair", "missing", "retired")),
    *(Move("in_use", to) for to in ("in_stock", "on_loan", "in_repair", "missing", "retired")),
    *(Move("on_loan", to) for to in ("in_stock", "in_repair", "missing")),
    *(Move("in_repair", to) for to in ("in_stock", "in_use", "retired")),
    *(Move("missing", to) for to in ("in_stock", "in_use", "retired")),
    Move("retired", "in_stock", permission=REINSTATE),
    Move("retired", "disposed"),
)

SEED_LIFE_CYCLE_CODE = "standard"
SEED_LIFE_CYCLE_NAMES = _n(
    "Standard asset life cycle", "دورة حياة الأصل القياسية", "اثاثے کا معیاری لائف سائیکل"
)


def _t(api: str, en: str, ar: str, ur: str, icon: str, *children: SeedType) -> SeedType:
    return SeedType(api, _n(en, ar, ur), icon, children=children)


SEED_TYPES: tuple[SeedType, ...] = (
    SeedType(
        "it_hardware",
        _n("IT hardware", "أجهزة تقنية المعلومات", "آئی ٹی ہارڈویئر"),
        "cluster",
        AssetTypeCategory.IT,
        AssetTypeKind.ASSET,
        (
            _t(
                "computer",
                "Computer",
                "حاسوب",
                "کمپیوٹر",
                "desktop",
                _t("workstation", "Workstation", "محطة عمل", "ورک اسٹیشن", "desktop"),
                _t("laptop", "Laptop", "حاسوب محمول", "لیپ ٹاپ", "laptop"),
                _t("server", "Server", "خادم", "سرور", "database"),
                _t("virtual_host", "Virtual host", "مضيف افتراضي", "ورچوئل ہوسٹ", "cloud-server"),
                _t("virtual_machine", "Virtual machine", "جهاز افتراضي", "ورچوئل مشین", "cloud"),
            ),
            _t(
                "mobile_device",
                "Mobile device",
                "جهاز محمول",
                "موبائل ڈیوائس",
                "mobile",
                _t("phone", "Phone", "هاتف", "فون", "mobile"),
                _t("tablet", "Tablet", "جهاز لوحي", "ٹیبلیٹ", "tablet"),
            ),
            _t(
                "network_device",
                "Network device",
                "جهاز شبكة",
                "نیٹ ورک ڈیوائس",
                "apartment",
                _t("router", "Router", "موجّه", "راؤٹر", "apartment"),
                _t("switch", "Switch", "محوّل", "سوئچ", "apartment"),
                _t("firewall", "Firewall", "جدار حماية", "فائر وال", "safety"),
                _t(
                    "wireless_access_point",
                    "Wireless access point",
                    "نقطة وصول لاسلكية",
                    "وائرلیس ایکسیس پوائنٹ",
                    "wifi",
                ),
            ),
            _t("printer", "Printer", "طابعة", "پرنٹر", "printer"),
            _t("storage_device", "Storage device", "جهاز تخزين", "اسٹوریج ڈیوائس", "hdd"),
            _t("ip_phone", "IP phone", "هاتف IP", "آئی پی فون", "phone"),
        ),
    ),
    SeedType(
        "non_it_assets",
        _n("Non-IT assets", "أصول غير تقنية", "غیر آئی ٹی اثاثے"),
        "shop",
        AssetTypeCategory.NON_IT,
        AssetTypeKind.ASSET,
        (
            _t("furniture", "Furniture", "أثاث", "فرنیچر", "shop"),
            _t("projector", "Projector", "جهاز عرض", "پروجیکٹر", "video-camera"),
            _t("office_equipment", "Office equipment", "معدات مكتبية", "دفتری سامان", "tool"),
            _t("vehicle", "Vehicle", "مركبة", "گاڑی", "car"),
        ),
    ),
    SeedType(
        "components",
        _n("Components", "مكونات", "پرزے"),
        "build",
        AssetTypeCategory.IT,
        AssetTypeKind.COMPONENT,
        (
            _t("monitor", "Monitor", "شاشة", "مانیٹر", "desktop"),
            _t("keyboard", "Keyboard", "لوحة مفاتيح", "کی بورڈ", "edit"),
            _t("mouse", "Mouse", "فأرة", "ماؤس", "aim"),
            _t("docking_station", "Docking station", "محطة إرساء", "ڈاکنگ اسٹیشن", "api"),
            _t("memory_module", "Memory module", "وحدة ذاكرة", "میموری ماڈیول", "block"),
            _t("disk", "Disk", "قرص", "ڈسک", "hdd"),
        ),
    ),
    SeedType(
        "consumables",
        _n("Consumables", "مستهلكات", "قابلِ صرف اشیاء"),
        "inbox",
        AssetTypeCategory.NON_IT,
        AssetTypeKind.CONSUMABLE,
        (
            _t("toner_and_ink", "Toner and ink", "حبر وتونر", "ٹونر اور سیاہی", "format-painter"),
            _t("cables", "Cables", "كابلات", "کیبلز", "link"),
            _t("paper", "Paper", "ورق", "کاغذ", "file"),
            _t("batteries", "Batteries", "بطاريات", "بیٹریاں", "thunderbolt"),
        ),
    ),
)
