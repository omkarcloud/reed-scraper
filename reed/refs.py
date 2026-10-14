"""Reed reference parsing: ONE param per input that auto-detects its forms
(tripadvisor QueryOrIdField convention — never a sibling `url`/`id` pair).

  job       57452596 | https://www.reed.co.uk/jobs/software-engineer-london/57452596
  employer  36210 | p36210 | https://www.reed.co.uk/jobs/hays-specialist-recruitment-limited/p36210
            (the employer PROFILE id — the `p{id}` of a listing page; every job
            row carries it as employer.profile_id)
  company   746 | FDM-Group-746 | https://www.reed.co.uk/company-profile/FDM-Group-746
            (the COMPANY PROFILE id — a different id space from `employer`)
  course    230612 | https://www.reed.co.uk/courses/python-complete-course/230612
  provider  1778 | p1778 | https://www.reed.co.uk/courses/janets/p1778
            | https://www.reed.co.uk/courses/provider-profiles/janets (slug;
            resolved to an id by the endpoint with one profile-search call)
  query     free text | a reed.co.uk job search / sector / employer listing
            link, whose own filters are then applied (parse_search_link)
            | a reed.co.uk course listing link (parse_course_link)
"""
import re
from urllib.parse import parse_qsl, urlparse

SITE = "https://www.reed.co.uk"

_ID_RE = re.compile(r"^\d{1,12}$")
_P_ID_RE = re.compile(r"^p(\d{1,12})$", re.I)
_SLUG_ID_RE = re.compile(r"^(?:[A-Za-z0-9.&'()+_-]+-)?(\d{1,12})$")       # FDM-Group-746 | 746
_HOST_RE = re.compile(r"^(?:www\.)?reed\.co\.uk(?=/|$)", re.I)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$", re.I)

# site query key (lower-cased) -> our search kwarg
_LINK_FLAGS = {
    "perm": "permanent", "contract": "contract", "temp": "temporary",
    "fulltime": "full_time", "parttime": "part_time", "graduate": "graduate",
    "agency": "agency", "direct": "direct", "isreed": "posted_by_reed",
    "isearlybird": "early_bird", "iseasyapply": "easy_apply",
    "visasponsorship": "visa_sponsorship", "hidejobswithoutsalary": "salary_shown_only",
    "hidetrainingjobs": "exclude_training", "hidesurveyjobs": "exclude_survey_jobs",
    "perhour": "per_hour",
}
_POSTED_WITHIN = {"today": "today", "lastthreedays": "last_3_days", "lastweek": "last_week",
                  "lasttwoweeks": "last_2_weeks"}
_WORKING = {"remote": "remote", "hybrid": "hybrid", "onsite": "on_site", "on-site": "on_site"}


def is_link(value):
    value = str(value or "").strip()
    return value.startswith(("http://", "https://", "//")) or bool(_HOST_RE.match(value))


def _parse(value):
    """A reed.co.uk link -> (path segments, query pairs). Raises ValueError
    for another site."""
    url = value.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith("http"):
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not (host == "reed.co.uk" or host.endswith(".reed.co.uk")):
        raise ValueError("not a reed.co.uk link")
    segments = [s for s in parsed.path.split("/") if s]
    return segments, parse_qsl(parsed.query, keep_blank_values=False)


def _truthy(raw):
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


# ---- links out -----------------------------------------------------------------

def absolute(path):
    if not path or not isinstance(path, str):
        return None
    if path.startswith("http"):
        return path.split("?sid=")[0] if "?sid=" in path else path
    if not path.startswith("/"):
        path = "/" + path
    return SITE + path


def strip_tracking(link):
    """Drop the site's sid / source / filter tracking from a job or
    employer link: /jobs/python-developer/57377207?source=searchResults&sid=... ."""
    if not link:
        return None
    return link.split("?", 1)[0]


def job_link(job_id, slug=None):
    if not job_id:
        return None
    return f"{SITE}/jobs/{slug or 'job'}/{job_id}"


