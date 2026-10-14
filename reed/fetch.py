"""Reed.co.uk transport: plain curl_cffi with browser-impersonated TLS. No
browser, no login, no token (validated 2026-10-14 from direct Indian egress:
every surface below answered 200 on the first try; Cloudflare sits in front
without a challenge for Chrome TLS, only its analytics beacon is present).

Upstream surfaces (all on https://www.reed.co.uk):

  * JOBS (Next.js app "web-jobseeker-jobs")
      /jobs/{slug}?...                  search / sector / employer listing pages.
        The page's __NEXT_DATA__ carries pageProps.searchResults (count, 25..100
        job rows as JSON, promoted rows, facets, similar searches, location
        substitutes) + pageProps.criteria (the normalised query) + the filter
        option lists. `take=N` (1..100) sets the page size, `pageno` the page.
        An employer listing is /jobs/{name}/p{profile_id} (same template).
      /jobs/{slug}/{job_id}             job page: pageProps.consolidatedJobDetails
        (jobDetails in full, similarJobs, similarSearches, recommendedCourses).
        An expired or unknown id answers HTTP 410 with notFoundReason JOB_EXPIRED.
      /company-profile/{Name}-{id}      pageProps.companyProfileDetails (404 when unknown).
      /api/location/getlocationsukonlyautocomplete?term=   JSON list of places
      /api/search/getjobtaxonomyautocomplete?term=         JSON list of job titles
  * RECRUITER DIRECTORY (server-rendered)
      /recruiterdirectory[/agencies|/direct][/{specialism}][/{location}]?keywords=&pageno=
  * SALARY (server-rendered)
      /average-salary/average-{title}-salary[-in-{place}]
  * REED COURSES (server-rendered ASP.NET + Vue islands; every page hands its
    Vue app a JSON blob through `m.init({...})` in an inline module script)
      /courses/all?keywords=&location=&... or /courses/{subject}?...   search
      /courses/{slug}/{course_id}       course page (init blob: Q&A, classrooms, GA item)
      /courses/coursereview/providercoursereviews?providerId=&courseId=&page=&pageSize=&sortBy=
      /courses/provider-profiles/search?searchText=&page=&pageSize=
      /courses/provider-profiles/{slug}  provider profile page
      /courses/{slug}/p{provider_id}     provider course listing
      /courses/api/location/autocomplete?term=

Blocks: none seen. Defensive handling only — a 403 / 429, or HTML where JSON
is expected, sends the worker's new sessions through a sticky residential GB
exit (config.reed_fallback_proxy()) for config.REED_BLOCK_COOLDOWN seconds,
the same shape as the vinted / woolworths transports.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  ReedUpstreamError  transport failure / 5xx            — retryable
  ReedBlocked        403 / 429 / challenge page         — retryable on a new exit
  ReedBadRequest     upstream 400                       — never retried
  ReedNotFound       404 / 410 / missing entity         — never retried
"""
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

SITE = "https://www.reed.co.uk"
IMPERSONATE = "chrome"
TIMEOUT = 60
FANOUT_WORKERS = 12

PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-GB,en;q=0.9",
    "upgrade-insecure-requests": "1",
}
JSON_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "en-GB,en;q=0.9",
    "x-requested-with": "XMLHttpRequest",
    "referer": SITE + "/",
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_INIT_RE = re.compile(r"import\('(/courses/resources/js-build/([a-z.-]+)\.js[^']*)'\)\.then\(function\(m\) "
                      r"\{ if \(m\.init\) \{ m\.init\((\{.*?\})\); \} \}\);", re.S)
_CHALLENGE_RE = re.compile(r"cf-mitigated|_cf_chl_opt|Just a moment|Access Denied|Pardon Our Interruption", re.I)


class ReedUpstreamError(UpstreamError):
    """Transport failure or 5xx — retryable."""


class ReedBlocked(ReedUpstreamError, Blocked):
    """403 / 429 or a challenge page — retryable on a fresh exit."""


class ReedBadRequest(BadRequest):
    """Upstream 400 — the params were rejected. Never retried."""


class ReedNotFound(NotFound):
    """Entity / page does not exist (404, 410, JOB_EXPIRED) — never retried."""


# ---- sessions ------------------------------------------------------------------
# One curl session per worker thread. Direct egress by default; after a block
# the thread's new sessions go through a sticky residential exit for a while.
_local = threading.local()
_fallback_until = 0.0
_fallback_lock = threading.Lock()


def _proxy_for_new_session():
    forced = config.reed_proxy()
    if forced:
        return forced
    if time.time() < _fallback_until:
        return config.reed_fallback_proxy()
    return None


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for_new_session()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        _local.session = sess
    return sess


def _drop_session():
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _note_block():
    global _fallback_until
    if config.reed_fallback_proxy() is not None:
        with _fallback_lock:
            _fallback_until = time.time() + config.REED_BLOCK_COOLDOWN


