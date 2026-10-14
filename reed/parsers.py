"""Reed normalizers: the jobs app's __NEXT_DATA__ objects, the recruiter
directory / salary / Reed Courses HTML and the courses JSON routes -> one
clean snake_case shape per entity.

Output conventions (shared with the other scrapers here): `link` for
canonical page URLs (absolute, tracking `sid=` dropped), `logo` / `image`
for picture links, `*_count` for counters, `is_*` / `has_*` for booleans,
ISO-8601 UTC ("2026-10-13T09:23:08Z") for timestamps (Reed's are Europe/
London wall-clock without a zone; they are converted), prices as a numeric
amount + a separate `currency` (always GBP), null for missing.

Entity vocabulary:
  job row      {id, title, link, description, contract_type, is_full_time,
                is_part_time, remote_working, salary{}, location{},
                employer{}, taxonomy{}, flags{}, application_count,
                external_application_link, posted_at, updated_at, expires_at}
  job details  the row + description_html / description_text, salary in full,
                location down to postcode, sector, skills, screening
                questions, application{}, branding{}, created_at
  employer     {id (ouId), name, profile_id, type, link (jobs listing), logo}
  course card  {id, title, link, subtitle, provider{}, image, price{},
                study_method, duration, students_count, cpd_points,
                has_certificate, has_tutor_support, badges[], rating,
                qualification_type, has_job_guarantee, excerpt, is_sponsored}

Deliberately dropped as noise:
  * viewer state on job rows: hasApplied, isWithdrawn, isInSavedJobsList,
    isHidden, toggleDescription, candidateState, shortlistedJobs, hiddenJobs
  * tracking: the `sid` / `source` / `filter` query of every link, gaTags,
    querySpeed, featureFlagsData, paymentModel ("Tenancy"), jobRecruiterTier,
    ouTierId, displayStyle, showLogoOnSearch, isPriorityBoost, refreshDate /
    nextRefreshDate, externalJobStatusId, hasUbioAccountCreation, isUbioFlow,
    coverLetterPreferenceId (its name is kept), jobApplicationEligibilityRequirement
    (kept as application.eligibility_requirement), localityId / orgId / townId
    / subSectorId zeros, displayLocationServiceId
  * numeric enum ids once mapped: jobType, salaryType, salaryDescription,
    salaryCurrencyId (1 = GBP), ouType, jobContractType.id, style.id
  * duplicated employer fields: ouLogoImage / ouBannerImage (the profile
    images are kept), profileLogoImage when it equals the logo
  * on courses: GA dataLayer_* duplicates once mapped, Square / Apple Pay /
    Google Pay checkout ids, __RequestVerificationToken, basket quantity,
    share / compare / save widgets, consent and ad scripts
  * on company profiles: headerId / displayOrder of article sections,
    benefitMapId, externalLinkId, companyProfileMediaImageId, lastViewedJob
"""
import html as html_lib
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from reed import refs

LONDON = ZoneInfo("Europe/London")
CURRENCY = "GBP"

CONTRACT_TYPES = {1: "permanent", 2: "contract", 3: "temporary", 4: "temporary"}
SALARY_PERIODS = {1: "hourly", 2: "daily", 3: "weekly", 4: "monthly", 5: "annual"}
SALARY_PERIOD_NAMES = {"per hour": "hourly", "per day": "daily", "per week": "weekly",
                       "per month": "monthly", "per annum": "annual", "per year": "annual"}
# salaryDescription: how a hidden salary is described on the site
SALARY_DESCRIPTIONS = {0: None, 16: "negotiable", 32: "commission", 64: "competitive"}
EMPLOYER_TYPES = {1: "recruitment_agency", 2: "direct_employer", 3: "reed"}
WORKING_OPTIONS = {"remote": "remote", "hybrid": "hybrid", "onsite": "on_site", "on-site": "on_site",
                   "on site": "on_site", "notspecified": None, "": None}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


# ---- value helpers ------------------------------------------------------------
# (kept local so the package stands alone, like the other site packages)

def to_int(value):
    try:
        return int(value) if value not in (None, "") and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        try:
            return int(float(str(value).replace(",", "")))
        except (TypeError, ValueError):
            return None


