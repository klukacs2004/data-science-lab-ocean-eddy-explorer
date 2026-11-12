# Run Ocean Eddy Explorer locally or on Kooplex

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

The data-inclusive ZIP already contains the annual NetCDF files and the Welcome
reference field in the project's `data/` directory. The source-only ZIP does
not contain NetCDF inputs; copy them into `data/` or set `SLA_DATA_DIR` in
`method_website/.env` to your existing directory. Relative paths in `.env`
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

## Kooplex

Copy the complete extracted project into a persistent Kooplex project directory,
choose a Python 3.12 environment, and run the setup command there. Use the
Kooplex configuration template before the final preparation/start:

```bash
cp method_website/.env.kooplex.example method_website/.env
# Edit the hostname, HTTPS origin, optional URL prefix, and data/state paths.
python3.12 method_website/run.py --setup
python3.12 method_website/run.py --production
```

The launcher generates the empty secret automatically. If setup has already
been completed, use `--prepare` instead of `--setup`; it does not reinstall
packages. Do not overwrite an existing configured `.env` when updating code.

The Kooplex service must forward to the configured port (8000 by default).
Use the published URL supplied by your Kooplex instance. Its exact hostname
and proxy path depend on that installation. Set `DJANGO_FORCE_SCRIPT_NAME` to
the path component when the upstream proxy strips it before forwarding.
See [the detailed local/Kooplex guide](../docs/local_and_kooplex.md) for examples,
configuration variables, input preparation, and verification.

## Start options

```bash
python3.12 method_website/run.py --host 127.0.0.1 --port 8080
python3.12 method_website/run.py --production --host 0.0.0.0 --port 8000
python3.12 method_website/run.py --production --prefix /reports/ocean-eddies
```

Serving uses one synchronous Gunicorn worker so plotting and NetCDF operations
remain serialized inside the web worker. Tracking comparisons retain their
existing separate background process and persistent checkpoints. The request
timeout defaults to 1200 seconds and can be changed with `WEB_TIMEOUT`.

`/health/` returns a small JSON readiness response, including when no NetCDF
files are installed. It does not assert that scientific inputs are present.
Static CSS/JavaScript is served by WhiteNoise with debug mode disabled as well.

Keep `.env`, `.venv`, SQLite, `.runtime`, and comparison caches on the destination
machine; distribute source and data instead of copying an old virtual
environment. Runtime settings do not change the detection or tracking rules.
