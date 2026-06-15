"""
Cache monitoring API views for admin dashboard.

Provides aggregated cache statistics and recent LLM call records.
"""
import logging

from django.http import JsonResponse, HttpRequest
from django.views import View

from ...services.cache_stats_service import CacheStatsService

logger = logging.getLogger(__name__)


class CacheStatsOverviewView(View):
    """Return aggregated cache statistics for the admin dashboard.

    GET /chatbot/api/admin/cache-stats/overview/?days=7

    Query params:
        days (int): Number of days to look back (default: 7)
    """

    async def get(self, request: HttpRequest) -> JsonResponse:
        days_str = request.GET.get('days', '7')
        try:
            days = max(1, min(365, int(days_str)))
        except (ValueError, TypeError):
            days = 7

        service = CacheStatsService()
        overview = await service.get_overview(days=days)

        return JsonResponse({
            'total_calls': overview.total_calls,
            'total_prompt_tokens': overview.total_prompt_tokens,
            'total_completion_tokens': overview.total_completion_tokens,
            'total_cached_tokens': overview.total_cached_tokens,
            'overall_cache_hit_rate': overview.overall_cache_hit_rate,
            'estimated_cost_savings': overview.estimated_cost_savings,
            'total_duration_ms': overview.total_duration_ms,
            'model_breakdown': overview.model_breakdown,
            'daily_stats': overview.daily_stats,
            'today_stats': overview.today_stats,
        })


class CacheStatsRecentView(View):
    """Return recent LLM call records.

    GET /chatbot/api/admin/cache-stats/recent/?limit=20

    Query params:
        limit (int): Number of records to return (default: 20, max: 100)
    """

    async def get(self, request: HttpRequest) -> JsonResponse:
        limit_str = request.GET.get('limit', '20')
        try:
            limit = max(1, min(100, int(limit_str)))
        except (ValueError, TypeError):
            limit = 20

        service = CacheStatsService()
        records = await service.get_recent_calls(limit=limit)

        # Convert datetimes to strings
        for r in records:
            if 'gmt_create' in r and r['gmt_create']:
                r['gmt_create'] = r['gmt_create'].isoformat()

        return JsonResponse({'records': records})
