# Job Scraper Service

A FastAPI-based job scraping service that searches for jobs across multiple portals using Playwright and collects structured job metadata, including title, company, location, description, URL, and portal source.

## Overview

This project scrapes job listings from:

- Indeed
- LinkedIn
- Wellfound
- Naukri

It runs a headless Chromium browser to search for roles, extract job cards, deduplicate results, cap per-portal counts, and optionally fetch full job descriptions from the job detail pages.

## Features

- Multi-portal scraping in one request
- Remote-friendly search option
- Duplicate removal and portal limit enforcement
- Job description extraction from listing detail pages
- Health check endpoint
- FastAPI JSON responses for easy integration with frontends or automation workflows

## Project structure

```text
job-scraper-service/
├── app.py
├── requirements.txt
├── start.bat
├── start.sh
├── README.md
├── __init__.py
├── scrapers/
│   ├── __init__.py
│   ├── base.py
│   ├── browser.py
│   ├── indeed.py
│   ├── linkedin.py
│   ├── naukri.py
│   └── wellfound.py
└── venv/                  # created locally when you run startup scripts
```

## Requirements

- Python 3.10+
- Playwright Chromium browser
- Internet access for scraping job portals

## Quick start

### Windows

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
uvicorn app:app --host 0.0.0.0 --port 5002 --reload
```

You can also use the bundled script:

```powershell
start.bat
```

### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app:app --host 0.0.0.0 --port 5002 --reload
```

You can also use:

```bash
bash start.sh
```

## API

The service runs at:

```text
http://localhost:5002
```

### Health check

```http
GET /health
```

Example response:

```json
{
  "status": "ok"
}
```

### Scrape all portals

```http
POST /scrape
```

Request body:

```json
{
  "queries": ["software-engineer", "backend-engineer", "ai-engineer"],
  "location": "India",
  "remote": true
}
```

Example response:

```json
{
  "success": true,
  "count": 60,
  "jobs": [
    {
      "title": "Senior Software Engineer",
      "company": "Example Corp",
      "location": "Remote",
      "description": "...",
      "url": "https://...",
      "salary": "Not mentioned",
      "portal": "LinkedIn",
      "posted_at": "",
      "job_id": "123456789",
      "company_url": "",
      "apply_url": "https://...",
      "skills": ""
    }
  ],
  "errors": []
}
```

### Scrape a single portal

```http
POST /scrape-indeed
```

Same request body as above.

### Fetch a job description by URL

```http
POST /job-description
```

Request body:

```json
{
  "url": "https://example.com/job/123",
  "portal": "Indeed"
}
```

## Notes

- This scraper depends on the structure of public job listings and may need updates if a portal changes its HTML or protection mechanisms.
- The project is designed for personal or internal automation and not as a production-grade crawler for all websites.
- Some portals may rate-limit or block browser automation; the code includes basic selectors, retries, and portal-level limits to reduce failures.
- The default results are limited to a reasonable total and capped per portal to avoid overwhelming output.

## Recommended usage

This service is ideal for:

- collecting jobs for research or advisement
- building a local jobs dashboard
- feeding structured job data into another app or workflow


## Disclaimer

Please comply with the terms of service of each job portal when scraping, and avoid aggressive crawling or excessive request volume.
