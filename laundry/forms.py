import re

from django import forms
from django.core.exceptions import ValidationError

from .models import Resident
from .phones import normalize_phone


class LoginForm(forms.Form):
    phone = forms.CharField(label="Телефон", max_length=32)

    def clean_phone(self):
        try:
            return normalize_phone(self.cleaned_data["phone"])
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc


class RegisterForm(LoginForm):
    name = forms.CharField(label="Имя", max_length=80)
    apartment = forms.CharField(label="Номер квартиры", max_length=20)

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if len(name) < 2 or not re.search(r"[^\W\d_]", name, flags=re.UNICODE):
            raise forms.ValidationError("Введите имя.")
        return name

    def clean_apartment(self):
        apartment = self.cleaned_data["apartment"].strip()
        if not apartment:
            raise forms.ValidationError("Введите номер квартиры.")
        if not re.fullmatch(r"[0-9A-Za-zА-Яа-яЁё/\- ]{1,20}", apartment):
            raise forms.ValidationError("Введите номер квартиры, например 214.")
        return apartment

    def clean_phone(self):
        phone = super().clean_phone()
        if Resident.objects.filter(phone=phone).exists():
            raise forms.ValidationError("Этот номер уже зарегистрирован. Войдите.")
        return phone


class ProfileForm(forms.Form):
    email = forms.EmailField(label="Почта", required=False)

    def __init__(self, *args, resident, **kwargs):
        self.resident = resident
        initial = kwargs.setdefault("initial", {})
        initial.setdefault("email", resident.email)
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            return ""
        taken = Resident.objects.exclude(pk=self.resident.pk).filter(email__iexact=email)
        if taken.exists():
            raise forms.ValidationError("Эта почта уже указана у другого жильца.")
        return email