def to_float(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def number(value):
    """A float that is whole -> int (salaries, prices)."""
    out = to_float(value)
    if out is None:
        return None
    return int(out) if out.is_integer() else out


def text(value):
    if not isinstance(value, str):
        return None
    value = _WS_RE.sub(" ", html_lib.unescape(value)).strip()
    return value or None


def bool_or_none(value):
    return value if isinstance(value, bool) else None


def strip_html(value):
    """HTML -> readable plain text (block tags become newlines)."""
    if not isinstance(value, str) or not value.strip():
        return None
    out = re.sub(r"(?i)<\s*br\s*/?>", "\n", value)
    out = re.sub(r"(?i)</\s*(p|div|li|h[1-6]|tr|ul|ol|section|article|header)\s*>", "\n", out)
    out = re.sub(r"(?i)<\s*(p|div|h[1-6]|tr|ul|ol|section|article|header)(\s[^>]*)?>", "\n", out)
    out = re.sub(r"(?i)<\s*li[^>]*>", "\n- ", out)
    out = _TAG_RE.sub("", out)
    out = html_lib.unescape(out)
    lines = [_WS_RE.sub(" ", line).strip() for line in out.splitlines()]
    out = "\n".join(line for line in lines if line)
    return out or None


def iso_datetime(value):
    """Reed's '2026-10-13T09:23:08.09' (Europe/London wall clock, no zone)
    -> '2026-10-13T08:23:08Z'. Zone-aware inputs are honoured."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LONDON)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_date(value):
    stamp = iso_datetime(value)
    return stamp[:10] if stamp else None


def first_number(value):
    """'£85,425' / '334 jobs' -> 85425 / 334 (None when there is none)."""
    if not isinstance(value, str):
        return None
    match = _NUMBER_RE.search(value)
    return number(match.group(0)) if match else None


def working_option(value):
    if not isinstance(value, str):
        return None
    return WORKING_OPTIONS.get(value.strip().lower(), value.strip().lower().replace(" ", "_") or None)


def pagination(page, per_page, total):
    page = to_int(page) or 1
    per_page = to_int(per_page) or 25
    total = to_int(total) or 0
    return {"page": page, "items_per_page": per_page,
            "total_pages": max((total + per_page - 1) // per_page, 1 if total else 0), "total_count": total}


# ---- jobs ------------------------------------------------------------------------

def _salary_from_codes(from_, to, type_id, description_id, display=None, from_annual=None, to_annual=None):
    description = SALARY_DESCRIPTIONS.get(description_id, "hidden" if description_id else None)
    min_ = number(from_)
    max_ = number(to)
    is_hidden = bool(description) or (not min_ and not max_)
    out = {
        "display": text(display),
        "min": None if is_hidden and description else min_,
        "max": None if is_hidden and description else max_,
        "currency": CURRENCY,
        "period": SALARY_PERIODS.get(to_int(type_id)),
        "is_hidden": is_hidden,
        "hidden_as": description,
    }
    if from_annual is not None or to_annual is not None:
        out["min_annual"] = number(from_annual)
        out["max_annual"] = number(to_annual)
    if out["display"] is None and not is_hidden:
        out["display"] = _display_salary(out["min"], out["max"], out["period"])
    return out


def _display_salary(min_, max_, period):
    if min_ is None and max_ is None:
        return None
    unit = {"hourly": "per hour", "daily": "per day", "weekly": "per week", "monthly": "per month",
            "annual": "per annum"}.get(period, "")
    fmt = lambda v: f"£{v:,.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else f"£{v:,}"
    if min_ is not None and max_ is not None and min_ != max_:
        return f"{fmt(min_)} - {fmt(max_)} {unit}".strip()
    return f"{fmt(min_ if min_ is not None else max_)} {unit}".strip()


def _employer_from_row(d, extra=None):
    extra = extra or {}
    profile_id = to_int(d.get("profileId"))
    slug = text(extra.get("profileUrl"))
    link = refs.absolute(refs.strip_tracking(extra.get("ouUrl"))) if extra.get("ouUrl") else refs.employer_jobs_link(profile_id, slug)
    logo = extra.get("logoImage")
    return {
        "id": to_int(d.get("ouId")),
        "name": text(d.get("ouName")),
        "profile_id": profile_id,
        "type": EMPLOYER_TYPES.get(to_int(d.get("ouType"))),
        "link": link,
        "logo": refs.logo_link(logo, thumb=True) if logo else (refs.logo_link(f"Logo_{profile_id}.png", thumb=True) if profile_id else None),
    }


def job_row(row, display_salary=None):
    """A search / employer-listing row ({jobDetail, profileName, url, ...}), a
    company profile's recentJobs row, or a bare jobDetail -> job row."""
    if not isinstance(row, dict):
        return None
    d = row.get("jobDetail") if isinstance(row.get("jobDetail"), dict) else row
    job_id = to_int(d.get("jobId") or d.get("id"))
    if not job_id:
        return None
    title = text(d.get("jobTitle") or d.get("title"))
    link = refs.absolute(refs.strip_tracking(row.get("url"))) if row.get("url") else refs.job_link(job_id, _slugify(title))
    remote = d.get("workingOption") if "workingOption" in d else d.get("remoteWorkingOption")
    if remote is None and d.get("isHybridJob"):
        remote = "hybrid"
    external = text(d.get("externalUrl"))
    out = {
        "id": job_id,
        "title": title,
        "link": link,
        "description": text(d.get("jobDescriptionSnippet") or d.get("jobDescription")),
        "contract_type": CONTRACT_TYPES.get(to_int(d.get("jobType"))),
        "is_full_time": bool_or_none(d.get("isFullTime")),
        "is_part_time": bool_or_none(d.get("isPartTime")),
        "remote_working": working_option(remote),
        "salary": _salary_from_codes(d.get("salaryFrom"), d.get("salaryTo"), d.get("salaryType"),
                                     to_int(d.get("salaryDescription")), display_salary,
                                     d.get("salaryFromPerAnnum") if "salaryFromPerAnnum" in d else None,
                                     d.get("salaryToPerAnnum") if "salaryToPerAnnum" in d else None),
        "location": {
            "name": text(d.get("displayLocationName") or d.get("locationName")),
            "town": text(d.get("townLocation")),
            "county": text(d.get("countyLocation") or d.get("countyName")),
            "latitude": to_float(d.get("latitude")),
            "longitude": to_float(d.get("longitude")),
        },
        "employer": _employer_from_row(d, row if row is not d else None),
        "taxonomy": {
            "domain": text(d.get("taxonomyKnowledgeDomain")),
            "role": text(d.get("taxonomyLevel1")),
            "title": text(d.get("taxonomyLevel2")),
            "specialism": text(d.get("taxonomyLevel3")),
            "sector_id": to_int(d.get("parentSectorId")) or None,
        },
        "flags": {
            "is_featured": bool_or_none(d.get("featuredLabel")),
            "is_promoted": bool_or_none(d.get("isPromoted")),
            "is_priority": bool_or_none(d.get("isPriority")),
            "is_top_job": bool_or_none(d.get("isTopJob")),
            "is_easy_apply": bool_or_none(d.get("isEasyApply")),
            "is_early_bird": bool_or_none(d.get("isEarlyBird")),
            "is_training_course": bool_or_none(d.get("isTrainingJob")),
            "is_survey_job": bool_or_none(d.get("isSurveyJob")),
            "is_branded": bool_or_none(d.get("isBranded")),
            "requires_uk_eligibility": bool_or_none(d.get("eligibleUkOnly")),
            "has_screening_questions": bool_or_none(d.get("hasScreeningQuestions")),
            "has_external_application": bool(external) if external is not None or "hasExternalUrl" in d else None,
        },
        "application_count": to_int(d.get("applicationCount")),
        "external_application_link": external,
        "posted_at": iso_datetime(d.get("displayDate")),
        "updated_at": iso_datetime(d.get("dateUpdated")),
        "expires_at": iso_datetime(d.get("expiryDate")),
    }
    if not any(out["location"][k] is not None for k in ("town", "latitude", "longitude")):
        out["location"] = {"name": out["location"]["name"], "county": out["location"]["county"]}
    return out


def _slugify(title):
    if not title:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or None


def job_rows(rows, display_salaries=None):
    display_salaries = display_salaries or {}
    out = []
    for row in rows or []:
        parsed = job_row(row, display_salaries.get(str(((row or {}).get("jobDetail") or row or {}).get("jobId"))))
        if parsed:
            out.append(parsed)
    return out


_CARD_RE = re.compile(r'<article[^>]*data-qa="job-card"[^>]*data-id="job(\d+)"[^>]*>(.*?)</article>', re.S)
_CARD_SALARY_RE = re.compile(r'data-qa="job-metadata-salary"[^>]*>(.*?)</li>', re.S)


def card_salaries(html):
    """{job id: displayed salary text} from the search page's job cards —
    the JSON rows carry codes, the cards the site's own wording
    ("Salary negotiable", "£550 - £617.55 per day")."""
    out = {}
    for job_id, body in _CARD_RE.findall(html or ""):
        match = _CARD_SALARY_RE.search(body)
        if match:
            out[job_id] = text(_TAG_RE.sub("", match.group(1)))
    return out


def similar_searches(rows):
    out = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        title = text(row.get("JobTitle") or row.get("title"))
        link = refs.absolute(refs.strip_tracking(row.get("JobTitleUrl") or row.get("url")))
        if title or link:
            out.append({"title": title, "link": link})
    return out


def search_facets(facets, sector_names=None):
    """searchFacets -> grouped counts. `sector_names` ({id: name}) labels the
    sector counts when the page's filter options are at hand."""
    f = facets if isinstance(facets, dict) else {}
    sector_names = sector_names or {}
    sectors = []
    for sector_id, count in (f.get("parentSectors") or {}).items():
        sectors.append({"id": to_int(sector_id), "name": sector_names.get(str(sector_id)), "jobs_count": to_int(count)})
    sectors.sort(key=lambda s: -(s["jobs_count"] or 0))
    remote = {working_option(k) or k: to_int(v) for k, v in (f.get("remoteWorkingOption") or {}).items()}
    return {
        "contract_type": {"permanent": to_int(f.get("permanent")), "contract": to_int(f.get("contract")),
                          "temporary": to_int(f.get("temp"))},
        "working_hours": {"full_time": to_int(f.get("fullTime")), "part_time": to_int(f.get("partTime"))},
        "remote_working": {"remote": remote.get("remote"), "hybrid": remote.get("hybrid"), "on_site": remote.get("on_site")},
        "posted_by": {"recruitment_agency": to_int(f.get("agency")), "direct_employer": to_int(f.get("employer")),
                      "reed": to_int(f.get("reed"))},
        "posted_within": {"today": to_int(f.get("today")), "last_3_days": to_int(f.get("last3Days")),
                          "last_week": to_int(f.get("lastWeek")), "last_2_weeks": to_int(f.get("last2Weeks"))},
        "badges": {"early_bird": to_int(f.get("earlyBirdJobs")), "visa_sponsorship": to_int(f.get("visaSponsorshipJobs")),
                   "training_courses": to_int(f.get("trainingJobs")), "survey_jobs": to_int(f.get("surveyJobs"))},
        "sectors": sectors,
        "locations": [{"name": text(k).title() if k and k[:1].islower() else text(k), "jobs_count": to_int(v)}
                      for k, v in (f.get("childLocations") or {}).items()],
    }


def sector_names_from_filters(filters):
    """pageProps.filters.specialisms.options -> {sector id: name}."""
    out = {}
    options = ((filters or {}).get("specialisms") or {}).get("options") or []
    for option in options:
        if not isinstance(option, dict):
            continue
        name = str(option.get("name") or "")
        sector_id = name.rsplit(".", 1)[-1] if "." in name else None
        if sector_id and sector_id.isdigit():
            out[sector_id] = text(option.get("text"))
    return out


def sectors_from_filters(filters):
    """The site's sector filter options -> [{id, name, jobs_count}] (live counts)."""
    out = []
    for option in (((filters or {}).get("specialisms") or {}).get("options") or []):
        if not isinstance(option, dict):
            continue
        name = str(option.get("name") or "")
        sector_id = name.rsplit(".", 1)[-1] if "." in name else None
        if sector_id and sector_id.isdigit():
            out.append({"id": int(sector_id), "name": text(option.get("text")), "jobs_count": to_int(option.get("count"))})
    out.sort(key=lambda s: s["id"])
    return out


def location_substitutes(rows):
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            name = text(row.get("locationName") or row.get("name") or row.get("displayName"))
            if name:
                out.append(name)
        elif isinstance(row, str) and row.strip():
            out.append(row.strip())
    return out


# ---- job details ---------------------------------------------------------------------

def _branding(jd):
    styling = jd.get("jobStyling") if isinstance(jd.get("jobStyling"), dict) else {}
    template = jd.get("brandedTemplate") if isinstance(jd.get("brandedTemplate"), dict) else {}
    style = styling.get("style") if isinstance(styling.get("style"), dict) else {}
    banner = text(template.get("bannerFilename"))
    gallery = []
    for media in template.get("galleryMedia") or []:
        if isinstance(media, dict):
            link = text(media.get("url") or media.get("fileName") or media.get("filename"))
            if link:
                gallery.append(link if link.startswith("http") else f"https://resources.reed.co.uk/brandedjob/gallery/thumbnail/{link}")
        elif isinstance(media, str):
            gallery.append(media)
    return {
        "style": text(style.get("name")).lower() if text(style.get("name")) else None,
        "is_branded": bool_or_none(styling.get("isBranded")),
        "has_branded_template": bool_or_none(styling.get("isBrandedTemplate")) and bool_or_none(template.get("isEnabled")),
        "banner": f"https://resources.reed.co.uk/brandedjob/banners/resized/{banner}" if banner else None,
        "banner_colour": text(template.get("bannerColourHex")),
        "gallery": gallery,
    }


def _screening_questions(jd):
    out = []
    for key in ("jobScreeningQuestionsV3", "jobScreeningQuestionsV2", "jobScreeningQuestions"):
        rows = jd.get(key)
        if isinstance(rows, dict):
            rows = rows.get("questions") or rows.get("items") or list(rows.values())
        if not isinstance(rows, list) or not rows:
            continue
        for row in rows:
            if isinstance(row, dict):
                question = text(row.get("question") or row.get("text") or row.get("questionText") or row.get("title"))
                if question:
                    out.append({"question": question,
                                "type": text(row.get("type") or row.get("questionType") or row.get("answerType")),
                                "is_required": bool_or_none(row.get("isRequired") or row.get("required")),
                                "options": [text(o) if isinstance(o, str) else text((o or {}).get("text") or (o or {}).get("answer"))
                                            for o in (row.get("options") or row.get("answers") or []) if o]})
            elif isinstance(row, str) and row.strip():
                out.append({"question": row.strip(), "type": None, "is_required": None, "options": []})
        if out:
            break
    return out


def _skills(jd):
    rows = jd.get("jobSkills")
    if isinstance(rows, dict):
        rows = rows.get("skills") or rows.get("items") or []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, str):
            name = text(row)
        elif isinstance(row, dict):
            name = text(row.get("name") or row.get("skillName") or row.get("skill") or row.get("title"))
        else:
            name = None
        if name and name not in out:
            out.append(name)
    return out


