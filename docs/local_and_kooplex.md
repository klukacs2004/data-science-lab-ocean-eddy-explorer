# Local setup and deployment to Kooplex

The application can be configured and started on another machine. The detection,
tracking, and statistical computation functions remain unchanged.

## Quick local start

1. Extract the complete ZIP into a writable directory.
2. Open a terminal in the `ocean-eddy-explorer` project root.
3. Run the following commands using Python 3.12:

```bash
python3.12 method_website/run.py --setup
python3.12 method_website/run.py
```

Open **http://127.0.0.1:8000/**. Stop the server with **Ctrl+C**.
Run directly on Linux or macOS; use WSL on Windows.
If your interpreter is named `python3` or `python`, check its version and use
that command instead if it runs Python 3.12.

The `--setup` command prepares the application and then exits. It creates a
local virtual environment, installs the packages listed in
`method_website/requirements.txt`, creates a `.env` file with a generated secret
key, runs database migrations, collects static files, and checks the inputs.

If you already have a compatible Python environment with the dependencies installed:

```bash
python method_website/run.py --prepare
python method_website/run.py
```

The `--prepare` command does not install packages. The launcher uses the `.venv`
environment beside `run.py` if it exists; otherwise, it uses the current interpreter.

## Data and package variants

| Package | Contents |
| --- | --- |
| `method-website-none.zip` | Source code, setup launcher, documentation, and existing result files. No NetCDF inputs. |
| `method-website-demo.zip` | The same files plus the 1993 daily fields and the reference mean field. Can be built separately. |
| `method-website-all.zip` | The same files plus all available local annual NetCDF files and the reference mean field. |

The full package already includes the `data/` directory in the correct location;
you do not need to download or decompress the inputs again before starting.
For the source package, copy the daily `.nc` files into this directory, or set
the location of your existing data in `method_website/.env`:

```dotenv
SLA_DATA_DIR=/path/to/existing/netcdf/directory
```

If you have the original `osu_daily_sla_geovel_v2.tar` archive:

```bash
mkdir -p data
tar -xf data/osu_daily_sla_geovel_v2.tar -C data
gzip -dk data/osu_daily_sla_geovel_*_v2.nc.gz
```

The loader requires the annual v2 `.nc` files; it cannot read the TAR archive
or `.nc.gz` files directly. The Welcome reference map also needs the separate
`mean_aviso_field_1993_2012_v2.nc` file. Detection does not require this mean field.

```bash
method_website/.venv/bin/python method_website/manage.py checkdata
```

This check validates variable names, units, increasing coordinates, matching
spatial grids, and unique dates. It reports the number and range of available
dates. Documentation and methodology pages can be opened without data, but
computations require the input files.

## Preparing Kooplex

1. Upload and extract the complete project into a persistent Kooplex project
   directory. Create the virtual environment on the destination machine.
2. Choose an environment with Python 3.12. The interpreter name and available
   environment choices depend on your Kooplex installation.
3. For the first installation, copy the configuration template:

```bash
cp method_website/.env.kooplex.example method_website/.env
```

4. In `.env`, replace the example host `kooplex.example.org` with the actual
   hostname. Set `DJANGO_CSRF_TRUSTED_ORIGINS` to the full HTTPS origin.
   `DJANGO_ALLOWED_HOSTS` must contain hostnames only, without a scheme or path.
5. Set `SLA_DATA_DIR` if the data is stored on a shared volume. The `.runtime`
   directory and the database and tracking work directories must be writable
   and persistent.
6. Prepare and start the application:

```bash
python3.12 method_website/run.py --setup
python3.12 method_website/run.py --production
```

If the dependencies are already installed, use `--prepare` instead of `--setup`.
The launcher generates a missing secret key and preserves an existing key.
Keep the destination machine's configured `.env` file when updating the code.

7. Configure the Kooplex application or proxy to forward requests to the
   container's **port 8000**, or the port specified by `PORT`.
   Open the URL assigned by Kooplex in your browser.

The start command runs in the foreground. For a persistent service, configure
the Kooplex service manager to run it. Stopping the container also stops the web
and background processes. Tracking jobs and daily caches retained on a
persistent volume can be reused according to the existing queue rules.

