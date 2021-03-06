import datetime
import tempfile

from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse
from django.db.models import Prefetch, Q
from django.test import TestCase
from nose.plugins.attrib import attr

import xlrd
from django_date_extensions.fields import ApproximateDate
from pombola.core.models import (Contact, ContactKind, Organisation,
                                 OrganisationKind, Person, Position,
                                 PositionTitle)
from pombola.south_africa.views.download import (
    get_active_persons_for_organisation, get_email_addresses_for_person,
    get_queryset_for_members_download, person_row_generator)

COLUMN_INDICES = {"name": 0, "mobile": 1, "email": 2, "parties": 3}


def get_row_from_name(sheet, columns, name):
    row_num = columns["names"].index(name)
    return sheet.row_values(row_num)


class DownloadMembersTest(TestCase):
    def setUp(self):
        party = OrganisationKind.objects.create(name="Party", slug="party",)
        self.parliament = OrganisationKind.objects.create(
            name="Parliament", slug="parliament",
        )
        self.na = Organisation.objects.create(
            name="National Assembly", kind=self.parliament, slug="national-assembly",
        )
        self.ncop = Organisation.objects.create(
            name="NCOP", kind=self.parliament, slug="ncop",
        )
        self.da = Organisation.objects.create(name="DA", kind=party, slug="da")
        self.anc = Organisation.objects.create(name="ANC", kind=party, slug="anc")
        self.member = PositionTitle.objects.create(name="Member", slug="member")

        self.email_kind = ContactKind.objects.create(slug="email", name="Email")
        self.cell_kind = ContactKind.objects.create(slug="cell", name="Cell")
        self.phone_kind = ContactKind.objects.create(slug="phone", name="Phone")


@attr(country="south_africa")
class GetQuerysetForMembersDownloadTest(DownloadMembersTest):
    def test_get_persons_for_national_assembly(self):
        self.mp = Person.objects.create(
            legal_name="Jimmy Stewart", slug="jimmy-stewart", email="jimmy@steward.com"
        )
        # Create MP position at the National Assembly
        Position.objects.create(
            person=self.mp,
            organisation=self.na,
            start_date=ApproximateDate(past=True),
            end_date=ApproximateDate(future=True),
            title=self.member,
        )

        result = get_queryset_for_members_download(self.na)
        self.assertEqual(1, len(result))
        self.assertIn(self.mp, result)

        # Check if the prefetched attributes are included
        self.assertTrue(hasattr(result[0], "cell_numbers"))
        self.assertTrue(hasattr(result[0], "email_addresses"))
        self.assertTrue(hasattr(result[0], "active_party_positions"))
        self.assertTrue(hasattr(result[0], "alternative_names"))


@attr(country="south_africa")
class GetActivePersonsForOrganisationTest(DownloadMembersTest):
    def test_get_inactive_persons_for_national_assembly(self):
        """
        No inactive people should be returned.
        """
        # Create an inactive MP
        self.inactive_mp = Person.objects.create(
            legal_name="Stefan Terblanche", slug="stefan-terblanche"
        )
        # Create an inactive position at the NA for the inactive MP
        Position.objects.create(
            person=self.inactive_mp,
            organisation=self.na,
            start_date=ApproximateDate(past=True),
            end_date=ApproximateDate(year=2009),
        )

        result = get_active_persons_for_organisation(self.na)
        self.assertEqual(0, len(result))
        self.assertNotIn(self.inactive_mp, result)

    def test_get_persons_for_national_assembly(self):
        self.mp = Person.objects.create(
            legal_name="Jimmy Stewart", slug="jimmy-stewart", email="jimmy@steward.com"
        )
        # Create MP position at the National Assembly
        Position.objects.create(
            person=self.mp,
            organisation=self.na,
            start_date=ApproximateDate(past=True),
            end_date=ApproximateDate(future=True),
            title=self.member,
        )
        # MP currently active position at the DA
        Position.objects.create(
            person=self.mp,
            organisation=self.da,
            start_date=ApproximateDate(past=True),
            end_date=ApproximateDate(future=True),
            title=self.member,
        )
        # MP contact number
        Contact.objects.create(
            content_type=ContentType.objects.get_for_model(self.mp),
            object_id=self.mp.id,
            kind=self.phone_kind,
            value="987654321",
            preferred=True,
        )
        # Create active NCOP member
        self.mpl = Person.objects.create(legal_name="John Steyn", slug="john-steyn")
        Position.objects.create(
            person=self.mp,
            organisation=self.ncop,
            start_date=ApproximateDate(past=True),
            end_date=ApproximateDate(future=True),
            title=self.member,
        )

        result = get_active_persons_for_organisation(self.na)
        self.assertEqual(1, len(result))
        self.assertIn(self.mp, result)
        self.assertNotIn(self.mpl, result)


