import React, { useState } from 'react';
import { Card, Row, Col, Statistic, Table, Tag, Typography, Spin, Select, Space, Progress } from 'antd';
import {
  ApiOutlined,
  ThunderboltOutlined,
  DollarOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import { getCacheStatsOverview, getRecentCalls } from '@/api/cacheStats';
import type { ModelBreakdownItem, DailyStatItem, RecentCallRecord } from '@/api/cacheStats';

const { Title, Text } = Typography;

const CacheMonitor: React.FC = () => {
  const [days, setDays] = useState<number>(7);

  const { data: overview, isLoading: overviewLoading } = useQuery({
    queryKey: ['cache-stats-overview', days],
    queryFn: () => getCacheStatsOverview(days),
  });

  const { data: recentData, isLoading: recentLoading } = useQuery({
    queryKey: ['cache-stats-recent'],
    queryFn: () => getRecentCalls(20),
  });

  // ── Model breakdown columns ──
  const modelColumns = [
    {
      title: 'Model',
      dataIndex: 'model_name',
      key: 'model_name',
      render: (name: string) => <Text code>{name}</Text>,
    },
    {
      title: 'Calls',
      dataIndex: 'calls',
      key: 'calls',
      sorter: (a: ModelBreakdownItem, b: ModelBreakdownItem) => a.calls - b.calls,
    },
    {
      title: 'Prompt Tokens',
      dataIndex: 'prompt_tokens',
      key: 'prompt_tokens',
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: 'Cached Tokens',
      dataIndex: 'cached_tokens',
      key: 'cached_tokens',
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: 'Cache Hit Rate',
      dataIndex: 'cache_hit_rate',
      key: 'cache_hit_rate',
      sorter: (a: ModelBreakdownItem, b: ModelBreakdownItem) => a.cache_hit_rate - b.cache_hit_rate,
      render: (rate: number) => {
        const color = rate > 50 ? '#3f8600' : rate > 20 ? '#faad14' : '#cf1322';
        return <Tag color={color}>{rate}%</Tag>;
      },
    },
    {
      title: 'Duration (ms)',
      dataIndex: 'duration_ms',
      key: 'duration_ms',
      render: (val: number) => Math.round(val).toLocaleString(),
    },
    {
      title: 'Avg TTFT',
      dataIndex: 'avg_ttft_ms',
      key: 'avg_ttft_ms',
      sorter: (a: ModelBreakdownItem, b: ModelBreakdownItem) => a.avg_ttft_ms - b.avg_ttft_ms,
      render: (val: number) => val ? `${Math.round(val)}ms` : '-',
    },
    {
      title: 'Avg TPOT',
      dataIndex: 'avg_tpot_ms',
      key: 'avg_tpot_ms',
      sorter: (a: ModelBreakdownItem, b: ModelBreakdownItem) => a.avg_tpot_ms - b.avg_tpot_ms,
      render: (val: number) => {
        if (!val) return '-';
        return val < 1 ? `${(val * 1000).toFixed(0)}ms/tk` : `${val.toFixed(1)}ms/tk`;
      },
    },
  ];

  // ── Daily stats columns ──
  const dailyColumns = [
    {
      title: 'Date',
      dataIndex: 'date',
      key: 'date',
    },
    {
      title: 'Calls',
      dataIndex: 'calls',
      key: 'calls',
    },
    {
      title: 'Prompt Tokens',
      dataIndex: 'prompt_tokens',
      key: 'prompt_tokens',
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: 'Cached Tokens',
      dataIndex: 'cached_tokens',
      key: 'cached_tokens',
      render: (val: number) => val.toLocaleString(),
    },
    {
      title: 'Cache Hit Rate',
      dataIndex: 'cache_hit_rate',
      key: 'cache_hit_rate',
      render: (rate: number) => (
        <Space>
          <Progress
            percent={Math.round(rate)}
            size="small"
            style={{ width: 100, margin: 0 }}
            strokeColor={rate > 50 ? '#3f8600' : rate > 20 ? '#faad14' : '#cf1322'}
          />
          <Text type="secondary">{rate}%</Text>
        </Space>
      ),
    },
  ];

  // ── Recent calls columns ──
  const recentColumns = [
    {
      title: 'Time',
      dataIndex: 'gmt_create',
      key: 'gmt_create',
      width: 180,
      render: (ts: string) => {
        if (!ts) return '-';
        const d = new Date(ts);
        return d.toLocaleString();
      },
    },
    {
      title: 'Model',
      dataIndex: 'model_name',
      key: 'model_name',
      render: (name: string) => <Text code>{name || '-'}</Text>,
    },
    {
      title: 'Provider',
      dataIndex: 'llm_provider',
      key: 'llm_provider',
    },
    {
      title: 'Prompt',
      dataIndex: 'prompt_tokens',
      key: 'prompt_tokens',
    },
    {
      title: 'Cached',
      dataIndex: 'cached_tokens',
      key: 'cached_tokens',
    },
    {
      title: 'Hit Rate',
      dataIndex: 'cache_hit_rate',
      key: 'cache_hit_rate',
      render: (rate: number) => {
        const pct = Math.round(rate * 100);
        const color = pct > 50 ? '#3f8600' : pct > 20 ? '#faad14' : '#cf1322';
        return <Tag color={color}>{pct}%</Tag>;
      },
    },
    {
      title: 'Duration',
      dataIndex: 'duration_ms',
      key: 'duration_ms',
      render: (val: number) => val ? `${Math.round(val)}ms` : '-',
    },
    {
      title: 'TTFT',
      dataIndex: 'ttft_ms',
      key: 'ttft_ms',
      render: (val: number) => val ? `${Math.round(val)}ms` : '-',
    },
    {
      title: 'Chunks',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      render: (val: number) => val || '-',
    },
    {
      title: 'TPOT',
      dataIndex: 'tpot_ms',
      key: 'tpot_ms',
      render: (val: number) => {
        if (!val) return '-';
        return val < 1 ? `${(val * 1000).toFixed(0)}ms/tk` : `${val.toFixed(1)}ms/tk`;
      },
    },
  ];

  if (overviewLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
        <Spin size="large" />
      </div>
    );
  }

  return (
    <div style={{ padding: 24 }}>
      {/* Header */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>Cache Monitor</Title>
          <Text type="secondary">KV Cache 命中率与 Token 用量监控</Text>
        </Col>
        <Col>
          <Space>
            <Text>周期:</Text>
            <Select value={days} onChange={setDays} style={{ width: 120 }}>
              <Select.Option value={1}>Today</Select.Option>
              <Select.Option value={3}>3 days</Select.Option>
              <Select.Option value={7}>7 days</Select.Option>
              <Select.Option value={14}>14 days</Select.Option>
              <Select.Option value={30}>30 days</Select.Option>
            </Select>
          </Space>
        </Col>
      </Row>

      {/* Overview Cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="Total LLM Calls"
              value={overview?.total_calls || 0}
              prefix={<ApiOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="Overall Cache Hit Rate"
              value={overview?.overall_cache_hit_rate || 0}
              suffix="%"
              precision={1}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: (overview?.overall_cache_hit_rate || 0) > 30 ? '#3f8600' : '#cf1322' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="Today Cache Hit Rate"
              value={overview?.today_stats?.cache_hit_rate || 0}
              suffix="%"
              precision={1}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: (overview?.today_stats?.cache_hit_rate || 0) > 30 ? '#3f8600' : '#cf1322' }}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card hoverable>
            <Statistic
              title="Est. Cost Savings"
              value={overview?.estimated_cost_savings || 0}
              prefix={<DollarOutlined />}
              precision={4}
              valueStyle={{ color: '#3f8600' }}
            />
          </Card>
        </Col>
      </Row>

      {/* Today & Total Tokens */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12}>
          <Card title="Today's Stats" size="small">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="Calls"
                  value={overview?.today_stats?.calls || 0}
                  valueStyle={{ fontSize: 20 }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="Prompt Tokens"
                  value={overview?.today_stats?.prompt_tokens || 0}
                  valueStyle={{ fontSize: 20 }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="Cached Tokens"
                  value={overview?.today_stats?.cached_tokens || 0}
                  valueStyle={{ fontSize: 20, color: '#1677ff' }}
                />
              </Col>
            </Row>
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card title="Total (Selected Period)" size="small">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="Prompt Tokens"
                  value={overview?.total_prompt_tokens || 0}
                  valueStyle={{ fontSize: 20 }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="Cached Tokens"
                  value={overview?.total_cached_tokens || 0}
                  valueStyle={{ fontSize: 20, color: '#1677ff' }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="Completion Tokens"
                  value={overview?.total_completion_tokens || 0}
                  valueStyle={{ fontSize: 20 }}
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>

      {/* Model Breakdown */}
      <Card
        title="Model Breakdown"
        size="small"
        style={{ marginBottom: 24 }}
      >
        <Table
          dataSource={overview?.model_breakdown || []}
          columns={modelColumns}
          rowKey={(record) => record.model_name}
          pagination={false}
          size="small"
        />
      </Card>

      {/* Daily Stats */}
      {overview?.daily_stats && overview.daily_stats.length > 0 && (
        <Card
          title="Daily Cache Hit Rate Trend"
          size="small"
          style={{ marginBottom: 24 }}
        >
          <Table
            dataSource={overview.daily_stats}
            columns={dailyColumns}
            rowKey="date"
            pagination={false}
            size="small"
          />
        </Card>
      )}

      {/* Recent Calls */}
      <Card
        title="Recent LLM Calls"
        size="small"
        loading={recentLoading}
      >
        <Table
          dataSource={recentData?.records || []}
          columns={recentColumns}
          rowKey="id"
          pagination={{ pageSize: 10, showSizeChanger: false }}
          size="small"
        />
      </Card>
    </div>
  );
};

export default CacheMonitor;
