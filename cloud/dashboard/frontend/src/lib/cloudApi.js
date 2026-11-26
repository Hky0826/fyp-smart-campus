let unauthorizedHandler = null;

export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn;
}

function getCsrfToken() {
  if (typeof document === 'undefined') return '';
  const entry = document.cookie.split('; ').find((v) => v.startsWith('csrf_token='));
  return entry ? decodeURIComponent(entry.split('=').slice(1).join('=')) : '';
}

export class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

export async function cloudFetch(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers || {});
  const isFormData = options.body instanceof FormData;
  const isUrlEncoded = options.body instanceof URLSearchParams;

  if (!isFormData && !isUrlEncoded && options.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) headers.set('X-CSRF-Token', csrf);
  }

  const response = await fetch(url, {
    ...options,
    method,
    headers,
    credentials: 'include',
  });

  if (response.status === 401 && !url.includes('/api/auth/login') && !url.includes('/api/auth/me')) {
    if (typeof unauthorizedHandler === 'function') {
      unauthorizedHandler();
    }
  }

  let data = null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    data = await response.json().catch(() => null);
  } else {
    const text = await response.text().catch(() => '');
    data = text ? { detail: text } : null;
  }

  if (!response.ok) {
    const msg =
      (typeof data?.detail === 'string' && data.detail) ||
      (Array.isArray(data?.detail) && data.detail.map((d) => d.msg || String(d)).join('; ')) ||
      `Request failed with status ${response.status}`;
    throw new ApiError(msg, response.status, data);
  }

  return data;
}

export const cloudApi = {
  get: (url, params) => {
    if (!params) return cloudFetch(url);
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '' && v !== 'ALL') {
        qs.set(k, String(v));
      }
    });
    const queryStr = qs.toString();
    return cloudFetch(queryStr ? `${url}?${queryStr}` : url);
  },
  post: (url, body) =>
    cloudFetch(url, {
      method: 'POST',
      body: body instanceof FormData || body instanceof URLSearchParams ? body : JSON.stringify(body ?? {}),
    }),
  put: (url, body) =>
    cloudFetch(url, {
      method: 'PUT',
      body: body instanceof FormData ? body : JSON.stringify(body ?? {}),
    }),
  delete: (url) => cloudFetch(url, { method: 'DELETE' }),
};

function parseUtcDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  let str = String(value).trim();
  if (!str) return null;
  // Backend stores naive UTC timestamps (e.g. "2026-11-26T01:05:00"); treat them as UTC.
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(str) && !/(Z|[+-]\d{2}:?\d{2})$/i.test(str)) {
    str = str.replace(' ', 'T') + 'Z';
  }
  const d = new Date(str);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function formatDateTime(value) {
  if (!value) return 'Never';
  const d = parseUtcDate(value);
  if (!d) return String(value);
  return d.toLocaleString('en-MY', {
    timeZone: 'Asia/Kuala_Lumpur',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  });
}

export function formatRelativeTime(value) {
  if (!value) return 'Never';
  const d = parseUtcDate(value);
  if (!d) return String(value);
  const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diffSec < 60) return 'Just now';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 604800) return `${Math.floor(diffSec / 86400)}d ago`;
  return d.toLocaleDateString('en-MY', { timeZone: 'Asia/Kuala_Lumpur' });
}