def job_details(jd, canonical_link=None, truncated=False):
    """consolidatedJobDetails.jobDetails (or one of its similarJobs) -> the
    full job record. `truncated` marks a similar-job row whose description
    the site cut short."""
    if not isinstance(jd, dict) or not to_int(jd.get("id")):
        return None
    job_id = to_int(jd.get("id"))
    title = text(jd.get("title"))
    owner = jd.get("jobOwner") if isinstance(jd.get("jobOwner"), dict) else {}
    salary = jd.get("jobSalary") if isinstance(jd.get("jobSalary"), dict) else {}
    loc = jd.get("jobLocation") if isinstance(jd.get("jobLocation"), dict) else {}
    hours = jd.get("jobEmploymentHours") if isinstance(jd.get("jobEmploymentHours"), dict) else {}
    contract = jd.get("jobContractType") if isinstance(jd.get("jobContractType"), dict) else {}
    sector = jd.get("jobSector") if isinstance(jd.get("jobSector"), dict) else {}
    cover = jd.get("jobCoverLetterPreference") if isinstance(jd.get("jobCoverLetterPreference"), dict) else {}
    salary_type = salary.get("type") if isinstance(salary.get("type"), dict) else {}
    description_html = jd.get("description") if isinstance(jd.get("description"), str) else None
    hidden_flags = {k: bool(salary.get(k)) for k in ("isNegotiableHideSalary", "hasCommissionHideSalary", "isCompetitiveHideSalary")}
    hidden_as = ("negotiable" if hidden_flags["isNegotiableHideSalary"] else "commission" if hidden_flags["hasCommissionHideSalary"]
                 else "competitive" if hidden_flags["isCompetitiveHideSalary"] else SALARY_DESCRIPTIONS.get(to_int(salary.get("salaryDescriptionType"))))
    if hidden_as is None and to_int(salary.get("salaryDescriptionType")):
        hidden_as = "hidden"
    is_hidden = bool(hidden_as) or (not number(salary.get("from")) and not number(salary.get("to")))
    profile_id = to_int(owner.get("profileId"))
    company_profile_id = to_int(owner.get("companyProfileId"))
    logo = text(owner.get("profileLogoImage") or owner.get("ouLogoImage"))
    banner = text(owner.get("profileBannerImage") or owner.get("ouBannerImage"))
    contract_name = text(contract.get("name"))
    out = {
        "id": job_id,
        "title": title,
        "link": canonical_link or refs.job_link(job_id, _slugify(title)),
        "description_html": description_html,
        "description_text": strip_html(description_html),
        "is_description_truncated": True if truncated else None,
        "contract_type": contract_name.lower() if contract_name else (
            "permanent" if jd.get("isPermanent") else "contract" if jd.get("isContract") else "temporary" if jd.get("isTemp") else None),
        "is_full_time": bool_or_none(hours.get("isFullTime")),
        "is_part_time": bool_or_none(hours.get("isPartTime")),
        "remote_working": working_option(loc.get("workingOption")),
        "salary": {
            "display": text(salary.get("displaySalary")),
            "min": number(salary.get("from")),
            "max": number(salary.get("to")),
            "min_annual": number(salary.get("fromPerAnnum")),
            "max_annual": number(salary.get("toPerAnnum")),
            "currency": CURRENCY,
            "period": SALARY_PERIOD_NAMES.get((text(salary_type.get("name")) or "").lower()) or SALARY_PERIODS.get(to_int(salary_type.get("id"))),
            "is_hidden": is_hidden,
            "hidden_as": hidden_as,
            "is_ote": bool_or_none(salary.get("isOte")),
            "is_pro_rata": bool_or_none(salary.get("isProRata")),
            "is_negotiable": bool_or_none(salary.get("isNegotiable")) or hidden_flags["isNegotiableHideSalary"],
            "has_included_benefits": bool_or_none(salary.get("hasIncludedBenefits")),
        },
        "location": {
            "name": text(loc.get("locationName")),
            "town": text(loc.get("townName")),
            "county": text(loc.get("countyName")),
            "region": text(loc.get("regionName")),
            "country": text(loc.get("countryName")),
            "country_code": text(loc.get("countryCode")),
            "nation": text(loc.get("subCountryName")),
            "postcode": text(loc.get("postCode")),
            "is_remote_job": bool_or_none(loc.get("isRemoteJob")),
            "inferred_type": working_option(loc.get("inferredJobLocationType")),
            "location_id": to_int(loc.get("displayId")),
        },
        "employer": {
            "id": to_int(owner.get("ouId")),
            "name": text(owner.get("ouName") or owner.get("profileName")),
            "profile_id": profile_id,
            "profile_name": text(owner.get("profileName")),
            "company_profile_id": company_profile_id,
            "type": EMPLOYER_TYPES.get(to_int(owner.get("ouType"))) or (
                "recruitment_agency" if jd.get("isAgency") else "direct_employer" if jd.get("isEmployer") else "reed" if jd.get("isReed") else None),
            "link": refs.employer_jobs_link(profile_id, text(owner.get("profileUrl"))),
            "company_profile_link": refs.company_profile_link(text(owner.get("companyProfileUrl")) or company_profile_id),
            # Reed serves profile logos only under logos/thumbs/ (the plain path 404s);
            # banners live at the plain path.
            "logo": refs.logo_link(logo, thumb=True),
            "banner": refs.logo_link(banner),
            "job_reference": text(owner.get("reference")),
        },
        "sector": {
            "id": to_int(sector.get("id")),
            "name": text(sector.get("name")),
            "parent_id": to_int(sector.get("parentId")),
            "parent_name": text(sector.get("parentName")),
        },
        "taxonomy": text(jd.get("taxonomy")),
        "breadcrumbs": [text(b) for b in (jd.get("breadcrumbs") or []) if text(b)],
        "skills": _skills(jd),
        "screening_questions": _screening_questions(jd),
        "application": {
            "is_easy_apply": bool_or_none(jd.get("isEasyApply")),
            "is_external": bool_or_none(jd.get("isRedirect")),
            "requires_uk_eligibility": bool_or_none(jd.get("hasEligibilityToWorkInUk")),
            "eligibility_requirement": text(jd.get("jobApplicationEligibilityRequirement")),
            "cover_letter": (text(cover.get("name")) or "").lower() or None,
        },
        "flags": {
            "is_featured": bool_or_none(jd.get("isFeatured")),
            "is_promoted": bool_or_none(jd.get("isPromoted")),
            "is_graduate": bool_or_none(jd.get("isGraduate")),
            "is_management_executive": bool_or_none(jd.get("isManageExec")),
            "is_multilingual": bool_or_none(jd.get("isMultilingual")),
            "is_training_course": bool_or_none(jd.get("isTrainingJob")),
            "is_early_bird": bool_or_none(jd.get("isEarlyBird")),
            "is_live": bool_or_none(jd.get("isLive")),
            "is_suspended": bool_or_none(jd.get("isSuspended")),
            "is_public": bool_or_none(jd.get("isPublic")),
            "is_posted_by_agency": bool_or_none(jd.get("isAgency")),
            "is_posted_by_employer": bool_or_none(jd.get("isEmployer")),
            "is_posted_by_reed": bool_or_none(jd.get("isReed")),
        },
        "branding": _branding(jd),
        "posted_at": iso_datetime(jd.get("displayDate")),
        "created_at": iso_datetime(jd.get("createdDate")),
        "updated_at": iso_datetime(jd.get("updatedDate")),
        "expires_at": iso_datetime(jd.get("expiryDate")),
    }
    if not truncated:
        out.pop("is_description_truncated")
    return out


