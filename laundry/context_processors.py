from .models import Resident


def resident(request):
    resident_id = request.session.get("resident_id")
    if not resident_id:
        return {"resident": None}
    return {"resident": Resident.objects.filter(pk=resident_id).first()}
