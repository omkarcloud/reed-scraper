"""Marshmallow request schemas for every /reed/* route. Generic fields come
from the shared schema_fields.py; this module adds the Reed resolvers.
Every schema's load() output is the kwargs dict its endpoint takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair):

    job        a job id (57452596) OR a reed.co.uk job link
    jobs       up to 25 of those, comma-separated
    employer   an employer profile id (36210 / p36210) OR an employer listing link
    company    a company profile id (746 / FDM-Group-746) OR a company profile link
    course     a course id (230612) OR a reed.co.uk course link
    provider   a provider id (1778 / p1778), a provider course listing link OR
               a provider profile link
    query      free text OR (on /reed/jobs/search, /reed/jobs/facets,
               /reed/courses/search) a reed.co.uk listing link, whose own
               filters are then applied
"""
import re

from marshmallow import ValidationError, fields, validates_schema

from reed import refs
from reed.employers import SPECIALISMS
from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, NonNegativeNumber, PageField,
                           PageSizeField, Price, QueryField, RefField, StrippedString)

MAX_SEARCH_RESULTS = 10000
_ID_RE = re.compile(r"^\d{1,12}$")


# ---- fields ------------------------------------------------------------------------

class JobField(RefField):
    resolver = staticmethod(refs.resolve_job)


class EmployerField(RefField):
    resolver = staticmethod(refs.resolve_employer)


class CompanyField(RefField):
    resolver = staticmethod(refs.resolve_company)


class CourseField(RefField):
    resolver = staticmethod(refs.resolve_course)


class ProviderField(RefField):
    resolver = staticmethod(refs.resolve_provider)


class JobListField(fields.Field):
    """'57452596, https://www.reed.co.uk/jobs/x/57377207' -> ['57452596', '57377207'] (max 25)."""

    def __init__(self, max_items=25, **kwargs):
        kwargs.setdefault("required", True)
        super().__init__(**kwargs)
        self.max_items = max_items

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for raw in str(value).split(","):
            part = raw.strip()
            if not part:
                continue
            try:
                job_id = refs.resolve_job(part)
            except ValueError as e:
                raise ValidationError(str(e))
            if job_id not in out:
                out.append(job_id)
        if not out:
            raise ValidationError("Must not be empty.")
        if len(out) > self.max_items:
            raise ValidationError(f"At most {self.max_items} jobs.")
        return out


class IdListField(fields.Field):
    """'52, 68' -> ['52', '68'] (numeric ids, deduped)."""

    def __init__(self, max_items=38, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)
        self.max_items = max_items

    def _deserialize(self, value, attr, data, **kwargs):
        out = []
        for raw in str(value).split(","):
            part = raw.strip()
            if not part:
                continue
            if not _ID_RE.match(part):
                raise ValidationError(f"'{part}' is not a numeric id.")
            if part not in out:
                out.append(part)
        if len(out) > self.max_items:
            raise ValidationError(f"At most {self.max_items} ids.")
        return out or None


class DistanceField(fields.Integer):
    """Search radius in miles, 0-50 (the site's own range)."""

    def __init__(self, max_miles=50, **kwargs):
        kwargs.setdefault("load_default", None)
        super().__init__(strict=False, **kwargs)
        self.max_miles = max_miles

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        if value < 0 or value > self.max_miles:
            raise ValidationError(f"Must be between 0 and {self.max_miles} miles.")
        return value


