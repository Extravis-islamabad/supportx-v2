"""Tenant branding (WP-017, REQ-ADM-055, REQ-PRT-016, REQ-SEC-003; D-027, D-090).

One row per tenant; no row means the SupportX default. Saving:

1. checks colours against WCAG AA on the server (refused with the failing checks and the nearest
   passing colour as params, so the screen can offer it in one click) and the translated texts;
2. reads the uploaded originals through the files service (scanned, owner `branding`) and makes
   every variant (`infra/brand_images.py`) when they changed;
3. replaces the variants, bumps the version, and writes `organization.branding.changed` to the
   outbox in the same transaction: open consoles and portals reload the brand (§8).

Who may save is the route's business (`branding.manage`); auditing is the route's `audited`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.errors import Conflict, FieldError, ParamValue, ValidationFailed
from app.modules.organization.domain.branding import (
    DEFAULT_COLOURS,
    Check,
    Colours,
    FieldProblem,
    TextField,
    clean_texts,
    nearest_passing_gradient,
    nearest_passing_primary,
    normalise_hex,
    text_problems,
)
from app.modules.organization.events import BrandingChanged
from app.modules.organization.infra import brand_images
from app.modules.organization.infra.models import BrandingAsset, TenantBranding
from app.shared.events import record_event
from app.shared.files.service import access
from app.shared.history import stale_version

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.shared.files.ports import Actor
    from app.shared.files.service.core import FileServices

ASSET_NAMES = (
    "logo.png",
    "logo-dark.png",
    "logo-high-contrast.png",
    "icon.png",
    "icon-high-contrast.png",
    "favicon.ico",
    "apple-touch-icon.png",
    "icon-192.png",
    "icon-512.png",
)


@dataclass(frozen=True)
class BrandingView:
    """What a tenant's surfaces show: chosen values, or None/empty for the default."""

    tenant_id: uuid.UUID
    primary_colour: str | None
    gradient: tuple[str, str] | None
    product_name: dict[str, str]
    portal_name: dict[str, str]
    welcome_text: dict[str, str]
    logo_file_id: uuid.UUID | None
    logo_dark_file_id: uuid.UUID | None
    icon_file_id: uuid.UUID | None
    assets_version: str | None
    assets: frozenset[str]
    version: int

    @property
    def colours(self) -> Colours:
        """Chosen colours, defaults where nothing was chosen."""
        primary = self.primary_colour or DEFAULT_COLOURS.primary
        gradient = self.gradient or (
            DEFAULT_COLOURS.gradient if self.primary_colour is None else (primary, primary)
        )
        return Colours(primary, gradient)

    @property
    def customised(self) -> bool:
        """Anything differs from the SupportX default."""
        return self.version > 0 and bool(
            self.primary_colour
            or self.gradient
            or self.product_name
            or self.portal_name
            or self.welcome_text
            or self.assets
        )


@dataclass(frozen=True)
class BrandingChanges:
    """A full branding (PUT): every field; None or empty restores that field's default."""

    primary_colour: str | None = None
    gradient: tuple[str, str] | None = None
    product_name: Mapping[str, str] = field(default_factory=dict)
    portal_name: Mapping[str, str] = field(default_factory=dict)
    welcome_text: Mapping[str, str] = field(default_factory=dict)
    logo_file_id: uuid.UUID | None = None
    logo_dark_file_id: uuid.UUID | None = None
    icon_file_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ColourReport:
    """Contrast checks for a candidate, and what to use instead when they fail."""

    checks: list[Check]
    suggested_primary: str | None
    suggested_gradient: tuple[str, str] | None

    @property
    def passes(self) -> bool:
        """Every check passes."""
        return all(check.passed for check in self.checks)


def _field_error(problem: FieldProblem) -> FieldError:
    params: dict[str, ParamValue] = {
        key: value for key, value in problem.params.items() if isinstance(value, str | int)
    }
    return FieldError(
        field=problem.field,
        code=problem.code,
        message_key=f"errors.field.{problem.code}",
        params=params,
    )


def colour_report(primary: str | None, gradient: tuple[str, str] | None) -> ColourReport:
    """Checks for the colours a branding would show (the live preview asks this as you type)."""
    chosen = Colours(
        primary or DEFAULT_COLOURS.primary,
        gradient or ((primary, primary) if primary else DEFAULT_COLOURS.gradient),
    )
    checks = chosen.checks()
    primary_fails = not all(check.passed for check in chosen.primary_checks())
    gradient_fails = not chosen.gradient_check().passed
    return ColourReport(
        checks,
        nearest_passing_primary(chosen.primary) if primary_fails else None,
        nearest_passing_gradient(chosen.gradient) if gradient_fails and gradient else None,
    )


