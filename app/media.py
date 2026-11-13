"""Controlled media properties shared by inventory, designs and printer capabilities."""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.i18n import Message

MediaFamily = Literal["tze", "fixed_label"]
if TYPE_CHECKING:
    from app.models import TapeProfile
    from app.printer.registry import PrinterCapabilities


class MediaProperties(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    media_family: MediaFamily = "tze"
    label_length_mm: float | None = Field(default=None, ge=10, le=300)

    @model_validator(mode="after")
    def valid_stock(self) -> "MediaProperties":
        if self.media_family == "fixed_label" and self.label_length_mm is None:
            raise ValueError(Message("domainMessages.fixedLabelMediaRequiresALabelLength"))
        if self.media_family == "tze" and self.label_length_mm is not None:
            raise ValueError(
                Message("domainMessages.continuousTZeMediaCannotHaveAFixedStockLength")
            )
        return self

    @property
    def media_kind(self) -> Literal["continuous", "fixed_label"]:
        return "continuous" if self.media_family == "tze" else "fixed_label"


def profile_media(profile: "TapeProfile") -> MediaProperties:
    return MediaProperties.model_validate(
        {"media_family": profile.media_family, "label_length_mm": profile.label_length_mm}
    )


def require_matching_media(required: MediaProperties, profile: "TapeProfile") -> None:
    if required != profile_media(profile):
        raise ValueError(
            Message("domainMessages.designAndCartridgeMediaDoNotMatchFamilyOrFixedLabelSize")
        )


def require_profile_supported(profile: "TapeProfile", capabilities: "PrinterCapabilities") -> None:
    require_supported_media(
        profile_media(profile),
        profile.width_mm,
        media_family=capabilities.media_family,
        media_kind=capabilities.media_kind.value,
        supported_widths_mm=capabilities.supported_widths_mm,
        fixed_label_sizes_mm=capabilities.fixed_label_sizes_mm,
    )


def require_supported_media(
    media: MediaProperties,
    width_mm: float,
    *,
    media_family: str,
    media_kind: str,
    supported_widths_mm: tuple[float, ...] | None,
    fixed_label_sizes_mm: tuple[tuple[float, float], ...],
) -> None:
    if media.media_family != media_family or media.media_kind != media_kind:
        raise ValueError(
            Message("domainMessages.theSelectedPrinterDoesNotSupportThisMediaFamilyOrFormat")
        )
    if supported_widths_mm is not None and width_mm not in supported_widths_mm:
        raise ValueError(
            Message("domainMessages.theSelectedPrinterDoesNotSupportThisPhysicalTapeWidth")
        )
    if (
        media.media_kind == "fixed_label"
        and (width_mm, media.label_length_mm) not in fixed_label_sizes_mm
    ):
        raise ValueError(
            Message("domainMessages.theSelectedPrinterDoesNotSupportThisFixedLabelSize")
        )
