/** Reads a local video's duration, size and first frame in the browser (nothing is uploaded). */
export interface LocalVideoInfo {
  file: File
  url: string
  duration: number
  width: number
  height: number
  /** JPEG data URL of the frame at `frameT` seconds */
  frameUrl: string
  frameT: number
}

const OK_TYPES = ['video/mp4', 'video/quicktime']
const OK_EXT = /\.(mp4|mov)$/i

export function isAcceptedVideo(file: File): boolean {
  return OK_TYPES.includes(file.type) || OK_EXT.test(file.name)
}

export function readVideo(file: File): Promise<LocalVideoInfo> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const v = document.createElement('video')
    v.preload = 'auto'
    v.muted = true
    v.playsInline = true
    const fail = () => {
      URL.revokeObjectURL(url)
      reject(new Error('This browser cannot open this video. Try an H.264 MP4.'))
    }
    v.onerror = fail
    v.onloadedmetadata = () => {
      if (!v.videoWidth || !Number.isFinite(v.duration)) return fail()
      v.currentTime = Math.min(0.1, v.duration / 2)
    }
    v.onseeked = () => {
      const c = document.createElement('canvas')
      // keep the frame light: at most 1280 px wide for the on-screen preview
      const scale = Math.min(1, 1280 / v.videoWidth)
      c.width = Math.round(v.videoWidth * scale)
      c.height = Math.round(v.videoHeight * scale)
      c.getContext('2d')!.drawImage(v, 0, 0, c.width, c.height)
      resolve({ file, url, duration: v.duration, width: v.videoWidth, height: v.videoHeight, frameUrl: c.toDataURL('image/jpeg', 0.85), frameT: v.currentTime })
    }
    v.src = url
  })
}

export function formatBytes(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)} GB`
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`
  return `${Math.max(1, Math.round(n / 1e3))} KB`
}

export function formatDuration(s: number): string {
  const t = Math.round(s)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const sec = t % 60
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}` : `${m}:${String(sec).padStart(2, '0')}`
}