def normalise_or_none(value: str | None) -> str | None:
    """A colour as #rrggbb (None stays None); ValidationFailed when it is not a colour."""
    if value is None:
        return None
    found = normalise_hex(value)
    if found is None:
        raise ValidationFailed(
            errors=[_field_error(FieldProblem("primary_colour", "invalid_colour", {}))]
        )
    return found


def normalise_pair_or_none(value: tuple[str, str] | None) -> tuple[str, str] | None:
    """Both gradient ends as #rrggbb (None stays None); ValidationFailed otherwise."""
    if value is None:
        return None
    start, end = normalise_hex(value[0]), normalise_hex(value[1])
    if start is None or end is None:
        raise ValidationFailed(
            errors=[_field_error(FieldProblem("gradient", "invalid_colour", {}))]
        )
    return start, end


def _colours(changes: BrandingChanges) -> tuple[str | None, tuple[str, str] | None]:
    """Normalised colours, or ValidationFailed for a malformed or unreadable one."""
    errors: list[FieldError] = []
    primary = None
    if changes.primary_colour is not None:
        primary = normalise_hex(changes.primary_colour)
        if primary is None:
            errors.append(_field_error(FieldProblem("primary_colour", "invalid_colour", {})))
    gradient = None
    if changes.gradient is not None:
        ends = (normalise_hex(changes.gradient[0]), normalise_hex(changes.gradient[1]))
        if ends[0] is None or ends[1] is None:
            errors.append(_field_error(FieldProblem("gradient", "invalid_colour", {})))
        else:
            gradient = (ends[0], ends[1])
    if errors:
        raise ValidationFailed(errors=errors)
    report = colour_report(primary, gradient)
    if not report.passes:
        failed = [check for check in report.checks if not check.passed]
        params: dict[str, str | int] = {"checks": ",".join(check.code.value for check in failed)}
        if report.suggested_primary:
            params["suggested_primary"] = report.suggested_primary
        if report.suggested_gradient:
            params["suggested_gradient"] = ",".join(report.suggested_gradient)
        raise ValidationFailed(code="brand_colour_contrast", params=params)
    return primary, gradient


def _texts(changes: BrandingChanges) -> dict[TextField, dict[str, str]]:
    values = {
        TextField.PRODUCT_NAME: changes.product_name,
        TextField.PORTAL_NAME: changes.portal_name,
        TextField.WELCOME_TEXT: changes.welcome_text,
    }
    problems = [p for name, value in values.items() for p in text_problems(name, value)]
    if problems:
        raise ValidationFailed(errors=[_field_error(problem) for problem in problems])
    return {name: clean_texts(value) for name, value in values.items()}


def _images(changes: BrandingChanges) -> None:
    if changes.logo_file_id is None and (changes.logo_dark_file_id or changes.icon_file_id):
        raise ValidationFailed(
            errors=[_field_error(FieldProblem("logo_file_id", "logo_required", {}))]
        )


async def _row(session: AsyncSession) -> TenantBranding | None:
    return await session.scalar(select(TenantBranding))


async def _asset_names(session: AsyncSession) -> frozenset[str]:
    return frozenset((await session.scalars(select(BrandingAsset.name))).all())


def _view(tenant_id: uuid.UUID, row: TenantBranding | None, assets: frozenset[str]) -> BrandingView:
    if row is None:
        return BrandingView(
            tenant_id, None, None, {}, {}, {}, None, None, None, None, frozenset(), 0
        )
    gradient = (
        (row.gradient_start, row.gradient_end)
        if row.gradient_start is not None and row.gradient_end is not None
        else None
    )
    return BrandingView(
        tenant_id=row.tenant_id,
        primary_colour=row.primary_colour,
        gradient=gradient,
        product_name=dict(row.product_name),
        portal_name=dict(row.portal_name),
        welcome_text=dict(row.welcome_text),
        logo_file_id=row.logo_file_id,
        logo_dark_file_id=row.logo_dark_file_id,
        icon_file_id=row.icon_file_id,
        assets_version=row.assets_version,
        assets=assets,
        version=row.version,
    )


async def get_branding(session: AsyncSession, tenant_id: uuid.UUID) -> BrandingView:
    """The tenant's branding (version 0 and no values when it never saved one)."""
    return _view(tenant_id, await _row(session), await _asset_names(session))


