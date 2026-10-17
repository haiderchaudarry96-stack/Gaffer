import { useId } from 'react'
import { MessageSquare, Send } from 'lucide-react'
import Panel from './Panel'

/** Chat reuses the agent's tools, so it needs the backend. Shown, but switched off. */
export default function ChatPanel() {
  const id = useId()
  return (
    <Panel title="Ask Gaffer" id="chat-title" actions={<MessageSquare className="size-4 text-muted" aria-hidden="true" />}>
      <form className="space-y-2 p-4" onSubmit={(e) => e.preventDefault()} aria-describedby={`${id}-note`}>
        <label htmlFor={id} className="sr-only">
          Question about the match
        </label>
        <div className="flex gap-2">
          <input
            id={id}
            disabled
            placeholder="Why did White go to a back three?"
            className="h-10 min-w-0 flex-1 rounded-full border border-line bg-bg px-4 text-sm text-text placeholder:text-muted disabled:cursor-not-allowed"
          />
          <button type="submit" disabled className="grid size-10 place-items-center rounded-full bg-surface-2 text-muted disabled:cursor-not-allowed" aria-label="Send">
            <Send className="size-4" aria-hidden="true" />
          </button>
        </div>
        <p id={`${id}-note`} className="text-xs text-muted">
          Needs the backend: chat answers through the agent’s tools on Amazon Bedrock, which this static demo does not
          call.
        </p>
      </form>
    </Panel>
  )
}
