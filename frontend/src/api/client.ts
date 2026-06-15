import axios, { type AxiosInstance, type AxiosError } from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE || '';

// Base client without auth
export const baseClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Client with auth interceptor
export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor - adds X-Tenant-Id header for tenant context
baseClient.interceptors.request.use(
  (config) => {
    const tenantId = localStorage.getItem('asri_tenant_id');
    if (tenantId) {
      config.headers['X-Tenant-Id'] = tenantId;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Request interceptor - adds token from localStorage (legacy support)
apiClient.interceptors.request.use(
  (config) => {
    const tenantId = localStorage.getItem('asri_tenant_id');
    if (tenantId) {
      config.headers['X-Tenant-Id'] = tenantId;
    }
    const token = localStorage.getItem('asri_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('asri_token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default apiClient;
