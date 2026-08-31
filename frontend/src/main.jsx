import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import 'bootstrap/dist/css/bootstrap.rtl.min.css'
import 'bootstrap-icons/font/bootstrap-icons.css'
import './index.css'

import App from './App.jsx'
import SentryDevelopmentTest from './components/SentryDevelopmentTest.jsx'
import { initSentry, sentryTestId, Sentry } from './services/sentry.js'

initSentry()

const testId = sentryTestId()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Sentry.ErrorBoundary fallback={(
      <main className="container py-5 text-center" dir="rtl">
        <h1 className="h4">حدث خطأ غير متوقع</h1>
        <p className="text-secondary">تم تسجيل الخطأ، يرجى تحديث الصفحة والمحاولة مرة أخرى.</p>
      </main>
    )}>
      {testId ? (
        <SentryDevelopmentTest testId={testId} />
      ) : (
        <BrowserRouter>
          <App />
        </BrowserRouter>
      )}
    </Sentry.ErrorBoundary>
  </StrictMode>,
)
