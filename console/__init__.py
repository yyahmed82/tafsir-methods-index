"""مِرْقاة — committee console (لوحة لجنة الذكاء).

A local operator console for the tagging committee: who may log in, which
agent runs what, progress, daily reports and settings. It never writes tafsir
text: model output reaches ``data/<base>/moves`` and ``verified`` only through
``src/run_window.py`` (see AGENTS.md rules 1–3).
"""

__version__ = "0.1.0"
