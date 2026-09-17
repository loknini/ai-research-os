"""SQLite persistence package.

The public compatibility surface remains :mod:`scripts.database`.  Internal
connection, migration and repository modules live here so they can evolve
without forcing a flag-day import change across the application.
"""
