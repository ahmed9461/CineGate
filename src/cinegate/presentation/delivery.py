from __future__ import annotations

import re

_MAX_CAPTION_LENGTH = 1024
_VARIABLE_RE = re.compile(r"%[a-z_]+%")
_ALLOWED_VARIABLES = frozenset({"%movie%", "%year%", "%quality%", "%time%"})

DEFAULT_DELIVERY_CAPTION = (
    "%movie% %year% %quality%\n\n"
    "مهم جدا\n"
    "يرجى تحويل الفيديو الى رسائل المحفوظة او اي محادثة اخرى "
    "لانه سوف يتم حذفه بعد %time%"
)


class DeliveryTemplateError(ValueError):
    pass


def render_delivery_caption(
    template: str,
    *,
    movie: str,
    year: int | None,
    quality: str,
    delete_seconds: int,
) -> str:
    if delete_seconds <= 0:
        raise DeliveryTemplateError("delete_seconds must be positive")

    unknown = set(_VARIABLE_RE.findall(template)) - _ALLOWED_VARIABLES
    if unknown:
        raise DeliveryTemplateError(
            f"unsupported template variables: {', '.join(sorted(unknown))}"
        )

    rendered = template
    replacements = {
        "%movie%": movie,
        "%year%": str(year) if year is not None else "",
        "%quality%": quality,
        "%time%": f"{delete_seconds} ثانية",
    }
    for variable, value in replacements.items():
        rendered = rendered.replace(variable, value)

    rendered = "\n".join(line.rstrip() for line in rendered.splitlines()).strip()
    if not rendered:
        raise DeliveryTemplateError("delivery caption cannot be empty")
    if len(rendered) > _MAX_CAPTION_LENGTH:
        raise DeliveryTemplateError(
            f"delivery caption exceeds {_MAX_CAPTION_LENGTH} characters"
        )
    return rendered