@attr(country="south_africa")
class DownloadMPsTest(DownloadMembersTest):
    def setUp(self):
        super(DownloadMPsTest, self).setUp()

        self.mp = Person.objects.create(
            legal_name="Jimmy Stewart", slug="jimmy-stewart", email="jimmy@steward.com"
        )
        # Create MP position at the National Assembly
        Position.objects.create(
            person=self.mp,
            organisation=self.na,
            start_date=ApproximateDate(past=True),
            end_date=ApproximateDate(future=True),
            title=self.member,
        )
        # MP currently active position at the DA
        Position.objects.create(
            person=self.mp,
            organisation=self.da,
            start_date=ApproximateDate(past=True),
            end_date=ApproximateDate(future=True),
            title=self.member,
        )
        # MP contact number
        Contact.objects.create(
            content_type=ContentType.objects.get_for_model(self.mp),
            object_id=self.mp.id,
            kind=self.phone_kind,
            value="987654321",
            preferred=True,
        )
        Contact.objects.create(
            content_type=ContentType.objects.get_for_model(self.mp),
            object_id=self.mp.id,
            kind=self.phone_kind,
            value="5555",
            preferred=True,
        )

    def test_download_mps(self):
        response = self.client.get(
            reverse("sa-download-members-xlsx", args=("national-assembly",))
        )
        xlsx_file = self.stream_xlsx_file(response)
        book = xlrd.open_workbook(filename=xlsx_file.name)
        sheet = self.sheet = book.sheet_by_index(0)

        # Test that the headings are included and correct
        self.check_headings(sheet)

        # Test that the MP's details are in the sheet
        columns = self.get_columns(sheet)
        self.assertIn(self.mp.name, columns["names"])
        mp_row = get_row_from_name(sheet, columns, self.mp.name)
        self.assertEqual("jimmy@steward.com", mp_row[COLUMN_INDICES["email"]])
        self.assertEqual("5555, 987654321", mp_row[COLUMN_INDICES["mobile"]])
        self.assertEqual(self.da.name, mp_row[COLUMN_INDICES["parties"]])

    def stream_xlsx_file(self, response):
        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        for chunk in response.streaming_content:
            f.write(chunk)
        f.close()
        return f

    def check_headings(self, sheet):
        self.assertEqual(sheet.cell_value(0, COLUMN_INDICES["name"]), u"Name")
        self.assertEqual(sheet.cell_value(0, COLUMN_INDICES["mobile"]), u"Cell")
        self.assertEqual(sheet.cell_value(0, COLUMN_INDICES["email"]), u"Email")
        self.assertEqual(sheet.cell_value(0, COLUMN_INDICES["parties"]), u"Parties")

    def get_columns(self, sheet):
        return {
            "names": sheet.col_values(COLUMN_INDICES["name"]),
            "mobiles": sheet.col_values(COLUMN_INDICES["mobile"]),
            "emails": sheet.col_values(COLUMN_INDICES["email"]),
            "parties": sheet.col_values(COLUMN_INDICES["parties"]),
        }


@attr(country="south_africa")
class GetEmailAddressForPersonTest(TestCase):
    def get_persons_with_email_addresses(self):
        return Person.objects.distinct().prefetch_email_addresses()

    def test_person_with_email_in_email_field(self):
        Person.objects.all().delete()
        person = Person.objects.create(
            legal_name="Jimmy Stewart", slug="jimmy-stewart", email="jimmy@steward.com"
        )
        person_with_email_addresses = self.get_persons_with_email_addresses()[0]
        self.assertEqual(
            "jimmy@steward.com",
            get_email_addresses_for_person(person_with_email_addresses),
        )

    def test_person_with_no_email_addresses(self):
        Person.objects.all().delete()
        person = Person.objects.create(legal_name="Jimmy Stewart", slug="jimmy-stewart")
        person_with_email_addresses = self.get_persons_with_email_addresses()[0]
        self.assertEqual(
            "", get_email_addresses_for_person(person_with_email_addresses)
        )

    def test_person_with_multiple_email_addresses(self):
        Person.objects.all().delete()
        person = Person.objects.create(
            legal_name="Jimmy Stewart", slug="jimmy-stewart", email="jimmy@gmail.com"
        )
        email_kind = ContactKind.objects.create(slug="email", name="Email")
        Contact.objects.create(
            content_type=ContentType.objects.get_for_model(person),
            object_id=person.id,
            kind=email_kind,
            value="jimmy@steward.com",
            preferred=True,
        )
        Contact.objects.create(
            content_type=ContentType.objects.get_for_model(person),
            object_id=person.id,
            kind=email_kind,
            value="jimmy@hotmail.com",
            preferred=True,
        )
        person_with_email_addresses = self.get_persons_with_email_addresses()[0]
        email_addresses = ["jimmy@gmail.com", "jimmy@steward.com", "jimmy@hotmail.com"]
        for email_address in email_addresses:
            self.assertIn(
                email_address,
                get_email_addresses_for_person(person_with_email_addresses),
            )


@attr(country="south_africa")
class PersonRowGeneratorTest(TestCase):
    def generate_persons_from_empty_queryset_test(self):
        Person.objects.all().delete()
        result = list(person_row_generator(Person.objects.all()))
        self.assertEqual([], result)

    def get_persons_test(self):
        person = Person.objects.create(legal_name="Jimmy Stewart")
        result = list(
            person_row_generator(
                Person.objects.all()
                .prefetch_contact_numbers()
                .prefetch_email_addresses()
                .prefetch_active_party_positions()
            )
        )
        for person in result:
            print(person)
        self.assertEqual(1, len(result))
        self.assertEqual([person], result)