def employer_jobs_link(profile_id, slug=None):
    if not profile_id:
        return None
    return f"{SITE}/jobs/{slug or 'employer'}/p{profile_id}"


def company_profile_link(company_profile_url_or_id):
    if not company_profile_url_or_id:
        return None
    return f"{SITE}/company-profile/{company_profile_url_or_id}"


def course_link(course_id, slug=None):
    if not course_id:
        return None
    return f"{SITE}/courses/{slug or 'course'}/{course_id}"


def provider_courses_link(provider_id, slug=None):
    if not provider_id:
        return None
    return f"{SITE}/courses/{slug or 'provider'}/p{provider_id}"


def provider_profile_link(slug):
    return f"{SITE}/courses/provider-profiles/{slug}" if slug else None


def logo_link(filename, thumb=False):
    """'Logo_36210.png' -> the resources CDN link (None for a missing logo)."""
    if not filename or not isinstance(filename, str):
        return None
    if filename.startswith("http"):
        return filename
    folder = "profileimages/logos/thumbs" if thumb else "profileimages/logos"
    return f"https://resources.reed.co.uk/{folder}/{filename.lstrip('/')}"


# ---- resolvers -------------------------------------------------------------------

def _id_from_segments(segments, after=None):
    """The last numeric segment (optionally the one right after `after`)."""
    if after:
        for index, segment in enumerate(segments[:-1]):
            if segment.lower() == after and _ID_RE.match(segments[index + 1]):
                return segments[index + 1]
        return None
    for segment in reversed(segments):
        if _ID_RE.match(segment):
            return segment
    return None


