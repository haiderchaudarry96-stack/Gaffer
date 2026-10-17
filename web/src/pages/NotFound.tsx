import { ButtonLink } from '../components/ui/Button'
import { EmptyState } from '../components/ui/States'

export default function NotFound() {
  return (
    <main className="grid min-h-screen place-items-center bg-bg px-4">
      <EmptyState title="Off the pitch">
        <p className="mb-5">That page does not exist.</p>
        <ButtonLink to="/">Back to Gaffer</ButtonLink>
      </EmptyState>
    </main>
  )
}
