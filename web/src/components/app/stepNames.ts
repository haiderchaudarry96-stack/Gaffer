/** Coach-facing names of the agent's tool calls. */
export const STEP_NAMES: Record<string, string> = {
  check_frame_quality: 'Camera check (OpenCV)',
  reanalyse_window: 'Second look (OpenCV)',
  record_decision: 'Rules verdict',
  render_evidence: 'Evidence image (OpenCV)',
  propose_alert: 'Alert for you',
}
