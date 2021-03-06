import os

from django.db.models import Prefetch, Q
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView

import xlsx_streaming
from pombola.core.models import Contact, Organisation, Person, Position

MP_DOWNLOAD_TEMPLATE_SHEET = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "mp-download-template.xlsx"
)


def get_email_addresses_for_person(person):
    """
    Return all of the email addresses that we have for a person separated by spaces.
    """
    email_addresses = [person.email] if person.email else []
    email_addresses += [email_address.value for email_address in person.email_addresses]
    return " ".join(email_addresses)


def person_row_generator(persons):
    """
    Generate a tuple for each person containing their name, contact numbers, 
    email addresses and party memberships.
    """
    for person in persons:
        email = get_email_addresses_for_person(person)
        yield (
            person.name,
            ", ".join([cell_number.value for cell_number in person.cell_numbers]),
            get_email_addresses_for_person(person),
            ",".join(
                position.organisation.name for position in person.active_party_positions
            ),
        )


def get_active_persons_for_organisation(organisation):
    """
    Get all of the currently active positions at an organisation.
    """
    organisation_positions = organisation.position_set.currently_active().values("id")

    # Get the persons from the positions
    return (
        Person.objects.filter(hidden=False)
        .filter(position__id__in=organisation_positions)
        .distinct()
    )


def get_queryset_for_members_download(organisation):
    """
    Return the querset for the members download with the necessary data prefetched.
    """
    return (
        get_active_persons_for_organisation(organisation)
        .prefetch_contact_numbers()
        .prefetch_email_addresses()
        .prefetch_active_party_positions()
        .prefetch_related("alternative_names",)
    )


def download_members_xlsx(request, slug):
    """
    View function to stream an Excel sheet containing people's contact details
    for people who are active members of an organisation with the given slug.
    """
    organisation = get_object_or_404(Organisation, slug=slug)

    persons = get_queryset_for_members_download(organisation)

    with open(MP_DOWNLOAD_TEMPLATE_SHEET, "rb") as template:
        stream = xlsx_streaming.stream_queryset_as_xlsx(
            person_row_generator(persons), template
        )

    response = StreamingHttpResponse(
        stream,
        content_type="application/vnd.xlsxformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = "attachment; filename=%s-members.xlsx" % organisation.slug
    return response
