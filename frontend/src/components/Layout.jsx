import { NavLink, Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import ResumeBanner from './ResumeBanner'

export default function Layout() {
  return (
    <div className="app-shell">
      <main className="app-main">
        <header className="app-header d-flex align-items-center justify-content-between flex-wrap gap-2">
          <div>
            <h1>
              <i className="bi bi-shop me-2" aria-hidden="true"></i>
              نظام استخراج بيانات المتاجر
            </h1>
            <p>ارفع فيديو الشارع — هنطلعلك كل المحلات بأرقامها ومواقعها</p>
          </div>
          <span className="badge bg-light text-primary fw-semibold px-3 py-2">
            Pipeline v6
          </span>
        </header>

        <ResumeBanner />

        <nav className="app-nav mb-3">
          <ul className="nav nav-pills flex-wrap gap-2">
            <li className="nav-item">
              <NavLink to="/upload" className="nav-link">
                <i className="bi bi-cloud-arrow-up"></i> رفع الفيديو
              </NavLink>
            </li>
            <li className="nav-item">
              <NavLink to="/progress" className="nav-link">
                <i className="bi bi-lightning-charge"></i> التقدم
              </NavLink>
            </li>
            <li className="nav-item">
              <NavLink to="/review" className="nav-link">
                <i className="bi bi-clipboard-check"></i> المراجعة
              </NavLink>
            </li>
            <li className="nav-item">
              <NavLink to="/results" className="nav-link">
                <i className="bi bi-table"></i> النتائج
              </NavLink>
            </li>
          </ul>
        </nav>

        <Outlet />
      </main>

      <aside className="app-sidebar">
        <Sidebar />
      </aside>
    </div>
  )
}
