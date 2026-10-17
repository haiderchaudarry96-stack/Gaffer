/**
 * Times chosen from the real data with scripts/pick-windows.mjs (output, 17 Oct):
 *   hero: 19:16-20:20 (128 frames), mean outfield in a team: White 9.66, Blue 9.53
 *   app start: 16:17 (every frame to 16:30: White >= 9, Blue >= 8 outfield in a team)
 *
 * Hero: the longest stretch of the 15:00-21:00 window where, in every frame, both teams have at
 * least 8 outfield players assigned to them AND the tactics engine reads a confident shape for
 * both (no "uncertain" segment). So the first impression is a full, readable pitch.
 * /app: starts 13 s before the confirmed 16:30 change, from the point where coverage is full.
 */
export const HERO_WINDOW: [number, number] = [1156, 1220]
export const APP_START_S = 977
/** the confirmed change the landing story and live replay follow */
export const STORY_EVENT = 'evt_003'
