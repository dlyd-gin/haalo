import { isWebKitOnly } from './webkit';

const MAC_SAFARI =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15';
const IOS_SAFARI =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1';
const IOS_CHROME =
  'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/123.0.6312.52 Mobile/15E148 Safari/604.1';
const MAC_CHROME =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36';
const ANDROID_CHROME =
  'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36';
const WIN_EDGE =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0';
const MAC_FIREFOX = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) Gecko/20100101 Firefox/124.0';

describe('isWebKitOnly', () => {
  it('is true for Safari and iOS browsers', () => {
    expect(isWebKitOnly(MAC_SAFARI)).toBe(true);
    expect(isWebKitOnly(IOS_SAFARI)).toBe(true);
    expect(isWebKitOnly(IOS_CHROME)).toBe(true);
  });

  it('is false for Blink browsers and Firefox', () => {
    expect(isWebKitOnly(MAC_CHROME)).toBe(false);
    expect(isWebKitOnly(ANDROID_CHROME)).toBe(false);
    expect(isWebKitOnly(WIN_EDGE)).toBe(false);
    expect(isWebKitOnly(MAC_FIREFOX)).toBe(false);
  });
});
