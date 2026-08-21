"""Shared, business-rule-free helpers used across every functional area.

This is the leaf layer of the dependency graph: modules here import only the
standard library and third-party packages (pandas, openpyxl), never other
``secrdb.core`` sub-packages. Everything else may safely depend on it.
"""
