"""Cache TTL per /reed/* endpoint (cache.py, keyed on the validated params).

Tiers follow how fast the site moves each surface: adverts are posted every
minute and search totals shift with them, a job record changes only when
the recruiter edits or refreshes it, company profiles and the course
catalogue change a few times a day, reference lists a few times a year.
"""
from datetime import timedelta

# --- jobs --------------------------------------------------------------------
SEARCH_CACHE = timedelta(minutes=10)
FACETS_CACHE = timedelta(minutes=30)
JOB_CACHE = timedelta(hours=1)
BATCH_CACHE = timedelta(hours=1)
SIMILAR_CACHE = timedelta(hours=1)

# --- employers ---------------------------------------------------------------
DIRECTORY_CACHE = timedelta(hours=6)
EMPLOYER_JOBS_CACHE = timedelta(minutes=15)
COMPANY_CACHE = timedelta(hours=6)

# --- salary / reference ------------------------------------------------------
SALARY_CACHE = timedelta(hours=12)
SUGGEST_CACHE = timedelta(days=1)
SECTORS_CACHE = timedelta(hours=6)

# --- courses -----------------------------------------------------------------
COURSE_SEARCH_CACHE = timedelta(hours=1)
COURSE_CACHE = timedelta(hours=6)
REVIEWS_CACHE = timedelta(hours=6)
PROVIDERS_CACHE = timedelta(days=1)
PROVIDER_CACHE = timedelta(days=1)
