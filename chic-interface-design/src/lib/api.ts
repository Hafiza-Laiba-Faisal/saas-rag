export const API_BASE = '/api/v1';

function getApiBaseUrl() {
  return '/api/v1';
}

export function getAuthToken() {
  return sessionStorage.getItem('rag_admin_token') || localStorage.getItem('rag_admin_token');
}

export function setAuthToken(token: string | null) {
  if (token) {
    sessionStorage.setItem('rag_admin_token', token);
    localStorage.setItem('rag_admin_token', token);
  } else {
    sessionStorage.removeItem('rag_admin_token');
    localStorage.removeItem('rag_admin_token');
  }
}

export async function apiFetch(endpoint: string, options: RequestInit = {}) {
  const token = getAuthToken();
  const headers = new Headers(options.headers || {});
  
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  
  const response = await fetch(`${getApiBaseUrl()}${endpoint}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    setAuthToken(null);
    window.location.href = '/login'; // Redirect to login
  }

  if (!response.ok) {
    let errMsg = response.statusText;
    try {
      const data = await response.json();
      if (data.detail) errMsg = data.detail;
    } catch {
      // ignore
    }
    throw new Error(errMsg);
  }

  return response;
}
