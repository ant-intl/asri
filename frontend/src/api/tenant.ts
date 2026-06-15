import { baseClient } from './client';

export interface TenantInfo {
  tenant_id: string;
  name: string;
}

export interface CreateTenantRequest {
  tenant_id: string;
  name: string;
  config_json?: Record<string, unknown>;
}

export const getTenants = async (): Promise<TenantInfo[]> => {
  const response = await baseClient.get('/chatbot/api/admin/tenants/');
  return response.data;
};

export const createTenant = async (data: CreateTenantRequest): Promise<TenantInfo> => {
  const response = await baseClient.post('/chatbot/api/admin/tenants/', data);
  return response.data;
};
