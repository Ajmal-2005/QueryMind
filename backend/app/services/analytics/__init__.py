"""Result analytics: profiling, chart selection, outliers, trends, narrative.

Everything here reads a result set and says something about it. Nothing here
touches a database, and only `narrative` touches a network - which is why the
LLM-free parts run inline in the query pipeline and the narrative does not.
"""

from app.services.analytics.analyze import Analysis, analyze
from app.services.analytics.charts import ChartSpec, ChartType
from app.services.analytics.export import ExportFormat, ReportContext, render
from app.services.analytics.masking import MaskingReport, mask_rows
from app.services.analytics.narrative import Narrative, narrate
from app.services.analytics.outliers import OutlierReport
from app.services.analytics.profile import ColumnKind, ColumnProfile, ResultProfile
from app.services.analytics.trends import Trend, TrendResult

__all__ = [
    "Analysis",
    "ChartSpec",
    "ChartType",
    "ColumnKind",
    "ColumnProfile",
    "ExportFormat",
    "MaskingReport",
    "Narrative",
    "OutlierReport",
    "ReportContext",
    "ResultProfile",
    "Trend",
    "TrendResult",
    "analyze",
    "mask_rows",
    "narrate",
    "render",
]
