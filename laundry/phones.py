import re

from django.core.exceptions import ValidationError


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]

    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 9:
        digits = "992" + digits

    if not digits.isdigit() or not 11 <= len(digits) <= 15:
        raise ValidationError("Введите телефон, например +992 90 123 45 67.")
    return digits
