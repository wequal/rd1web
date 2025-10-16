"""
Management command to populate RMA statistics from existing directories
"""

from django.core.management.base import BaseCommand
from pxe.rma_statistics import scan_all_rma_directories
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Scan all RMA directories and populate statistics database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show verbose output',
        )

    def handle(self, *args, **options):
        verbose = options['verbose']
        
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write(self.style.SUCCESS('RMA Statistics Population'))
        self.stdout.write(self.style.SUCCESS('=' * 60))
        self.stdout.write('')
        
        self.stdout.write('Scanning RMA directories...')
        self.stdout.write('This may take a few minutes depending on the number of directories.')
        self.stdout.write('')
        
        # Run the scan
        stats = scan_all_rma_directories()
        
        # Display results
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('Scan Complete!'))
        self.stdout.write('')
        self.stdout.write(f"Total directories found:     {stats['total']}")
        self.stdout.write(f"Successfully processed:      {self.style.SUCCESS(str(stats['processed']))}")
        self.stdout.write(f"Skipped (no changes):        {stats['skipped']}")
        self.stdout.write(f"Errors:                      {self.style.ERROR(str(stats['errors']))}")
        
        if verbose and stats['error_messages']:
            self.stdout.write('')
            self.stdout.write(self.style.WARNING('Error Messages:'))
            for msg in stats['error_messages'][:10]:  # Show first 10 errors
                self.stdout.write(f"  - {msg}")
            if len(stats['error_messages']) > 10:
                self.stdout.write(f"  ... and {len(stats['error_messages']) - 10} more errors")
        
        self.stdout.write('')
        
        if stats['errors'] > 0:
            self.stdout.write(self.style.WARNING(
                f"Completed with {stats['errors']} errors. Run with --verbose to see details."
            ))
        else:
            self.stdout.write(self.style.SUCCESS('All directories processed successfully!'))
        
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=' * 60))