def recommended_courses(block):
    """consolidatedJobDetails.recommendedCourses / pageProps.coursesRecommendations."""
    if not isinstance(block, dict):
        return []
    out = []
    for row in block.get("recommendedCourses") or []:
        if not isinstance(row, dict):
            continue
        price = text(row.get("price"))
        out.append({
            "id": to_int(row.get("id")),
            "title": text(row.get("title")),
            "link": refs.absolute(row.get("url")),
            "price": {"amount": first_number(price) if price and "£" in price else (0 if (price or "").lower() == "free" else None),
                      "currency": CURRENCY, "display": price},
            "study_method": text(row.get("type")),
        })
    return out


# ---- company profile -------------------------------------------------------------------

def _header_title(block):
    header = (block or {}).get("header") if isinstance(block, dict) else None
    return text((header or {}).get("headerTitle")) if isinstance(header, dict) else None


def company_profile(cp):
    if not isinstance(cp, dict) or not to_int(cp.get("companyProfileId")):
        return None
    profile_id = to_int(cp.get("profileId"))
    slug = text(cp.get("companyProfileUrl"))
    sector = cp.get("companySector") if isinstance(cp.get("companySector"), dict) else {}
    about = []
    for article in cp.get("articles") or []:
        if not isinstance(article, dict):
            continue
        body = article.get("text")
        header = article.get("header") if isinstance(article.get("header"), dict) else {}
        about.append({"title": text(header.get("headerTitle")), "kind": (text(header.get("headerType")) or "").lower() or None,
                      "html": body if isinstance(body, str) and "<" in body else None,
                      "text": strip_html(body) if isinstance(body, str) else None})
    benefits_block = cp.get("benefitsContent") if isinstance(cp.get("benefitsContent"), dict) else {}
    benefits = [{"category": text(b.get("categoryName")), "detail": text(b.get("benefitDetails"))}
                for b in (benefits_block.get("benefits") or []) if isinstance(b, dict)]
    links_block = cp.get("externalLinksContent") if isinstance(cp.get("externalLinksContent"), dict) else {}
    links = [{"name": text(l.get("linkDescription")), "link": text(l.get("linkValue"))}
             for l in (links_block.get("externalLinks") or []) if isinstance(l, dict) and text(l.get("linkValue"))]
    images_block = cp.get("imagesContent") if isinstance(cp.get("imagesContent"), dict) else {}
    images = [text(i.get("imageUrl")) for i in (images_block.get("images") or []) if isinstance(i, dict) and text(i.get("imageUrl"))]
    videos_block = cp.get("videosContent") if isinstance(cp.get("videosContent"), dict) else {}
    videos = []
    for v in videos_block.get("videos") or []:
        if isinstance(v, dict):
            link = text(v.get("videoUrl") or v.get("url") or v.get("embedUrl"))
            if link:
                videos.append({"title": text(v.get("title") or v.get("videoTitle")), "link": link})
    return {
        "id": to_int(cp.get("companyProfileId")),
        "name": text(cp.get("companyName")),
        "link": refs.company_profile_link(slug or cp.get("companyProfileId")),
        "profile_id": profile_id,
        "jobs_link": refs.employer_jobs_link(profile_id, text(cp.get("profileUrl"))),
        "website": text(cp.get("websiteUrl")),
        "employee_count_range": text(cp.get("employeeCountRange")),
        "sector": {"id": to_int(sector.get("sectorId")), "name": text(sector.get("sectorName")),
                   "directory_slug": text(sector.get("directoryName"))},
        "location": {"name": text(cp.get("locationText")), "latitude": to_float(cp.get("latitude")),
                     "longitude": to_float(cp.get("longitude"))},
        "logo": text(cp.get("logoImageUrl")),
        "banner": text(cp.get("bannerImageUrl")),
        "about": about,
        "benefits": benefits,
        "benefits_title": _header_title(benefits_block),
        "social_links": links,
        "images": images,
        "videos": videos,
        "live_jobs_count": to_int(cp.get("totalJobsCount")),
        "recent_jobs": job_rows(cp.get("recentJobs")),
    }


