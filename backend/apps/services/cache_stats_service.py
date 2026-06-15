"""
Cache statistics service for monitoring LLM token usage and cache hit rates.

Tracks per-LLM-call token usage data and provides aggregated statistics
for the cache monitoring dashboard.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from django.db.models import Avg, FloatField, Sum, Count
from django.db.models.functions import Cast

from asgiref.sync import sync_to_async

from ..entities.token_usage import TokenUsage
from ..tenant.context import get_current_tenant_id

logger = logging.getLogger(__name__)


@dataclass
class CacheStatsOverview:
    """Aggregated cache statistics for the dashboard overview."""
    total_calls: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    overall_cache_hit_rate: float = 0.0
    estimated_cost_savings: float = 0.0  # USD
    total_duration_ms: float = 0.0
    model_breakdown: List[Dict[str, Any]] = field(default_factory=list)
    daily_stats: List[Dict[str, Any]] = field(default_factory=list)
    today_stats: Dict[str, Any] = field(default_factory=dict)


# Cost per 1K tokens (approximate, for estimation)
# These are rough estimates - actual costs depend on provider/pricing
COST_PER_1K_PROMPT_TOKENS = 0.003  # $0.003/1K prompt tokens (GPT-4o mini range)
COST_PER_1K_CACHED_SAVED = 0.0025  # ~85% of prompt cost saved when cached


class CacheStatsService:
    """Service for recording and aggregating LLM token usage statistics."""

    def __init__(self):
        pass

    @staticmethod
    def _tenant_id() -> str:
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            raise ValueError("tenant_id not set in request context")
        return tenant_id

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    @sync_to_async(thread_sensitive=False)
    def record_llm_call(
        self,
        session_id: str,
        user_id: str = '',
        llm_provider: str = '',
        model_name: str = '',
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cached_tokens: int = 0,
        duration_ms: float = 0.0,
        ttft_ms: float = 0.0,
        chunk_count: int = 0,
        tpot_ms: float = 0.0,
        finish_reason: str = '',
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TokenUsage:
        """Record a single LLM call's token usage.

        Args:
            session_id: Chat session ID
            user_id: User identifier
            llm_provider: Provider name (e.g., 'openai', 'ucloud')
            model_name: Model name (e.g., 'gpt-4', 'qwen3-32b')
            prompt_tokens: Prompt token count
            completion_tokens: Completion token count
            cached_tokens: Cached (KV cache hit) token count
            duration_ms: Call duration in milliseconds
            ttft_ms: Time to first token in milliseconds
            chunk_count: Number of content chunks received
            tpot_ms: Average time per output token in milliseconds
            finish_reason: Why the call finished
            metadata: Additional metadata dict

        Returns:
            The created TokenUsage record
        """
        total_tokens = prompt_tokens + completion_tokens
        cache_hit_rate = (cached_tokens / prompt_tokens * 1.0
                          if prompt_tokens > 0 else 0.0)

        record = TokenUsage.objects.create(
            tenant_id=self._tenant_id(),
            session_id=session_id,
            user_id=user_id,
            llm_provider=llm_provider,
            model_name=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            total_tokens=total_tokens,
            cache_hit_rate=cache_hit_rate,
            duration_ms=duration_ms,
            ttft_ms=ttft_ms,
            chunk_count=chunk_count,
            tpot_ms=tpot_ms,
            finish_reason=finish_reason,
            metadata=metadata or {},
        )

        logger.info(
            "[CacheStats] recorded: model=%s provider=%s "
            "prompt=%d cached=%d hit_rate=%.1f%% duration=%.0fms",
            model_name, llm_provider,
            prompt_tokens, cached_tokens,
            cache_hit_rate * 100, duration_ms,
        )

        return record

    @sync_to_async(thread_sensitive=False)
    def record_from_context(
        self,
        session_id: str,
        user_id: str,
        context,
        model_name: str = '',
        llm_provider: str = '',
    ) -> List[TokenUsage]:
        """Record token usage from an AgentContext's trace data.

        Parses the trace for ``llm_end`` entries and creates a
        ``TokenUsage`` record for each.

        Args:
            session_id: Chat session ID
            user_id: User identifier
            context: AgentContext instance with trace and token fields
            model_name: Fallback model name (used if not in trace)
            llm_provider: Fallback provider name

        Returns:
            List of created TokenUsage records
        """
        records: List[TokenUsage] = []
        tenant_id = self._tenant_id()

        # Build llm_id -> (model, provider) mapping from llm_start entries
        # since llm_end entries do not carry these fields.
        llm_meta: Dict[str, Dict[str, str]] = {}
        for entry in context.trace:
            if entry.get('type') == 'llm_start':
                llm_id = entry.get('llm_id', '')
                if llm_id:
                    llm_meta[llm_id] = {
                        'model': entry.get('model', '') or '',
                        'provider': entry.get('provider', '') or '',
                    }

        # Parse trace for llm_end entries
        for entry in context.trace:
            if entry.get('type') != 'llm_end':
                continue

            p_tokens = entry.get('prompt_tokens', 0) or 0
            c_tokens = entry.get('completion_tokens', 0) or 0
            cached = entry.get('cached_tokens', 0) or 0
            total = p_tokens + c_tokens
            hit_rate = (cached / p_tokens * 1.0) if p_tokens > 0 else 0.0

            # Look up model/provider from the matching llm_start entry
            llm_id = entry.get('llm_id', '')
            meta = llm_meta.get(llm_id, {})
            resolved_model = meta.get('model') or model_name
            resolved_provider = meta.get('provider') or llm_provider

            record = TokenUsage.objects.create(
                tenant_id=tenant_id,
                session_id=session_id,
                user_id=user_id,
                llm_provider=resolved_provider,
                model_name=resolved_model,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                cached_tokens=cached,
                total_tokens=total,
                cache_hit_rate=hit_rate,
                duration_ms=entry.get('duration_ms', 0) or 0,
                ttft_ms=entry.get('ttft_ms', 0) or 0,
                chunk_count=entry.get('chunk_count', 0) or 0,
                tpot_ms=entry.get('tpot_ms', 0) or 0,
                finish_reason=entry.get('finish_reason', ''),
                metadata={
                    'llm_id': entry.get('llm_id', ''),
                    'iteration': entry.get('iteration', 0),
                },
            )
            records.append(record)

            logger.info(
                "[CacheStats] recorded from trace: model=%s "
                "prompt=%d cached=%d hit_rate=%.1f%% duration=%.0fms",
                record.model_name, p_tokens, cached,
                hit_rate * 100, entry.get('duration_ms', 0),
            )

        if not records:
            logger.debug(
                "[CacheStats] no llm_end entries in trace "
                "(len=%d tokens: prompt=%d cached=%d)",
                len(context.trace),
                context.prompt_tokens,
                context.cached_tokens,
            )

        return records

    # ------------------------------------------------------------------
    # Aggregation queries
    # ------------------------------------------------------------------

    @sync_to_async(thread_sensitive=False)
    def get_overview(
        self,
        days: int = 7,
        tenant_id: Optional[str] = None,
    ) -> CacheStatsOverview:
        """Get aggregated cache statistics for the given period.

        Args:
            days: Number of days to look back (default: 7)
            tenant_id: Tenant filter (default: current tenant)

        Returns:
            A CacheStatsOverview dataclass with aggregated stats
        """
        tid = tenant_id or self._tenant_id()
        since = datetime.now() - timedelta(days=days)

        qs = TokenUsage.objects.filter(
            tenant_id=tid,
            gmt_create__gte=since,
        )

        total_calls = qs.count()
        if total_calls == 0:
            return CacheStatsOverview()

        # Aggregation
        agg = qs.aggregate(
            total_prompt=Sum('prompt_tokens'),
            total_completion=Sum('completion_tokens'),
            total_cached=Sum('cached_tokens'),
            total_duration=Sum(Cast('duration_ms', FloatField())),
        )

        total_prompt = agg['total_prompt'] or 0
        total_completion = agg['total_completion'] or 0
        total_cached = agg['total_cached'] or 0
        total_duration = agg['total_duration'] or 0.0

        overall_hit_rate = (total_cached / total_prompt * 1.0
                            if total_prompt > 0 else 0.0)

        # Cost savings estimate
        cost_savings = (total_cached / 1000) * COST_PER_1K_CACHED_SAVED

        # Model breakdown
        model_breakdown = []
        for entry in qs.values('model_name').annotate(
            calls=Count('id'),
            prompt=Sum('prompt_tokens'),
            cached=Sum('cached_tokens'),
            completion=Sum('completion_tokens'),
            duration=Sum(Cast('duration_ms', FloatField())),
            avg_ttft=Avg(Cast('ttft_ms', FloatField())),
            avg_tpot=Avg(Cast('tpot_ms', FloatField())),
        ).order_by('-calls'):
            p = entry['prompt'] or 0
            c = entry['cached'] or 0
            model_breakdown.append({
                'model_name': entry['model_name'] or 'unknown',
                'calls': entry['calls'],
                'prompt_tokens': p,
                'cached_tokens': c,
                'completion_tokens': entry['completion'] or 0,
                'cache_hit_rate': round((c / p * 100) if p > 0 else 0, 1),
                'duration_ms': entry['duration'] or 0,
                'avg_ttft_ms': round(entry['avg_ttft'] or 0, 1),
                'avg_tpot_ms': round(entry['avg_tpot'] or 0, 2),
            })

        # Daily stats
        daily_stats = []
        for day_offset in range(days):
            day_start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0,
            ) - timedelta(days=day_offset)
            day_end = day_start + timedelta(days=1)

            day_qs = qs.filter(
                gmt_create__gte=day_start,
                gmt_create__lt=day_end,
            )
            day_count = day_qs.count()
            if day_count == 0:
                continue

            day_agg = day_qs.aggregate(
                p=Sum('prompt_tokens'),
                c=Sum('cached_tokens'),
            )
            day_p = day_agg['p'] or 0
            day_c = day_agg['c'] or 0

            daily_stats.append({
                'date': day_start.strftime('%Y-%m-%d'),
                'calls': day_count,
                'prompt_tokens': day_p,
                'cached_tokens': day_c,
                'cache_hit_rate': round((day_c / day_p * 100) if day_p > 0 else 0, 1),
            })

        # Today's stats
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        today_qs = TokenUsage.objects.filter(
            tenant_id=tid,
            gmt_create__gte=today_start,
        )
        today_count = today_qs.count()
        today_agg = today_qs.aggregate(
            p=Sum('prompt_tokens'),
            c=Sum('cached_tokens'),
        )
        today_p = today_agg['p'] or 0
        today_c = today_agg['c'] or 0

        return CacheStatsOverview(
            total_calls=total_calls,
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_cached_tokens=total_cached,
            overall_cache_hit_rate=round(overall_hit_rate * 100, 1),
            estimated_cost_savings=round(cost_savings, 4),
            total_duration_ms=total_duration,
            model_breakdown=model_breakdown,
            daily_stats=list(reversed(daily_stats)),
            today_stats={
                'calls': today_count,
                'prompt_tokens': today_p,
                'cached_tokens': today_c,
                'cache_hit_rate': round((today_c / today_p * 100) if today_p > 0 else 0, 1),
            },
        )

    @sync_to_async(thread_sensitive=False)
    def get_recent_calls(
        self,
        limit: int = 20,
        tenant_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get the most recent LLM call records.

        Args:
            limit: Maximum number of records to return
            tenant_id: Tenant filter (default: current tenant)

        Returns:
            List of recent TokenUsage records as dicts
        """
        tid = tenant_id or self._tenant_id()
        qs = TokenUsage.objects.filter(tenant_id=tid)[:limit]
        rows = list(qs.values(
            'id', 'session_id', 'model_name', 'llm_provider',
            'prompt_tokens', 'cached_tokens', 'completion_tokens',
            'cache_hit_rate', 'duration_ms',
            'ttft_ms', 'chunk_count', 'tpot_ms', 'gmt_create',
        ))
        # FloatCharField values come back as strings from .values();
        # convert them to float for API consistency.
        float_fields = ('cache_hit_rate', 'duration_ms', 'ttft_ms', 'tpot_ms')
        for row in rows:
            for f in float_fields:
                val = row.get(f)
                if val is not None and val != '':
                    try:
                        row[f] = float(val)
                    except (ValueError, TypeError):
                        row[f] = 0.0
                else:
                    row[f] = 0.0
        return rows
