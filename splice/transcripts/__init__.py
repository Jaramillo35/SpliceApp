"""Meeting transcript capture from Teams Live Captions (Windows only).

The recorder scrapes the Teams Live Captions window through Windows UI
Automation and writes anonymized markdown transcripts: participant names are
replaced with stable "Speaker N" aliases so a transcript can be fed to an LLM
for minutes without disclosing who attended.
"""