# ---- recruiter directory ----------------------------------------------------------------

_DIR_CARD_RE = re.compile(
    r'<a href="(/jobs/[^"]+/p(\d+)[^"]*)"[^>]*class="profile-link">\s*<img[^>]*?(?:data-src|src)="([^"]*)"[^>]*alt="([^"]*)"'
    r'.*?class="count-jobs-company">\(([\d,]+)\)</span>', re.S)


def directory_cards(html):
    out = []
    seen = set()
    for href, profile_id, logo, alt, count in _DIR_CARD_RE.findall(html or ""):
        if profile_id in seen:
            continue
        seen.add(profile_id)
        name = text(re.sub(r"\s+jobs$", "", html_lib.unescape(alt)))
        slug = href.split("/p" + profile_id)[0].rsplit("/", 1)[-1]
        out.append({
            "name": name,
            "profile_id": int(profile_id),
            "link": refs.employer_jobs_link(profile_id, slug),
            "logo": logo.split("?")[0] if logo.startswith("http") else None,
            "live_jobs_count": to_int(count),
        })
    return out


def directory_last_page(html):
    pages = [int(p) for p in re.findall(r"[?&]pageno=(\d+)", html or "")]
    return max(pages) if pages else 1


def directory_heading(html):
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.S)
    return text(_TAG_RE.sub("", match.group(1))) if match else None


# ---- average salary ---------------------------------------------------------------------

def salary_page(html, job_title, location=None):
    h = html or ""
    average = re.search(r'class="salary-title-value">([^<]*)<', h)
    low = re.search(r'lowest-salary">.*?salary-value">([^<]*)<', h, re.S)
    high = re.search(r'highest-salary">.*?salary-value">([^<]*)<', h, re.S)
    info = re.findall(r'salary-info-title">([^<]*)</span>\s*</div>\s*<span[^>]*>([^<]*)<', h, re.S)
    counts = {"new_jobs_last_day": None, "jobs": None, "jobs_above_average": None}
    for value, label in info:
        label = label.lower()
        if "last day" in label:
            counts["new_jobs_last_day"] = first_number(value)
        elif "more than the average" in label:
            counts["jobs_above_average"] = first_number(value)
        elif "jobs" in label:
            counts["jobs"] = first_number(value)
    jobs_link = re.search(r'class="lnk-view-jobs" href="([^"]+)"', h)
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
    heading_text = text(_TAG_RE.sub("", heading.group(1))) if heading else None
    by_location = []
    for href in dict.fromkeys(re.findall(r'href="(/average-salary/average-[^"]+-salary-in-[^"]+)"', h)):
        place = href.rsplit("-salary-in-", 1)[-1].replace("-", " ")
        by_location.append({"location": place.title(), "link": refs.absolute(href)})
    if average is None:
        return None
    return {
        "job_title": job_title,
        "location": location or "UK",
        "heading": heading_text,
        "currency": CURRENCY,
        "period": "annual",
        "average": first_number(html_lib.unescape(average.group(1))),
        "low": first_number(html_lib.unescape(low.group(1))) if low else None,
        "high": first_number(html_lib.unescape(high.group(1))) if high else None,
        "jobs_count": counts["jobs"],
        "new_jobs_last_day_count": counts["new_jobs_last_day"],
        "jobs_above_average_count": counts["jobs_above_average"],
        "jobs_link": refs.absolute(html_lib.unescape(jobs_link.group(1))) if jobs_link else None,
        "by_location": by_location,
    }


# ---- autocomplete -----------------------------------------------------------------------

def job_title_suggestions(rows):
    out = []
    for row in rows or []:
        value = row.get("value") if isinstance(row, dict) else None
        title = text((value or {}).get("JobTitle")) if isinstance(value, dict) else text(row) if isinstance(row, str) else None
        if title and title not in out:
            out.append(title)
    return out


def place_suggestions(rows):
    return [text(r) for r in (rows or []) if isinstance(r, str) and text(r)]


# ---- courses: search cards -------------------------------------------------------------

_COURSE_CARD_RE = re.compile(r'<article id="(\d+)"\s+class="([^"]*)"[^>]*>(.*?)</article>', re.S)
_PRICE_RE = re.compile(r"£\s*([\d,]+(?:\.\d+)?)")


def _price_block(fragment):
    """'<span class="price">£15</span> <small><span class="was-price">£19</span></small>'
    + 'Save 21%' -> price dict."""
    current = re.search(r'class="(?:price|current-price)">([^<]*)<', fragment or "")
    was = re.search(r'class="was-price">([^<]*)<', fragment or "")
    was_inline = re.search(r"\(was\s*([^)]*)\)", html_lib.unescape(fragment or ""))
    saving = re.search(r"Save\s+(\d+)%", fragment or "")
    current_text = text(current.group(1)) if current else None
    amount = None
    if current_text:
        amount = 0 if current_text.lower() == "free" else first_number(current_text)
    was_text = text(was.group(1)) if was else (text(was_inline.group(1)) if was_inline else None)
    return {
        "amount": amount,
        "was_amount": first_number(was_text) if was_text else None,
        "currency": CURRENCY,
        "discount_percent": to_int(saving.group(1)) if saving else None,
        "is_free": amount == 0 if amount is not None else None,
        "includes_vat": True if "inc VAT" in (fragment or "") else None,
    }