async def asset(session: AsyncSession, name: str) -> BrandingAsset | None:
    """One generated variant of the session tenant's brand."""
    return await session.scalar(select(BrandingAsset).where(BrandingAsset.name == name))


async def _render(
    session: AsyncSession,
    services: FileServices,
    actor: Actor,
    changes: BrandingChanges,
) -> list[brand_images.Variant]:
    async def read(file_id: uuid.UUID | None, field_name: str) -> bytes | None:
        if file_id is None:
            return None
        data = await access.read_image(
            session, services, actor, file_id, max_bytes=brand_images.MAX_INPUT_BYTES
        )
        try:
            brand_images.check_image(data)
        except brand_images.BrandImageError as exc:
            raise ValidationFailed(
                errors=[_field_error(FieldProblem(field_name, exc.code, {}))]
            ) from exc
        return data

    logo = await read(changes.logo_file_id, "logo_file_id")
    if logo is None:
        return []
    dark = await read(changes.logo_dark_file_id, "logo_dark_file_id")
    icon = await read(changes.icon_file_id, "icon_file_id")
    try:
        return await brand_images.render(logo, dark, icon)
    except brand_images.BrandImageError as exc:
        raise ValidationFailed(
            errors=[_field_error(FieldProblem("logo_file_id", exc.code, {}))]
        ) from exc


def _assets_version(variants: list[brand_images.Variant]) -> str:
    digest = hashlib.sha256()
    for variant in variants:
        digest.update(variant.name.encode())
        digest.update(hashlib.sha256(variant.content).digest())
    return digest.hexdigest()[:16]


def _changed_fields(row: TenantBranding | None, values: dict[str, object]) -> list[str]:
    if row is None:
        return sorted(key for key, value in values.items() if value not in (None, {}))
    return sorted(key for key, value in values.items() if getattr(row, key) != value)


async def save_branding(  # noqa: PLR0913 - who, with which files, what, and the version read
    session: AsyncSession,
    *,
    services: FileServices,
    actor: Actor,
    tenant_id: uuid.UUID,
    changes: BrandingChanges,
    expected_version: int,
) -> tuple[BrandingView, list[str]]:
    """Save the whole branding (If-Match: 0 creates it). Returns the view and changed fields."""
    primary, gradient = _colours(changes)
    texts = _texts(changes)
    _images(changes)
    row = await _row(session)
    current = row.version if row is not None else 0
    if current != expected_version:
        if row is None:  # nothing saved yet: nobody to name
            raise Conflict(
                code="version_conflict",
                params={"expected_version": expected_version, "current_version": current},
            )
        raise await stale_version(session, row, expected_version=expected_version)

    images = (changes.logo_file_id, changes.logo_dark_file_id, changes.icon_file_id)
    same_images = row is not None and images == (
        row.logo_file_id,
        row.logo_dark_file_id,
        row.icon_file_id,
    )
    assets_version = row.assets_version if row is not None else None
    if not same_images:
        variants = await _render(session, services, actor, changes)
        await session.execute(delete(BrandingAsset))
        session.add_all(
            BrandingAsset(
                tenant_id=tenant_id, name=v.name, content_type=v.content_type, content=v.content
            )
            for v in variants
        )
        assets_version = _assets_version(variants) if variants else None

    values: dict[str, object] = {
        "primary_colour": primary,
        "gradient_start": gradient[0] if gradient else None,
        "gradient_end": gradient[1] if gradient else None,
        "product_name": texts[TextField.PRODUCT_NAME],
        "portal_name": texts[TextField.PORTAL_NAME],
        "welcome_text": texts[TextField.WELCOME_TEXT],
        "logo_file_id": changes.logo_file_id,
        "logo_dark_file_id": changes.logo_dark_file_id,
        "icon_file_id": changes.icon_file_id,
        "assets_version": assets_version,
    }
    changed = _changed_fields(row, values)
    if row is None:
        row = TenantBranding(tenant_id=tenant_id, **values)
        session.add(row)
        try:
            await session.flush()
        except IntegrityError as exc:  # someone else created it first
            raise Conflict(code="version_conflict", params={"current_version": 1}) from exc
    else:
        for key, value in values.items():
            setattr(row, key, value)
        row.version += 1
        await session.flush()
    await record_event(
        session,
        BrandingChanged(version=row.version, changed_fields=changed),
        aggregate_id=row.id,
        aggregate_version=row.version,
    )
    return _view(tenant_id, row, await _asset_names(session)), changed
