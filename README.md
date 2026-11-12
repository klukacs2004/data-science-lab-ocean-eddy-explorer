# Ocean Eddy Explorer

Numerical detection, tracking, and comparison of mesoscale ocean eddies along
the U.S. West Coast, with a Django interface and reproducible plotting scripts.
The three implemented detection methods are Chelton, Nencioli, and Halo.

## Installation

The application can be downloaded and run locally. Python and Git must be installed on your computer.

### Clone the repository

```bash
git clone https://github.com/USERNAME/REPOSITORY.git
cd REPOSITORY
```
##  Prepare the dataset

Download the required OSU NetCDF dataset (22 individual NetCDF files have been added to a single TAR file) from https://ir.library.oregonstate.edu/concern/datasets/fn107383f?locale=en and place the files in the data directory configured by the application or set `SLA_DATA_DIR` in
`method_website/.env` to your existing directory.

Ensure that the application can access the dataset before starting the server.

## Run locally

Use **Python 3.12** on Linux, macOS, or Windows through **WSL**. The numerical
dependencies have the same versions as the saved analysis. No Node.js or
external database server is required.

From the extracted project root:

```bash
python3.12 method_website/run.py --setup
python3.12 method_website/run.py
```

The first command creates a local `method_website/.venv`, installs the web
application dependencies, creates a private `.env` with a generated secret,
prepares SQLite, and collects static files. The second starts the application
at **http://127.0.0.1:8000/**. Stop it with Ctrl+C.

If your Python command is named `python3`, check `python3 --version` and use it
instead when it reports Python 3.12. An already activated compatible environment
can run `python method_website/run.py --prepare` without creating another venv.

## Input data

  Relative paths in `.env`
are resolved against **method_website/**, independent of the terminal's current
directory. Leave `SLA_DATA_DIR` empty to discover the usual `../data/` or `./data/`.

The website can show its documentation without daily inputs. Detection and
tracking need decompressed `osu_daily_sla_geovel_YYYY_v2.nc` files.

```bash
method_website/.venv/bin/python method_website/manage.py checkdata
python3.12 method_website/run.py --check
```

The first command requires data. The second also permits an installation with
no data, reporting how to add it.


## Reading the code

Follow the processing pipeline in this order:

1. **Load fields:** `method_website/explorer/datasets.py` discovers the daily
   NetCDF inputs; `methods.py` loads SLA and geostrophic velocity.
2. **Detect eddies:** `method_website/eddy_detection/` contains the three
   detectors. `method_utils.py` defines the common detection record and
   geographic boundary, area, and radius conversions.
3. **Associate observations:** `method_website/eddy_tracking/` contains each
   method's tracker and the separate shared tracking experiment.
4. **Run an analysis:** `scripts/plot_osu.py` runs the batch
   experiment and builds the numerical tables for Figures 7 and 8.
5. **Explore interactively:** `method_website/explorer/` connects forms,
   daily detection, tracking runners, diagnostics, and plots to Django views.

| Directory or module | Responsibility |
| --- | --- |
| `method_website/config/` | Django settings, root URLs, and server entry points. |
| `method_website/explorer/urls.py` | Named application routes. |
| `method_website/explorer/views.py` | Welcome, methodology, reproduction, detection, tracking, and comparison pages. |
| `method_website/explorer/forms.py` | Input controls, defaults, and validation. |
| `method_website/explorer/*_diagnostics.py` | Candidate explanations and diagnostic/export tables. |
| `method_website/explorer/plots/` | Matplotlib diagnostics, Plotly figures, and common plot styling. |
| `method_website/explorer/templates/` | Django page layouts and method-specific content. |
| `method_website/explorer/static/explorer/` | Browser interactions and styles. |
| `method_website/explorer/comparison_jobs.py` | Persistent background comparison queue. |
| `method_website/explorer/comparison_cache.py` | Daily detection storage and cache keys. |
| `data/` | Local source datasets, excluded from source control. |
| `artifacts/` | Saved numerical results, figures, and local comparison jobs. |


Open `http://127.0.0.1:8000/`. The Welcome page links to the reproduction
guide at `/reproduction/`. It documents data acquisition, exact numerical
settings, full-period runs, and checks against the saved results.

## Verification

```bash
method_website/.venv/bin/python method_website/manage.py check
method_website/.venv/bin/python method_website/manage.py test config explorer eddy_detection --noinput
```

Comparison cache keys include numerical source-file hashes. Source formatting
can therefore trigger fresh cached computations while keeping the numerical
rules unchanged. Saved CSVs and figures remain separate from those caches.

## Notes

- The application is intended for local development and scientific demonstration.
- The Django development server is not intended for production deployment.
- Large-scale eddy detection and tracking computations may require significant memory and processing time.