def _key_info(body):
    bubbles = [text(_TAG_RE.sub(" ", b)) for b in re.findall(r'class="bubble-text">(.*?)</span>', body, re.S)]
    out = {"students_count": None, "study_method": None, "duration": None, "has_certificate": None,
           "cpd_points": None, "has_tutor_support": None, "key_info": [b for b in bubbles if b]}
    for bubble in out["key_info"]:
        low = bubble.lower()
        if low.endswith("students") or low.endswith("student"):
            out["students_count"] = first_number(bubble)
        elif low in ("online", "classroom", "in company", "in-company", "online, classroom", "classroom, online") or low.startswith(("online", "classroom")) and "hour" not in low and "day" not in low and "week" not in low:
            out["study_method"] = low.replace("in-company", "in_company").replace("in company", "in_company").replace(", ", ",")
        elif "cpd" in low:
            out["cpd_points"] = first_number(bubble)
        elif "certificate" in low:
            out["has_certificate"] = True
        elif "tutor" in low:
            out["has_tutor_support"] = True
        elif re.search(r"\d\s*(hour|day|week|month|year|min)", low) or "self-paced" in low or "full-time" in low or "part-time" in low:
            out["duration"] = bubble.replace(" · ", " · ")
    return out


def course_cards(html, ga_items=None):
    """The search page's <article> cards (+ the page's GA item list for
    ratings / badges / qualification type) -> course cards, in page order,
    sponsored placements flagged."""
    ga = {}
    for item in ga_items or []:
        if isinstance(item, dict) and item.get("item_id") is not None:
            ga[str(item.get("item_id"))] = item
    out = []
    for course_id, classes, body in _COURSE_CARD_RE.findall(html or ""):
        if 'data-qa="searchCards"' not in body and "searchCards" not in classes and "course-card" not in classes:
            continue
        title_match = re.search(r'course-card-title[^>]*>\s*<a href="([^"#?]+)[^"]*"[^>]*title="([^"]*)"', body, re.S)
        if not title_match:
            title_match = re.search(r'course-card-title[^>]*>\s*<a href="([^"#?]+)[^"]*"[^>]*>(.*?)</a>', body, re.S)
        link = refs.absolute(title_match.group(1)) if title_match else refs.course_link(course_id)
        title = text(_TAG_RE.sub("", title_match.group(2))) if title_match else None
        provider = re.search(r'class="provider-name">(.*?)</div>', body, re.S)
        subtitle = re.search(r'class="course-card-subtitle">(.*?)</div>', body, re.S)
        image = re.search(r'<img src="([^"]+)"[^>]*class="course-img"', body)
        excerpt = re.search(r'class="excerpt">(.*?)</div>', body, re.S)
        badges = [text(b) for b in re.findall(r'class="[a-z-]+-badge badge">([^<]*)<', body)]
        lod = re.search(r'class="course-card-lod-badge">([^<]*)<', body)
        price_fragment = re.search(r'class="course-card-price">(.*?)</div>\s*</div>', body, re.S)
        info = _key_info(body)
        ga_item = ga.get(course_id) or {}
        rating = to_float(ga_item.get("course_rating")) if str(ga_item.get("course_rating", "")).replace(".", "", 1).isdigit() else None
        qualification = text(ga_item.get("course_qualification_type"))
        is_sponsored = "SearchSponsored" in body or 'data-sponsored-courseid' in body
        out.append({
            "id": int(course_id),
            "title": title,
            "link": link,
            "subtitle": text(_TAG_RE.sub("", subtitle.group(1))) if subtitle else None,
            "provider": {"name": text(_TAG_RE.sub("", provider.group(1))) if provider else text(ga_item.get("item_brand"))},
            "image": text(image.group(1)) if image else None,
            "price": _price_block(price_fragment.group(0) if price_fragment else body),
            "study_method": (text(ga_item.get("item_variant")) or info["study_method"] or "").lower().replace("paid_lod", "online").replace("free_lod", "online") or None,
            "is_on_demand": True if (lod and "demand" in lod.group(1).lower()) or "course-on-demand" in classes else None,
            "duration": info["duration"],
            "students_count": info["students_count"],
            "cpd_points": info["cpd_points"],
            "has_certificate": info["has_certificate"],
            "has_tutor_support": info["has_tutor_support"],
            "key_info": info["key_info"],
            "badges": [b.lower().replace(" ", "_") for b in badges if b],
            "rating": rating,
            "qualification_type": qualification,
            "has_job_guarantee": {"True": True, "False": False}.get(str(ga_item.get("is_job_guaranteed"))),
            "subjects": [s.strip() for s in str(ga_item.get("item_category2") or "").replace(",_", ",").split(",") if s.strip()] or None,
            "excerpt": text(_TAG_RE.sub(" ", excerpt.group(1))).rstrip("…").strip() if excerpt else None,
            "is_sponsored": is_sponsored,
        })
    return out


def course_search_total(html):
    match = re.search(r"Browse ([\d,]+)", html or "") or re.search(r"([\d,]+) matching courses", html or "")
    return to_int(match.group(1)) if match else None


def course_search_last_page(html):
    pages = [int(p) for p in re.findall(r"[?&]pageno=(\d+)", html or "")]
    of = re.search(r'class="of-number[^"]*">of (\d+)<', html or "")
    candidates = pages + ([int(of.group(1))] if of else [])
    return max(candidates) if candidates else 1


def course_search_heading(html):
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.S)
    return text(_TAG_RE.sub("", match.group(1))) if match else None


# ---- courses: details ------------------------------------------------------------------

def _section_html(html, section_id):
    """Inner HTML of <div class="collapse ..." id="{section_id}">…</div> up to
    the closing </section>, or None."""
    match = re.search(r'<div class="collapse[^"]*"\s+id="%s">(.*?)</section>' % re.escape(section_id), html or "", re.S)
    if not match:
        return None
    body = match.group(1)
    # drop the trailing wrapper divs the regex swallowed
    body = re.sub(r"(\s*</div>\s*)+$", "", body)
    return body.strip() or None


def _summary_rows(html):
    """The summary card's header/content rows -> {header slug: inner HTML}."""
    card = re.search(r'<div class="summary-card[^"]*">(.*?)<div class="summary-social">', html or "", re.S)
    out = {}
    if not card:
        return out
    for header, content in re.findall(r'<div class="col-sm-4 summary-header">\s*(.*?)\s*</div>\s*<div class="col-sm-8 (?:summary-content|summary-list)"[^>]*>(.*?)</div>\s*</div>', card.group(1), re.S):
        key = re.sub(r"[^a-z0-9]+", "_", text(_TAG_RE.sub("", header)).lower()).strip("_")
        out[key] = content
    return out


def _list_items(fragment):
    items = [text(_TAG_RE.sub(" ", li)) for li in re.findall(r"<li[^>]*>(.*?)</li>", fragment or "", re.S)]
    return [i for i in items if i]


def _plain(fragment):
    if not fragment:
        return None
    fragment = re.sub(r'<a class="info-popover".*?</a>', "", fragment, flags=re.S)
    return text(_TAG_RE.sub(" ", fragment))


