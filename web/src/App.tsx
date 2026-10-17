import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { domAnimation, LazyMotion, MotionConfig } from 'motion/react'
import LandingPage from './pages/LandingPage'
import NotFound from './pages/NotFound'
import { PageSkeleton } from './components/ui/States'

// The analyst desk is a separate chunk: the landing page stays light.
const AppPage = lazy(() => import('./pages/AppPage'))

export default function App() {
  return (
    // reducedMotion="user": Motion turns transform/layout animations off when the OS asks for it.
    <MotionConfig reducedMotion="user">
      {/* LazyMotion + m.* keeps the animation code small (only the DOM animation features) */}
      <LazyMotion features={domAnimation} strict>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LandingPage />} />
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