def dump_debug(name, text):
    dbg = os.environ.get("REED_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(text)
        except OSError:
            pass


# ---- requests --------------------------------------------------------------------

def _retrying(fn):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except ReedUpstreamError as e:          # includes ReedBlocked
            last = e
            _drop_session()
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def clean_params(params):
    """Drop None / empty values; lists become comma strings; booleans become
    the site's lower-case `true` (a false flag is simply not sent)."""
    query = {}
    for key, value in (params or {}).items():
        if value is None or value == "" or value == [] or value is False:
            continue
        if value is True:
            value = "true"
        elif isinstance(value, (list, tuple)):
            value = ",".join(str(v) for v in value)
        query[key] = value
    return query


def _url(path):
    return path if path.startswith("http") else SITE + path


def get_page(path, params=None, *, label=None, not_found_status=(404, 410)):
    """GET one HTML page. 404 / 410 raise ReedNotFound; 403 / 429 and
    challenge pages are blocks; anything else non-200 is upstream."""
    label = label or path
    query = clean_params(params)

    def once():
        sess = _session()
        try:
            resp = sess.get(_url(path), params=query, headers=PAGE_HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except Exception as e:
            raise ReedUpstreamError(f"request failed: {type(e).__name__}: {e}")
        finally:
            sess.cookies.clear()
        status = resp.status_code
        body = resp.text or ""
        if status in not_found_status:
            # a Next.js 404/410 still carries __NEXT_DATA__; callers read the reason
            return status, body, str(resp.url)
        if status in (403, 429) or (status == 200 and _CHALLENGE_RE.search(body[:4000])):
            dump_debug("blocked", body)
            _note_block()
            raise ReedBlocked(f"HTTP {status} on {label}")
        if status == 400:
            raise ReedBadRequest(f"upstream rejected {label}")
        if status != 200:
            raise ReedUpstreamError(f"HTTP {status} on {label}")
        if not body.strip():
            raise ReedUpstreamError(f"empty body on {label}")
        return status, body, str(resp.url)

    return _retrying(once)


def get_html(path, params=None, *, label=None):
    """GET one HTML page that must exist (404 / 410 -> ReedNotFound)."""
    label = label or path
    status, body, _ = get_page(path, params, label=label)
    if status != 200:
        raise ReedNotFound(f"{label} not found")
    return body


def get_json(path, params=None, *, label=None, referer=None):
    """GET one JSON route. HTML where JSON is expected is a block."""
    label = label or path
    query = clean_params(params)
    headers = dict(JSON_HEADERS)
    if referer:
        headers["referer"] = referer

    def once():
        sess = _session()
        try:
            resp = sess.get(_url(path), params=query, headers=headers, timeout=TIMEOUT, allow_redirects=True)
        except Exception as e:
            raise ReedUpstreamError(f"request failed: {type(e).__name__}: {e}")
        finally:
            sess.cookies.clear()
        status = resp.status_code
        body = resp.text or ""
        if status == 404:
            raise ReedNotFound(f"{label} not found")
        if status in (403, 429):
            dump_debug("blocked", body)
            _note_block()
            raise ReedBlocked(f"HTTP {status} on {label}")
        if status == 400:
            raise ReedBadRequest(f"upstream rejected {label}")
        if status == 204 or not body.strip():
            return None
        if status != 200:
            raise ReedUpstreamError(f"HTTP {status} on {label}")
        if not body.lstrip().startswith(("{", "[")):
            dump_debug("nonjson", body)
            raise ReedBlocked(f"{label} returned HTML, not JSON")
        try:
            return resp.json()
        except Exception:
            dump_debug("badjson", body)
            raise ReedUpstreamError(f"could not parse JSON from {label}")

    return _retrying(once)


# ---- embedded data ---------------------------------------------------------------

def next_data(html):
    """The Next.js __NEXT_DATA__ object of a jobs page (None when absent)."""
    match = _NEXT_DATA_RE.search(html or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def page_props(html, label="page"):
    data = next_data(html)
    props = (data or {}).get("props", {}).get("pageProps") if isinstance(data, dict) else None
    if not isinstance(props, dict):
        dump_debug("no_next_data", html)
        raise ReedUpstreamError(f"{label} carried no page data (layout changed?)")
    return props


def init_blobs(html):
    """{bundle name: init payload} of a Reed Courses page, e.g.
    'course-view.view', 'course-search.index', 'provider-profile.details'."""
    out = {}
    for match in _INIT_RE.finditer(html or ""):
        try:
            out[match.group(2)] = json.loads(match.group(3))
        except json.JSONDecodeError:
            continue
    return out


# ---- fan-out ------------------------------------------------------------------------
_pool = ThreadPoolExecutor(max_workers=FANOUT_WORKERS, thread_name_prefix="reed")


def run_parallel(fns):
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    futures = [_pool.submit(fn) for fn in fns]
    return [f.result() for f in futures]


def gather(mapping, optional=()):
    """{key: callable} in parallel -> {key: result}. Keys named in
    `optional` yield None instead of failing the set when they raise any
    scraper error (an enrichment must not sink the endpoint)."""
    keys = list(mapping)

    def guarded(key):
        fn = mapping[key]
        if key not in optional:
            return fn

        def run():
            try:
                return fn()
            except (UpstreamError, BadRequest, NotFound):
                return None
        return run

    results = run_parallel([guarded(k) for k in keys])
    return dict(zip(keys, results))


if __name__ == "__main__":
    # Smoke test: python reed/fetch.py [keywords] [location]
    kw = sys.argv[1] if len(sys.argv) > 1 else "python developer"
    loc = sys.argv[2] if len(sys.argv) > 2 else "london"
    props = page_props(get_html("/jobs", {"keywords": kw, "location": loc, "take": 3}))
    results = props["searchResults"]
    print("search:", results["count"], [(j["jobDetail"]["jobId"], j["jobDetail"]["jobTitle"]) for j in results["jobs"]])
    job_id = results["jobs"][0]["jobDetail"]["jobId"]
    job = page_props(get_html(f"/jobs/x/{job_id}"))["consolidatedJobDetails"]["jobDetails"]
    print("job:", job["id"], job["title"], job["jobSalary"]["displaySalary"])
    print("places:", get_json("/api/location/getlocationsukonlyautocomplete", {"term": "lee"})[:3])
