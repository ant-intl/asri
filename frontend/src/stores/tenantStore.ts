import { create } from 'zustand';

const STORAGE_KEY = 'asri_tenant_id';

interface TenantStore {
  currentTenantId: string;
  setCurrentTenant: (tenantId: string) => void;
}

export const useTenantStore = create<TenantStore>((set) => ({
  currentTenantId: localStorage.getItem(STORAGE_KEY) || 'default',
  setCurrentTenant: (tenantId: string) => {
    localStorage.setItem(STORAGE_KEY, tenantId);
    set({ currentTenantId: tenantId });
  },
}));
