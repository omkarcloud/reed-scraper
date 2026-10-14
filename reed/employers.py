"""/reed/employers/* — the recruiter directory (employers hiring now, with
live job counts), every live job of one employer (the p{profile_id}
listing, which takes the full job search filter set) and the company
profile pages.

Three ids name an employer on the site:
  employer id   `ouId` — the advertiser account (on every job row)
  profile id    the `p{id}` of /jobs/{name}/p{id} — what the directory and
                the listing use (every job row carries it as employer.profile_id)
  company id    /company-profile/{Name}-{id} — only employers with a company
                profile have one (job details and the listing's companyProfile
                block carry it)
"""
import re

from reed import parsers as P
from reed import refs
from reed.fetch import ReedNotFound, get_html, get_page, init_blobs, page_props
from reed.jobs import load_search, search_block, search_path

# Directory specialism slug -> display name (the sidebar of /recruiterdirectory)
SPECIALISMS = {
    "accountancy": "Accountancy", "accountancy-qualified": "Accountancy (Qualified)",
    "admin-secretarial-pa": "Admin, Secretarial & PA", "apprenticeships": "Apprenticeships", "banking": "Banking",
    "charity-voluntary": "Charity & Voluntary", "construction-property": "Construction & Property",
    "customer-service": "Customer Service", "education": "Education", "energy": "Energy", "engineering": "Engineering",
    "estate-agency": "Estate Agency", "financial-services": "Financial Services", "fmcg": "FMCG",
    "general-insurance": "General Insurance", "graduate-training-internships": "Graduate Training & Internships",
    "health-medicine": "Health & Medicine", "hospitality-catering": "Hospitality & Catering",
    "human-resources": "Human Resources", "it-telecoms": "IT & Telecoms", "legal": "Legal",
    "leisure-tourism": "Leisure & Tourism", "manufacturing": "Manufacturing", "marketing-pr": "Marketing & PR",
    "media-digital-creative": "Media, Digital & Creative", "motoring-automotive": "Motoring & Automotive",
    "other": "Other", "public-sector": "Public Sector", "purchasing": "Purchasing",
    "recruitment-consultancy": "Recruitment Consultancy", "retail": "Retail", "sales": "Sales",
    "scientific": "Scientific", "security-safety": "Security & Safety", "social-care": "Social Care",
    "strategy-consultancy": "Strategy & Consultancy", "training": "Training", "transport-logistics": "Transport & Logistics",
}
EMPLOYER_TYPES = {"recruitment_agency": "agencies", "direct_employer": "direct"}
DIRECTORY_PAGE_SIZE = 20


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def search(query=None, employer_type=None, sector=None, location=None, distance_miles=None, page=1):
    """Employers with live jobs, from the recruiter directory. `sector` is a
    specialism slug or name (see SPECIALISMS); `location` narrows the live
    job counts to a place (within `distance_miles`)."""
    parts = ["/recruiterdirectory"]
    if employer_type:
        parts.append(EMPLOYER_TYPES[employer_type])
    if sector:
        parts.append(sector)
    if location:
        parts.append(_slug(location))
    path = "/".join(parts)
    params = {"keywords": query, "pageno": page if page and page > 1 else None, "proximity": distance_miles}
    html = get_html(path, params, label="employer directory")
    employers = P.directory_cards(html)
    last_page = P.directory_last_page(html)
    if page > 1 and not employers:
        raise ReedNotFound(f"page {page} is past the last page of the directory (last page {last_page})")
    return {
        "query": query,
        "employer_type": employer_type,
        "sector": {"slug": sector, "name": SPECIALISMS.get(sector)} if sector else None,
        "location": location,
        "distance_miles": distance_miles if location else None,
        "heading": P.directory_heading(html),
        "pagination": {"page": page, "items_per_page": DIRECTORY_PAGE_SIZE,
                       "total_pages": max(last_page, page) if not query else 1,
                       "total_count": len(employers) if query else None},
        "employers": employers,
    }


def jobs(employer, **kw):
    """Every live job of one employer (by profile id or listing link), with
    the search filters and facets of /reed/jobs/search."""
    link = employer.get("link") or {}
    kw = dict(kw)
    kw["keywords"] = kw.pop("query", None) or link.get("keywords")
    for key in ("location", "distance_miles", "min_salary", "max_salary", "sector_ids", "posted_within", "remote_working", "page", "per_page"):
        if kw.get(key) is None and link.get(key) is not None:
            kw[key] = link[key]
    profile_id = employer["id"]
    path = search_path(kw.get("keywords"), kw.get("location"), profile_id, link.get("employer_slug"))
    props, salaries = load_search(path, kw, label=f"employer {profile_id} jobs")
    results = props["searchResults"]
    rows = results.get("jobs") or []
    first = rows[0] if rows and isinstance(rows[0], dict) else {}
    cp = results.get("companyProfile") if isinstance(results.get("companyProfile"), dict) else {}
    heading = P.text(props.get("resultsHeading"))
    name = (P.text(cp.get("profileName")) or P.text(first.get("profileName"))
            or (re.sub(r"^[\d,]+\s+", "", heading).rsplit(" Jobs", 1)[0] if heading else None))
    body = search_block(props, salaries, kw)
    total = body["pagination"]["total_count"]
    if total == 0 and not rows and not name:
        raise ReedNotFound(f"employer profile {profile_id} has no listing on reed.co.uk")
    out = {
        "employer": {
            "profile_id": int(profile_id),
            "name": name,
            "link": refs.employer_jobs_link(profile_id, P.text(cp.get("profileUrl")) or P.text(first.get("profileUrl")) or link.get("employer_slug")),
            "logo": refs.logo_link(P.text(cp.get("logoImage")) or P.text(first.get("logoImage")), thumb=True),
            "banner": refs.logo_link(P.text(cp.get("bannerImage"))),
            "company_profile_id": P.to_int(cp.get("companyProfileId")),
            "company_profile_link": refs.company_profile_link(P.text(cp.get("companyProfileUrl"))) if P.text(cp.get("companyProfileUrl")) else None,
            "live_jobs_count": total,
        },
        "query": kw.get("keywords"),
    }
    out.update(body)
    return out


def profile(company):
    """A company profile page by company profile id or link."""
    status, html, _ = get_page(f"/company-profile/{company}", label=f"company profile {company}")
    if status != 200:
        raise ReedNotFound(f"company profile {company} not found")
    props = page_props(html, f"company profile {company}")
    record = P.company_profile(props.get("companyProfileDetails"))
    if not record:
        raise ReedNotFound(f"company profile {company} not found")
    return record
