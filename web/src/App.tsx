import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { domAnimation, LazyMotion, MotionConfig } from 'motion/react'
import NotFound from './pages/NotFound'
import { PageSkeleton } from './components/ui/States'

import { getAlerts, getExplanations, getReport, getRunRows, getTimeline, getTrace } from './lib/matchData'

// The analyst desk is a separate chunk: the landing page stays light. Its small data files start
// downloading together with the chunk instead of after it (one round trip less on slow networks).
// Each route is its own chunk, so /app does not parse the landing page's code and vice versa.
const LandingPage = lazy(() => import('./pages/LandingPage'))
const AppPage = lazy(() => {
  for (const load of [getTimeline, getAlerts, getTrace, getRunRows, getReport, getExplanations]) load().catch(() => {})
  return import('./pages/AppPage')
})

export default function App() {
  return (
    // reducedMotion="user": Motion turns transform/layout animations off when the OS asks for it.
    <MotionConfig reducedMotion="user">
      {/* LazyMotion + m.* keeps the animation code small (only the DOM animation features) */}
      <LazyMotion features={domAnimation} strict>
      <BrowserRouter>
        <Routes>
          <Route
            path="/"
            element={
              <Suspense fallback={<div className="min-h-screen bg-bg" />}>
                <LandingPage />
              </Suspense>
            }
          />
          <Route
            path="/app"
            element={
              <Suspense fallback={<PageSkeleton />}>
                <AppPage />
              </Suspense>
            }
          />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
      </LazyMotion>
    </MotionConfig>
  )
}