class SpecialismField(StrippedString):
    """A recruiter directory specialism: its slug (it-telecoms) or name (IT & Telecoms)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        low = value.lower()
        if low in SPECIALISMS:
            return low
        by_name = {name.lower(): slug for slug, name in SPECIALISMS.items()}
        if low in by_name:
            return by_name[low]
        slug = re.sub(r"[^a-z0-9]+", "-", low.replace("&", "")).strip("-")
        if slug in SPECIALISMS:
            return slug
        raise ValidationError(f"Must be one of: {', '.join(SPECIALISMS)}.")


# ---- jobs -------------------------------------------------------------------------------

class _JobFilters(BaseSchema):
    location = StrippedString(required=False, load_default=None)
    distance_miles = DistanceField()
    min_salary = Price()
    max_salary = Price()
    salary_period = ChoiceField(["annual", "hourly"])
    contract_type = CommaListField(allowed=["permanent", "contract", "temporary"], upper=False, max_items=3)
    full_time = Flag()
    part_time = Flag()
    remote_working = ChoiceField(["remote", "hybrid", "on_site"])
    sector_ids = IdListField()
    posted_within = ChoiceField(["today", "last_3_days", "last_week", "last_2_weeks"])
    posted_by = CommaListField(allowed=["recruitment_agency", "direct_employer", "reed"], upper=False, max_items=3)
    graduate = Flag()
    easy_apply = Flag()
    early_bird = Flag()
    visa_sponsorship = Flag()
    salary_shown_only = Flag()
    exclude_training = Flag()
    exclude_survey_jobs = Flag()

    @validates_schema
    def _ranges(self, data, **kwargs):
        low, high = data.get("min_salary"), data.get("max_salary")
        if low is not None and high is not None and high and low > high:
            raise ValidationError("Must not be greater than max_salary.", "min_salary")
        if data.get("salary_period") and low is None and high is None:
            raise ValidationError("Send it with min_salary or max_salary.", "salary_period")
        if data.get("distance_miles") is not None and not data.get("location") and not refs.is_link(data.get("query") or ""):
            raise ValidationError("Needs a location.", "distance_miles")


class _Paged(BaseSchema):
    page = PageField(max_page=MAX_SEARCH_RESULTS, load_default=None)
    per_page = PageSizeField(default=25, max_size=100)

    @validates_schema
    def _depth(self, data, **kwargs):
        if (data.get("page") or 1) * (data.get("per_page") or 25) > MAX_SEARCH_RESULTS:
            raise ValidationError(f"The site serves the first {MAX_SEARCH_RESULTS} results of a search: "
                                  f"page x per_page must not exceed {MAX_SEARCH_RESULTS}. Narrow the search to reach more jobs.", "page")


class JobSearchSchema(_JobFilters, _Paged):
    query = StrippedString(required=False, load_default=None,
                           metadata={"description": "keywords, or a reed.co.uk job search / employer listing link"})

    @validates_schema
    def _query_length(self, data, **kwargs):
        query = data.get("query")
        if query and len(query) > 300 and not refs.is_link(query):
            raise ValidationError("Longer than 300 characters.", "query")


class JobFacetsSchema(_JobFilters):
    query = StrippedString(required=False, load_default=None)


class JobSchema(BaseSchema):
    job = JobField()


class JobsSchema(BaseSchema):
    jobs = JobListField()


# ---- employers ----------------------------------------------------------------------------

class EmployerSearchSchema(BaseSchema):
    query = StrippedString(required=False, load_default=None, metadata={"description": "employer name"})
    employer_type = ChoiceField(["recruitment_agency", "direct_employer"])
    sector = SpecialismField()
    location = StrippedString(required=False, load_default=None)
    distance_miles = DistanceField(max_miles=100)
    page = PageField(max_page=500)

    @validates_schema
    def _radius(self, data, **kwargs):
        if data.get("distance_miles") is not None and not data.get("location"):
            raise ValidationError("Needs a location.", "distance_miles")


class EmployerJobsSchema(_JobFilters, _Paged):
    employer = EmployerField()
    query = StrippedString(required=False, load_default=None, metadata={"description": "keywords within the employer's jobs"})


class CompanySchema(BaseSchema):
    company = CompanyField()


# ---- salary / reference -----------------------------------------------------------------

class SalarySchema(BaseSchema):
    job_title = QueryField(max_length=100)
    location = StrippedString(required=False, load_default=None)


class SuggestSchema(BaseSchema):
    query = QueryField(max_length=100)


class EmptySchema(BaseSchema):
    pass


# ---- courses --------------------------------------------------------------------------------

class CourseSearchSchema(BaseSchema):
    query = StrippedString(required=False, load_default=None,
                           metadata={"description": "keywords, or a reed.co.uk course listing link"})
    subject = StrippedString(required=False, load_default=None)
    location = StrippedString(required=False, load_default=None)
    distance_miles = DistanceField(max_miles=100)
    provider = ProviderField(required=False, load_default=None)
    study_method = CommaListField(allowed=["online", "classroom", "in_company", "on_demand"], upper=False, max_items=4)
    level = CommaListField(allowed=["beginner", "intermediate", "advanced"], upper=False, max_items=3)
    qualification = CommaListField(allowed=["cpd", "professional", "regulated", "higher_education"], upper=False, max_items=4)
    qualification_level = CommaListField(allowed=[str(n) for n in range(1, 9)], upper=False, max_items=8)
    min_price = Price()
    max_price = Price()
    duration = ChoiceField(["short", "long"])
    awarding_body = StrippedString(required=False, load_default=None)
    tutor_support = Flag()
    finance_available = Flag()
    funding_available = Flag()
    job_guarantee = Flag()
    on_offer = Flag()
    trending = Flag()
    buy_online = Flag()
    sort = ChoiceField(["relevance", "most_popular", "price_low_to_high", "price_high_to_low", "newest"])
    page = PageField(max_page=1000, load_default=None)
    per_page = PageSizeField(default=25, max_size=100)

    @validates_schema
    def _checks(self, data, **kwargs):
        low, high = data.get("min_price"), data.get("max_price")
        if low is not None and high is not None and low > high:
            raise ValidationError("Must not be greater than max_price.", "min_price")
        if data.get("provider") and not data["provider"].get("id"):
            raise ValidationError("Use a provider id or a /courses/{name}/p{id} link here (a profile link has no id).", "provider")
        query = data.get("query")
        if query and len(query) > 200 and not refs.is_link(query):
            raise ValidationError("Longer than 200 characters.", "query")


class CourseSchema(BaseSchema):
    course = CourseField()


class ReviewsSchema(BaseSchema):
    # Reviews belong to providers; `course` narrows to one of its courses.
    provider = ProviderField()
    course = CourseField(required=False, load_default=None)
    sort = ChoiceField(["newest", "highest_rating", "lowest_rating"], load_default="newest")
    page = PageField(max_page=1000)
    per_page = PageSizeField(default=25, max_size=100)


class ProvidersSchema(BaseSchema):
    query = StrippedString(required=False, load_default=None, metadata={"description": "provider name"})
    page = PageField(max_page=1000)
    per_page = PageSizeField(default=24, max_size=96)


class ProviderSchema(BaseSchema):
    provider = ProviderField()