def _curriculum(html):
    section = _section_html(html, "curriculum")
    if not section:
        return None
    format_ = re.search(r"Format:</span>\s*([^<]*)<", section)
    duration = re.search(r"Duration:</span>\s*([^<]*)<", section)
    modules = []
    for title_html, items_html in re.findall(r'<h3 class="h4 section-title">(.*?)</h3>\s*<ul[^>]*>(.*?)</ul>', section, re.S):
        duration_match = re.search(r'class="curriculum-duration">([^<]*)<', title_html)
        title = text(_TAG_RE.sub(" ", re.sub(r'<span class="curriculum-duration">.*?</span>', "", title_html, flags=re.S)))
        lectures = []
        for item in re.findall(r'<li class="lecture-item">(.*?)</li>', items_html, re.S):
            spans = re.findall(r"<span[^>]*>(.*?)</span>", item, re.S)
            name = text(_TAG_RE.sub("", spans[0])) if spans else None
            name = re.sub(r"^\d+:\s*", "", name) if name else None
            lectures.append({"title": name, "duration": text(spans[1]) if len(spans) > 1 else None})
        modules.append({"title": title, "duration": text(duration_match.group(1)) if duration_match else None,
                        "lectures": lectures})
    return {"format": text(format_.group(1)) if format_ else None,
            "duration": text(duration.group(1)) if duration else None,
            "modules": modules}


def _rating_summary(html):
    score = re.search(r'class="provider-score">\s*([\d.]+)\s*<', html or "")
    if not score:
        return None
    pct = {}
    for key in ("service", "content", "value"):
        match = re.search(r'id="%sCircle".*?percentage-circle-inside-circle">\s*(\d+)%%' % key, html, re.S)
        pct[key] = to_int(match.group(1)) if match else None
    return {"average": to_float(score.group(1)), "service_percent": pct["service"],
            "content_percent": pct["content"], "value_for_money_percent": pct["value"]}


def _provider_from_page(html, blob):
    slug_match = re.search(r'href="/courses/provider-profiles/([^"/?#]+)"\s+class="provider-link"[^>]*>(.*?)</a>', html or "", re.S)
    logo = re.search(r'<img src="(https://resources\.reed\.co\.uk/courses/providermedia/\d+/[^"]+)"', html or "")
    provider_id = to_int((blob or {}).get("providerId"))
    slug = slug_match.group(1) if slug_match else None
    return {
        "id": provider_id,
        "name": text((blob or {}).get("providerName")) or (text(_TAG_RE.sub("", slug_match.group(2))) if slug_match else None),
        "slug": slug,
        "link": refs.provider_profile_link(slug),
        "courses_link": refs.provider_courses_link(provider_id, slug),
        "logo": logo.group(1).split("?")[0] if logo else None,
    }


def _questions(blob):
    out = []
    for row in (blob or {}).get("questionAnswers") or []:
        if not isinstance(row, dict):
            continue
        out.append({"id": to_int(row.get("questionId")), "asked_by": text(row.get("name")),
                    "question": text(row.get("question")), "answer": text(row.get("answer")),
                    "asked_at": iso_datetime(row.get("questionCreatedOn")),
                    "helpful_count": to_int(row.get("helpfulCount"))})
    return out


def _breadcrumbs(html):
    crumbs = re.search(r'<ol class="breadcrumb">(.*?)</ol>', html or "", re.S)
    if not crumbs:
        return []
    return [text(_TAG_RE.sub("", li)) for li in re.findall(r"<li[^>]*>(.*?)</li>", crumbs.group(1), re.S) if text(_TAG_RE.sub("", li))]


def course_details(html, blob, course_id):
    """Course page HTML + its course-view init blob -> the course record."""
    h = html or ""
    blob = blob or {}
    details = blob.get("courseDetails") if isinstance(blob.get("courseDetails"), dict) else {}
    ga = blob.get("gaItem") if isinstance(blob.get("gaItem"), dict) else {}
    title_match = re.search(r"<h1>\s*(.*?)\s*<div", h, re.S)
    title = text(details.get("title")) or (text(_TAG_RE.sub("", title_match.group(1))) if title_match else None)
    subtitle = re.search(r'<header class="course-title">.*?<h2>(.*?)</h2>', h, re.S)
    canonical = re.search(r'<meta property="og:url" content="([^"]+)"', h)
    cover = re.search(r'<meta property="og:image" content="([^"]+)"', h)
    summary = _summary_rows(h)
    price_html = summary.get("price") or ""
    price = _price_block(price_html)
    if price["amount"] is None and details.get("price") is not None:
        price["amount"] = number(details.get("price"))
        price["is_free"] = price["amount"] == 0
    offer_ends = re.search(r'class="price-date">\s*Offer ends ([^<]*)<', price_html)
    purchases = re.search(r'id="number-enquiries-purchases">.*?<strong>([\d,]+)</strong>\s*([^<]*)<', h, re.S)
    badges = re.search(r'data-course-badge="([^"]*)"', h)
    achievement_html = summary.get("achievement")
    awarding = re.search(r'href="/courses/awarding-bodies/([^"]+)"[^>]*>([^<]*)<', achievement_html or "")
    study_method = _plain(summary.get("study_method"))
    cpd_html = summary.get("cpd") or ""
    cpd_first = re.search(r"<div>\s*(.*?)\s*</div>", cpd_html, re.S)
    cpd = _plain(cpd_first.group(1) if cpd_first else cpd_html)
    sections = {}
    for key, section_id in (("overview", "overview"), ("description", "descriptions"), ("requirements", "requirements"),
                            ("achievement", "achievement"), ("assessment", "assessmentDetailsSection"), ("cpd", "cpd")):
        body = _section_html(h, section_id)
        sections[key] = {"html": body, "text": strip_html(body)} if body else None
    who_for = re.search(r'<h2[^>]*>.*?Who is this course for\?.*?</h2>\s*<div class="collapse[^"]*"[^>]*>(.*?)</section>', h, re.S)
    career = re.search(r'<h2[^>]*>.*?Career path.*?</h2>\s*<div class="collapse[^"]*"[^>]*>(.*?)</section>', h, re.S)
    sections["who_is_this_for"] = {"html": who_for.group(1).strip(), "text": strip_html(who_for.group(1))} if who_for else None
    sections["career_path"] = {"html": career.group(1).strip(), "text": strip_html(career.group(1))} if career else None
    subjects = [s.strip() for s in str(details.get("dataLayerSubjects") or "").split(",") if s.strip()]
    return {
        "id": to_int(details.get("id")) or to_int(course_id),
        "title": title,
        "subtitle": text(_TAG_RE.sub("", subtitle.group(1))) if subtitle else None,
        "link": canonical.group(1).split("?")[0] if canonical else refs.course_link(course_id),
        "image": cover.group(1) if cover else None,
        "is_unavailable": bool_or_none(blob.get("isUnavailable")),
        "price": dict(price, offer_ends=text(offer_ends.group(1)) if offer_ends else None,
                      is_ex_vat=bool_or_none(details.get("isExVat"))),
        "study_method": study_method,
        "is_on_demand": bool_or_none(details.get("isOnDemand")),
        "can_buy_online": not bool(details.get("canEnquire")) if "canEnquire" in details else None,
        "can_enquire": bool_or_none(details.get("canEnquire")),
        "course_format": _plain(summary.get("course_format")),
        "duration": _plain(summary.get("duration")),
        "qualification": _plain(summary.get("qualification")),
        "qualification_type": text(details.get("dataLayerQualificationGroup")) or text(ga.get("course_qualification_type")),
        "cpd": cpd,
        "cpd_points": first_number(cpd) if cpd and "CPD" in cpd else None,
        "awarding_body": {"name": text(awarding.group(2)), "slug": awarding.group(1),
                          "link": refs.absolute(f"/courses/awarding-bodies/{awarding.group(1)}")} if awarding else None,
        "achievement": _plain(achievement_html),
        "certificates": _list_items(summary.get("certificates")),
        "assessment_details": _list_items(summary.get("assessment_details")),
        "additional_info": _list_items(summary.get("additional_info")),
        "finance_options": _plain(summary.get("finance_options")),
        "has_tutor_support": any("tutor" in i.lower() for i in _list_items(summary.get("additional_info"))) or None,
        "has_job_guarantee": bool_or_none(details.get("dataLayerHasJobGuarantee")),
        "badges": [b.strip() for b in (badges.group(1) if badges else "").split(",") if b.strip()],
        "rating": _rating_summary(h),
        "students_purchased_count": to_int(purchases.group(1)) if purchases and "purchased" in purchases.group(2) else None,
        "students_enquired_count": to_int(purchases.group(1)) if purchases and "enquir" in purchases.group(2) else None,
        "subjects": subjects,
        "breadcrumbs": _breadcrumbs(h),
        "provider": _provider_from_page(h, blob),
        "classroom_venues_count": to_int(blob.get("classroomCount")),
        "sections": sections,
        "curriculum": _curriculum(h),
        "questions_and_answers": _questions(blob),
    }