def resolve_job(value):
    """Job id or a reed.co.uk job link -> the id string."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("job is required")
    if is_link(value):
        try:
            segments, _ = _parse(value)
        except ValueError:
            raise ValueError("job must be a reed.co.uk job link (https://www.reed.co.uk/jobs/software-engineer/57452596) or a job id")
        if len(segments) >= 3 and segments[0].lower() == "jobs" and _ID_RE.match(segments[-1]):
            return segments[-1]
        if len(segments) >= 4 and segments[0].lower() == "jobs" and segments[-1].lower() == "apply" and _ID_RE.match(segments[-2]):
            return segments[-2]
        raise ValueError("job link must look like https://www.reed.co.uk/jobs/{title}/{job_id}")
    if not _ID_RE.match(value):
        raise ValueError("job must be a numeric reed.co.uk job id or a job link")
    return value


def resolve_employer(value):
    """Employer profile id (36210 / p36210) or a listing link
    (https://www.reed.co.uk/jobs/{name}/p36210[...]) -> {"id": "36210", "link": parsed link or None}."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("employer is required")
    if is_link(value):
        try:
            segments, pairs = _parse(value)
        except ValueError:
            raise ValueError("employer must be a reed.co.uk employer listing link (https://www.reed.co.uk/jobs/{name}/p36210) or a profile id")
        for segment in segments:
            match = _P_ID_RE.match(segment)
            if match and segments[0].lower() == "jobs":
                return {"id": match.group(1), "link": parse_search_link(value)}
        raise ValueError("employer link must look like https://www.reed.co.uk/jobs/{name}/p36210")
    match = _P_ID_RE.match(value)
    if match:
        return {"id": match.group(1), "link": None}
    if not _ID_RE.match(value):
        raise ValueError("employer must be a reed.co.uk employer profile id (the p{id} of a listing page, "
                         "employer.profile_id on every job) or an employer listing link")
    return {"id": value, "link": None}


def resolve_company(value):
    """Company profile id (746 / FDM-Group-746) or a link
    (https://www.reed.co.uk/company-profile/FDM-Group-746) -> the id string."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("company is required")
    if is_link(value):
        try:
            segments, _ = _parse(value)
        except ValueError:
            raise ValueError("company must be a reed.co.uk company profile link (https://www.reed.co.uk/company-profile/FDM-Group-746) or a company profile id")
        if len(segments) >= 2 and segments[0].lower() == "company-profile":
            match = _SLUG_ID_RE.match(segments[1])
            if match:
                return match.group(1)
        raise ValueError("company link must look like https://www.reed.co.uk/company-profile/{Name}-{company_profile_id}")
    match = _SLUG_ID_RE.match(value)
    if not match:
        raise ValueError("company must be a reed.co.uk company profile id (employer.company_profile_id on a job) or a company profile link")
    return match.group(1)


def resolve_course(value):
    """Course id or a reed.co.uk course link -> the id string."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("course is required")
    if is_link(value):
        try:
            segments, _ = _parse(value)
        except ValueError:
            raise ValueError("course must be a reed.co.uk course link (https://www.reed.co.uk/courses/python-course/230612) or a course id")
        if len(segments) >= 3 and segments[0].lower() == "courses" and _ID_RE.match(segments[-1]):
            return segments[-1]
        raise ValueError("course link must look like https://www.reed.co.uk/courses/{title}/{course_id}")
    if not _ID_RE.match(value):
        raise ValueError("course must be a numeric reed.co.uk course id or a course link")
    return value


def resolve_provider(value):
    """Provider id (1778 / p1778), a provider course listing link
    (https://www.reed.co.uk/courses/janets/p1778) or a provider profile link
    (https://www.reed.co.uk/courses/provider-profiles/janets) ->
    {"id": "1778"|None, "slug": "janets"|None}."""
    value = str(value or "").strip()
    if not value:
        raise ValueError("provider is required")
    if is_link(value):
        try:
            segments, _ = _parse(value)
        except ValueError:
            raise ValueError("provider must be a reed.co.uk provider link (https://www.reed.co.uk/courses/janets/p1778 or "
                             "https://www.reed.co.uk/courses/provider-profiles/janets) or a provider id")
        if len(segments) >= 3 and segments[0].lower() == "courses" and segments[1].lower() == "provider-profiles":
            return {"id": None, "slug": segments[2].lower()}
        if len(segments) >= 3 and segments[0].lower() == "courses":
            match = _P_ID_RE.match(segments[2])
            if match:
                return {"id": match.group(1), "slug": None}
        raise ValueError("provider link must look like https://www.reed.co.uk/courses/{name}/p1778 or "
                         "https://www.reed.co.uk/courses/provider-profiles/{name}")
    match = _P_ID_RE.match(value)
    if match:
        return {"id": match.group(1), "slug": None}
    if _ID_RE.match(value):
        return {"id": value, "slug": None}
    raise ValueError("provider must be a numeric reed.co.uk provider id, a provider course listing link or a provider profile link")


# ---- search links ----------------------------------------------------------------------

def _slug_parts(slug):
    """'python-developer-jobs-in-london' -> ('python developer', 'london');
    'jobs-in-london' -> (None, 'london'); 'accountancy-jobs' -> ('accountancy', None);
    'contract-python-developer-jobs-in-london' keeps the contract word in the keywords
    (the site itself re-derives the flag from the query string)."""
    slug = slug.lower()
    keywords = location = None
    if "-jobs-in-" in slug:
        head, _, tail = slug.partition("-jobs-in-")
        keywords = head.replace("-", " ") or None
        location = tail.replace("-", " ") or None
    elif slug.startswith("jobs-in-"):
        location = slug[len("jobs-in-"):].replace("-", " ") or None
    elif slug.endswith("-jobs"):
        keywords = slug[:-len("-jobs")].replace("-", " ") or None
    elif slug == "jobs":
        pass
    else:
        keywords = slug.replace("-", " ") or None
    return keywords, location


def parse_search_link(value):
    """A reed.co.uk job search / sector / employer listing link -> the
    search kwargs it encodes (absent parts are None):
    {keywords, location, distance_miles, page, per_page, employer_id,
     employer_slug, min_salary, max_salary, per_hour, sector_ids,
     posted_within, remote_working, permanent, contract, temporary, full_time,
     part_time, graduate, agency, direct, posted_by_reed, early_bird,
     easy_apply, visa_sponsorship, salary_shown_only, exclude_training,
     exclude_survey_jobs}. Raises ValueError for another site or a non-jobs path."""
    segments, pairs = _parse(value)
    if not segments or segments[0].lower() != "jobs":
        raise ValueError("query must be search text or a reed.co.uk job search link (https://www.reed.co.uk/jobs/python-developer-jobs-in-london)")
    out = {"keywords": None, "location": None, "distance_miles": None, "page": None, "per_page": None,
           "employer_id": None, "employer_slug": None, "min_salary": None, "max_salary": None,
           "per_hour": None, "sector_ids": None, "posted_within": None, "remote_working": None}
    rest = segments[1:]
    # employer listing: /jobs/{name}/p{id}[/{location}]
    for index, segment in enumerate(rest):
        match = _P_ID_RE.match(segment)
        if match:
            out["employer_id"] = match.group(1)
            out["employer_slug"] = rest[index - 1] if index >= 1 else None
            if index + 1 < len(rest):
                out["location"] = rest[index + 1].replace("-", " ")
            rest = []
            break
    if rest:
        keywords, location = _slug_parts(rest[0])
        out["keywords"], out["location"] = keywords, location
    for key, raw in pairs:
        key = key.lower()
        raw = raw.strip()
        if not raw:
            continue
        if key == "keywords":
            out["keywords"] = " ".join(raw.split()) or None
        elif key in ("location", "locationname"):
            out["location"] = " ".join(raw.split()) or None
        elif key == "proximity" and raw.isdigit():
            out["distance_miles"] = int(raw)
        elif key == "pageno" and raw.isdigit() and int(raw) >= 1:
            out["page"] = int(raw)
        elif key == "take" and raw.isdigit() and int(raw) >= 1:
            out["per_page"] = min(int(raw), 100)
        elif key == "salaryfrom" and _number(raw) is not None:
            out["min_salary"] = _number(raw)
        elif key == "salaryto" and _number(raw) is not None:
            out["max_salary"] = _number(raw)
        elif key in ("parentsectorids", "sectorids", "parentsector"):
            ids = [p for p in re.split(r"[,\s]+", raw) if p.isdigit()]
            if ids:
                out["sector_ids"] = ids
        elif key == "datecreatedoffset" and raw.lower() in _POSTED_WITHIN:
            out["posted_within"] = _POSTED_WITHIN[raw.lower()]
        elif key in ("remoteworkingoption", "workingoption") and raw.lower() in _WORKING:
            out["remote_working"] = _WORKING[raw.lower()]
        elif key in _LINK_FLAGS and _truthy(raw):
            out[_LINK_FLAGS[key]] = True
    return out


def _number(raw):
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


_COURSE_PATH_FLAGS = {
    "online": ("study_method", "online"), "classroom": ("study_method", "classroom"),
    "on-demand": ("study_method", "on_demand"), "ondemand": ("study_method", "on_demand"),
    "beginner": ("level", "beginner"), "intermediate": ("level", "intermediate"), "advanced": ("level", "advanced"),
    "cpd": ("qualification", "cpd"), "professional": ("qualification", "professional"),
    "regulated": ("qualification", "regulated"), "university": ("qualification", "higher_education"),
    "tutor-support": ("tutor_support", True), "finance-options": ("finance_available", True),
    "funding-options": ("funding_available", True), "job-guarantee": ("job_guarantee", True),
    "free": ("max_price", 0), "discount": ("on_offer", True), "trending": ("trending", True),
}
_COURSE_QUERY_FLAGS = {
    "online": ("study_method", "online"), "classroom": ("study_method", "classroom"), "onsite": ("study_method", "in_company"),
    "ondemand": ("study_method", "on_demand"),
    "beginner": ("level", "beginner"), "intermediate": ("level", "intermediate"), "advanced": ("level", "advanced"),
    "cpd": ("qualification", "cpd"), "professional": ("qualification", "professional"),
    "regulated": ("qualification", "regulated"), "highereducation": ("qualification", "higher_education"),
    "tutorsupport": ("tutor_support", True), "financeoptions": ("finance_available", True),
    "fundingoptions": ("funding_available", True), "jobguarantee": ("job_guarantee", True),
    "discount": ("on_offer", True), "trending": ("trending", True), "buynow": ("buy_online", True),
}
COURSE_SORTS = {"": "relevance", "mostpopular": "most_popular", "priceasc": "price_low_to_high",
                "pricedesc": "price_high_to_low", "recentlyadded": "newest"}


def parse_course_link(value):
    """A reed.co.uk course listing link -> the course search kwargs it
    encodes: {keywords, subject, location, provider_id, study_method[],
    level[], qualification[], qualification_level[], tutor_support,
    finance_available, funding_available, job_guarantee, on_offer, trending,
    buy_online, min_price, max_price, duration, awarding_body, sort, page,
    per_page}. Raises ValueError for another site or a non-courses path."""
    segments, pairs = _parse(value)
    if not segments or segments[0].lower() != "courses":
        raise ValueError("query must be search text or a reed.co.uk course listing link (https://www.reed.co.uk/courses/python/online)")
    out = {"keywords": None, "subject": None, "location": None, "provider_id": None, "study_method": [],
           "level": [], "qualification": [], "qualification_level": [], "min_price": None, "max_price": None,
           "duration": None, "awarding_body": None, "sort": None, "page": None, "per_page": None}

    def put(key, val):
        if isinstance(out.get(key), list):
            if val not in out[key]:
                out[key].append(val)
        else:
            out[key] = val

    rest = [s.lower() for s in segments[1:]]
    if rest and rest[0] in ("all", "search"):
        rest = rest[1:]
    for index, segment in enumerate(rest):
        match = _P_ID_RE.match(segment)
        if match:
            out["provider_id"] = match.group(1)
            rest = rest[:index - 1] + rest[index + 1:] if index >= 1 else rest[index + 1:]
            break
    for index, segment in enumerate(rest):
        if segment in _COURSE_PATH_FLAGS:
            key, val = _COURSE_PATH_FLAGS[segment]
            put(key, val)
        elif re.fullmatch(r"level-[1-8]", segment):
            put("qualification_level", segment[-1])
        elif index == 0 and _SLUG_RE.match(segment):
            out["subject"] = segment.replace("-", " ")
        elif index == 1 and _SLUG_RE.match(segment) and out["location"] is None:
            out["location"] = segment.replace("-", " ")
    for key, raw in pairs:
        key = key.lower()
        raw = raw.strip()
        if not raw:
            continue
        if key == "keywords":
            out["keywords"] = " ".join(raw.split()) or None
        elif key == "location":
            out["location"] = " ".join(raw.split()) or None
        elif key == "subject":
            out["subject"] = " ".join(raw.split()) or None
        elif key in ("providerid", "providerids"):
            ids = [p for p in re.split(r"[,\s]+", raw) if p.isdigit()]
            if ids:
                out["provider_id"] = ids[0]
        elif key == "pricefrom" and _number(raw) is not None:
            out["min_price"] = _number(raw)
        elif key == "priceto" and _number(raw) is not None:
            out["max_price"] = _number(raw)
        elif key == "free" and _truthy(raw):
            out["max_price"] = 0
        elif key == "duration" and raw.lower() in ("short", "long"):
            out["duration"] = raw.lower()
        elif key == "awardingbody":
            out["awarding_body"] = raw
        elif key == "sortby" and raw.lower() in COURSE_SORTS:
            out["sort"] = COURSE_SORTS[raw.lower()]
        elif key == "pageno" and raw.isdigit() and int(raw) >= 1:
            out["page"] = int(raw)
        elif key == "pagesize" and raw.isdigit() and int(raw) >= 1:
            out["per_page"] = min(int(raw), 100)
        elif re.fullmatch(r"level[1-8]", key) and _truthy(raw):
            put("qualification_level", key[-1])
        elif key in _COURSE_QUERY_FLAGS and _truthy(raw):
            k, v = _COURSE_QUERY_FLAGS[key]
            put(k, v)
    return out
