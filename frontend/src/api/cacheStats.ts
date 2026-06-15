import { baseClient } from './client';

export interface CacheStatsOverview {
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cached_tokens: number;
  overall_cache_hit_rate: number;
  estimated_cost_savings: number;
  total_duration_ms: number;
  model_breakdown: ModelBreakdownItem[];
  daily_stats: DailyStatItem[];
  today_stats: TodayStats;
}

export interface ModelBreakdownItem {
  model_name: string;
  calls: number;
  prompt_tokens: number;
  cached_tokens: number;
  completion_tokens: number;
  cache_hit_rate: number;
  duration_ms: number;
  avg_ttft_ms: number;
  avg_tpot_ms: number;
}

export interface DailyStatItem {
  date: string;
  calls: number;
  prompt_tokens: number;
  cached_tokens: number;
  cache_hit_rate: number;
}

export interface TodayStats {
  calls: number;
  prompt_tokens: number;
  cached_tokens: number;
  cache_hit_rate: number;
}

export interface RecentCallRecord {
  id: number;
  session_id: string;
  model_name: string;
  llm_provider: string;
  prompt_tokens: number;
  cached_tokens: number;
  completion_tokens: number;
  cache_hit_rate: number;
  duration_ms: number;
  ttft_ms: number;
  chunk_count: number;
  tpot_ms: number;
  gmt_create: string;
}

export interface RecentCallsResponse {
  records: RecentCallRecord[];
}

// Get cache stats overview
export const getCacheStatsOverview = async (days: number = 7): Promise<CacheStatsOverview> => {
  const response = await baseClient.get<CacheStatsOverview>('/chatbot/api/admin/cache-stats/overview/', {
    params: { days },
  });
  return response.data;
};

// Get recent LLM call records
export const getRecentCalls = async (limit: number = 20): Promise<RecentCallsResponse> => {
  const response = await baseClient.get<RecentCallsResponse>('/chatbot/api/admin/cache-stats/recent/', {
    params: { limit },
  });
  return response.data;
};