# ---- courses: reviews / providers ------------------------------------------------------

def review(row):
    if not isinstance(row, dict):
        return None
    return {
        "id": to_int(row.get("courseReviewId")),
        "rating": {
            "overall": round(to_float(row.get("overallCourseRating")), 2) if to_float(row.get("overallCourseRating")) is not None else None,
            "service": to_float(row.get("qualityOfServiceRating")),
            "content": to_float(row.get("courseContentRating")),
            "value_for_money": to_float(row.get("valueForMoneyRating")),
        },
        "course_title": text(row.get("title")),
        "text": text(row.get("reviewText")),
        "reviewer_name": text(row.get("reviewerName")),
        "created_at": iso_datetime(row.get("createdOn")),
        "purchased_at": iso_datetime(row.get("purchasedOn")),
        "provider": {"name": text(row.get("providerName")), "response": text(row.get("providerResponse")),
                     "responded_at": iso_datetime(row.get("providerResponseDate"))},
    }


def reviews_page(body, page, per_page):
    body = body if isinstance(body, dict) else {}
    meta = body.get("metaData") if isinstance(body.get("metaData"), dict) else {}
    rows = [r for r in (review(x) for x in (body.get("items") or [])) if r]
    total = to_int(meta.get("totalItemCount")) or 0
    return rows, {"page": to_int(meta.get("pageNumber")) or page, "items_per_page": to_int(meta.get("pageSize")) or per_page,
                  "total_pages": to_int(meta.get("pageCount")) or 0, "total_count": total}


def provider_result(row):
    if not isinstance(row, dict) or to_int(row.get("id")) is None:
        return None
    courses = row.get("courses") if isinstance(row.get("courses"), dict) else {}
    slug = (text(row.get("profileUrl")) or "").rsplit("/", 1)[-1] or None
    return {
        "id": to_int(row.get("id")),
        "name": text(row.get("name")),
        "slug": slug,
        "link": refs.absolute(row.get("profileUrl")),
        "courses_link": refs.provider_courses_link(to_int(row.get("id")), slug),
        "logo": (text(row.get("logoUrl")) or "").split("?")[0] or None,
        "rating": to_float(row.get("averageRating")) or None,
        "courses_count": to_int(courses.get("totalCount")),
        "has_online_courses": bool_or_none(courses.get("online")),
        "has_classroom_courses": bool_or_none(courses.get("classroom")),
        "has_in_company_courses": bool_or_none(courses.get("onSite")),
    }


def _ga_course(row):
    if not isinstance(row, dict) or to_int(row.get("id")) is None:
        return None
    badges = [b.strip() for b in str(row.get("dataLayerBadgeInfo") or "").split(",") if b.strip()]
    return {
        "id": to_int(row.get("id")),
        "title": text(row.get("title")),
        "link": refs.course_link(to_int(row.get("id")), _slugify(text(row.get("title")))),
        "price": {"amount": number(row.get("price")), "currency": CURRENCY},
        "study_method": text(row.get("dataLayerStudyMethod")),
        "is_on_demand": bool_or_none(row.get("isOnDemand")),
        "rating": to_float(row.get("dataLayerReviewRating")),
        "badges": badges,
        "qualification_type": text(row.get("dataLayerQualificationGroup")),
        "has_job_guarantee": bool_or_none(row.get("dataLayerHasJobGuarantee")),
        "subjects": [s.strip() for s in str(row.get("dataLayerSubjects") or "").split(",") if s.strip()],
    }


def provider_profile(html, blob, provider_id=None, slug=None):
    h = html or ""
    blob = blob or {}
    name = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
    rating = re.search(r'class="rating"[^>]*aria-label="([\d.]+)/5"', h)
    reviews_count = re.search(r'class="expanding-reviews-count"[^>]*>([\d,]+) reviews?<', h)
    about = re.search(r'<div id="aboutUs"[^>]*>\s*<h2>About us</h2>\s*<div>(.*?)</div>\s*</div>', h, re.S)
    logo = re.search(r'<img class="profile-img" src="([^"]+)"', h)
    cover = re.search(r'<source media="\(min-width: 768px\)" srcset="(https://resources\.reed\.co\.uk/courses/providermedia/[^"]+)"', h)
    courses_link = re.search(r'href="(/courses/[^"/]+/p(\d+))"', h)
    pid = to_int(blob.get("providerId")) or to_int(provider_id) or (to_int(courses_link.group(2)) if courses_link else None)
    website = re.search(r'id="top_enquireNow"', h)
    return {
        "id": pid,
        "name": text(blob.get("providerName")) or (text(_TAG_RE.sub("", name.group(1))) if name else None),
        "slug": slug,
        "link": refs.provider_profile_link(slug),
        "courses_link": refs.absolute(courses_link.group(1)) if courses_link else refs.provider_courses_link(pid),
        "logo": logo.group(1).split("?")[0] if logo else None,
        "cover_image": cover.group(1).split("?")[0] if cover else None,
        "rating": to_float(rating.group(1)) if rating else None,
        "reviews_count": to_int(reviews_count.group(1)) if reviews_count else None,
        "has_website_link": bool(website),
        "about_html": about.group(1).strip() if about else None,
        "about_text": strip_html(about.group(1)) if about else None,
        "popular_courses": [c for c in (_ga_course(r) for r in blob.get("popularCourses") or []) if c],
        "discounted_courses": [c for c in (_ga_course(r) for r in blob.get("discountCourses") or []) if c],
    }
