"""/reed/salary/benchmark — the site's average salary checker: the average,
low and high advertised annual pay for a job title (optionally in a place),
with the live job counts behind it.

The page is /average-salary/average-{title}-salary[-in-{place}]; a title the
site has no live adverts for renders the empty checker form.
"""
import re

from reed import parsers as P
from reed.fetch import ReedNotFound, get_html


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def benchmark(job_title, location=None):
    slug = f"average-{_slug(job_title)}-salary"
    if location:
        slug += f"-in-{_slug(location)}"
    html = get_html(f"/average-salary/{slug}", label="salary benchmark")
    record = P.salary_page(html, job_title, location)
    if not record or record.get("average") is None:
        where = f" in {location}" if location else ""
        raise ReedNotFound(f"no salary data for '{job_title}'{where}: the site has no live adverts with that title")
    return record
