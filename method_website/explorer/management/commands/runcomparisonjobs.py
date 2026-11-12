from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Process persistent comparison jobs, then exit when the queue is empty."

    def add_arguments(self, parser):
        parser.add_argument("--work-dir", type=Path)

    def handle(self, *args, **options):
        if options["work_dir"]:
            settings.COMPARISON_WORK_DIR = options["work_dir"]
        from explorer.comparison_jobs import work_queue

        work_queue()
