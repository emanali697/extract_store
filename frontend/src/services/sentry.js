import * as Sentry from '@sentry/react'

const EMAIL_RE = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi
const PHONE_RE = /(?:\+?\d[\d\s().-]{7,}\d)/g
const TOKEN_RE = /\b(?:Bearer\s+)?(?:sntrys_|gho_|AIza)[A-Za-z0-9._-]+\b/gi

function redactText(value) {
  if (typeof value !== 'string') return value
  return value
    .replace(EMAIL_RE, '[email]')
    .replace(PHONE_RE, '[phone]')
    .replace(TOKEN_RE, '[token]')
}

function sanitizeEvent(event) {
  event.user = { ip_address: '0.0.0.0' }
  delete event.request
  delete event.server_name

  if (event.message) event.message = redactText(event.message)
  if (event.logentry?.message) event.logentry.message = redactText(event.logentry.message)

  for (const value of event.exception?.values ?? []) {
    value.value = redactText(value.value)
  }

  event.breadcrumbs = (event.breadcrumbs ?? []).map((breadcrumb) => ({
    ...breadcrumb,
    message: redactText(breadcrumb.message),
    data: undefined,
  }))
  event.extra = undefined
  return event
}

function sampleRate(value, fallback) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 ? parsed : fallback
}

export function initSentry() {
  const dsn = import.meta.env.VITE_SENTRY_DSN?.trim()
  if (!dsn) return false

  Sentry.init({
    dsn,
    environment: import.meta.env.VITE_SENTRY_ENVIRONMENT || import.meta.env.MODE,
    release: import.meta.env.VITE_SENTRY_RELEASE || undefined,
    integrations: [Sentry.browserTracingIntegration()],
    tracesSampleRate: sampleRate(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE, 0.1),
    sendDefaultPii: false,
    beforeSend: sanitizeEvent,
  })
  Sentry.setTag('app_runtime', 'frontend')
  return true
}

export function sentryTestId() {
  if (!import.meta.env.DEV) return ''
  const requested = new URLSearchParams(window.location.search).get('sentry-test')
  return requested?.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 48) || ''
}

export { Sentry }
