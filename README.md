# Ocean Eddy Explorer

Numerical detection, tracking, and comparison of mesoscale ocean eddies along
the U.S. West Coast, with a Django interface and reproducible plotting scripts.
The three implemented detection methods are Chelton, Nencioli, and Halo.

## Reading the code

Follow the processing pipeline in this order:

1. **Load fields:** `method_website/explorer/datasets.py` discovers the daily
   NetCDF inputs; `methods.py` loads SLA and geostrophic velocity.
2. **Detect eddies:** `method_website/eddy_detection/` contains the three
   detectors. `method_utils.py` defines the common detection record and
   geographic boundary, area, and radius conversions.
3. **Associate observations:** `method_website/eddy_tracking/` contains each
   method's tracker and the separate shared tracking experiment.
4. **Run an analysis:** `scripts/plot_osu_assignment.py` runs the batch
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
| `scripts/export_comparison_presentation.py` | Slide PNGs using the paper's fixed axis windows. |
| `scripts/plot_welcome_fields.py` | Standalone Welcome field plots. |
| `tests/` and the application test modules | Numerical, plotting, and interface checks. |
| `docs/` | Additional workflow documentation. |
| `data/` | Local source datasets, excluded from source control. |
| `artifacts/` | Saved numerical results, figures, and local comparison jobs. |

## Run locally

Use Python 3.12 and run these commands from the project root:

```bash
python3.12 method_website/run.py --setup
python3.12 method_website/run.py
```

Open `http://127.0.0.1:8000/`. The Welcome page links to the reproduction
guide at `/reproduction/`. It documents data acquisition, exact numerical
settings, full-period runs, and checks against the saved results.
[The plotting notes](docs/osu_assignment_plots.md) describe the batch commands.

Use [the local/Kooplex deployment guide](docs/local_and_kooplex.md) for
configuration, data locations, proxy prefixes, and uploadable ZIP packages.
The website has a smaller pinned requirements file in `method_website/`;
the root requirements file retains the complete research environment.

## Verification

```bash
method_website/.venv/bin/python method_website/manage.py check
method_website/.venv/bin/python method_website/manage.py test config explorer eddy_detection --noinput
method_website/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Comparison cache keys include numerical source-file hashes. Source formatting
can therefore trigger fresh cached computations while keeping the numerical
rules unchanged. Saved CSVs and figures remain separate from those caches.

## Consistent formatting

Formatting tools are optional development dependencies and are not required
to start the website:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m black --line-length 88 method_website scripts tests
.venv/bin/python -m djlint method_website/explorer/templates --reformat --profile django --indent 4
npx --yes prettier@3.10.0 --tab-width 4 --print-width 88 --trailing-comma es5 --write "method_website/explorer/static/explorer/*.js"

for stylesheet in method_website/explorer/static/explorer/*.css; do
    .venv/bin/css-beautify --replace --indent-size 4 \
        --preserve-newlines --end-with-newline "$stylesheet"
done
```

Prettier's command needs Node.js/npm; the Python application does not.
Preserve import order, public names, numerical expressions, template
conditions, CSS rule order, and embedded reproduction commands during
readability work. Run the verification commands after changes.
