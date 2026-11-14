// True for browsers that run on WebKit's media stack: macOS Safari and every iOS browser
// (iOS Chrome reports "CriOS" and iOS Firefox "FxiOS", never a "Chrome" token). Those can't
// play the TTS stream through <audio src> — WebKit insists on byte-range requests and a known
// length, which the streaming /api/tts response doesn't offer — so they take the Web Audio path.
// Blink browsers (Chrome/Chromium/Edge/Opera) also carry "AppleWebKit" in their UA, hence the
// exclusions; Firefox desktop doesn't carry it at all.
export function isWebKitOnly(userAgent: string): boolean {
  return /AppleWebKit/.test(userAgent) && !/Chrome|Chromium|Edg|OPR/.test(userAgent);
}