## URL prefixes and proxies

For example, if the public URL is
`https://kooplex.example.org/reports/ocean-eddies/` and the proxy removes
`/reports/ocean-eddies` before forwarding requests to Django, use:

```dotenv
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,kooplex.example.org
DJANGO_CSRF_TRUSTED_ORIGINS=https://kooplex.example.org
DJANGO_FORCE_SCRIPT_NAME=/reports/ocean-eddies
DJANGO_TRUST_PROXY=true
DJANGO_SECURE_COOKIES=true
```

Use the URL and proxy configuration supplied by your platform to determine the
actual prefix; the path above is an **example**. Leave the prefix empty if the
application is published at the URL root. Setting `DJANGO_TRUST_PROXY=true`
assumes that the trusted proxy sets the `X-Forwarded-Proto` header itself.

With Jupyter Server Proxy, the usual route is `proxy/8000/` beneath the
notebook's base URL. Its documentation states that the proxy removes the
proxy path prefix by default. Apply this pattern on Kooplex only if your
environment uses this proxy type.

Generated navigation links, static CSS/JavaScript URLs, date queries, and
tracking status URLs include the configured prefix. WhiteNoise serves static
files with `DEBUG=false` as well, without requiring a separate nginx server.

## Main settings

| Variable | Purpose |
| --- | --- |
| `DJANGO_DEBUG` | `true` locally; `false` on Kooplex. |
| `DJANGO_SECRET_KEY` | A separate key for each installation; generated by the launcher if empty. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated list of accepted hostnames. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Trusted HTTPS origins for POST requests behind the proxy. |
| `DJANGO_FORCE_SCRIPT_NAME` | Public URL path prefix removed by the proxy. |
| `SLA_DATA_DIR` | Directory containing the daily NetCDF inputs. |
| `DJANGO_RUNTIME_DIR` | Writable directory for runtime and collected static files. |
| `DJANGO_DATABASE_PATH` | SQLite database file; no separate database server is required. |
| `COMPARISON_WORK_DIR` | Directory for existing background jobs and daily detection checkpoints. |
| `COMPARISON_AUTOSTART` | Enables the existing automatic background worker. |
| `BIND_HOST`, `PORT` | `127.0.0.1:8000` locally; `0.0.0.0:8000` in the Kooplex template. |
| `WEB_TIMEOUT` | Timeout for synchronous web requests in seconds; defaults to 1200. |

External environment variables take precedence over values in `.env`.
Relative file paths are resolved against the `method_website/` directory.
The launcher does not change detection thresholds, tracking parameters, or
statistical definitions.

## Verification

```bash
python3.12 method_website/run.py --check
method_website/.venv/bin/python method_website/manage.py test config explorer eddy_detection --noinput
method_website/.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

The `/health/` endpoint returns `{"status": "ok"}`. When using a URL prefix,
access this endpoint beneath the public prefix. Check the input data separately
with the `checkdata` command.

Installation requires an internet connection. Browser basemaps and MathJax
equation rendering also use external services. Numerical computations run on
the local NetCDF files.

## Building a new upload package

```bash
python3.12 scripts/package_method_website.py --data none
python3.12 scripts/package_method_website.py --data all
```

The ZIP files are written to `dist/`. The packager excludes local `.env` files,
virtual environments, databases, authentication and agent state, and queue caches.
Each package includes a `PACKAGE_MANIFEST.json` file with SHA-256 hashes of its
members. A separate `.sha256` checksum file is also created beside the ZIP.
The package does not upload itself or change Kooplex access settings.

## References

- [Kooplex: official project website](https://kooplex.github.io/)
- [Django: FORCE_SCRIPT_NAME and related settings](https://docs.djangoproject.com/en/5.2/ref/settings/#force-script-name)
- [Jupyter Server Proxy: proxy paths](https://jupyter-server-proxy.readthedocs.io/en/latest/server-process.html)
- [WhiteNoise: Django integration](https://whitenoise.readthedocs.io/en/stable/django.html)
