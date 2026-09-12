import { Language } from './language';

export const SUPPORTED_LANGUAGES: readonly Language[] = [
  { code: 'ja', label: 'Japanese', flag: '🇯🇵', flagCountryCode: 'jp' },
  { code: 'zh', label: 'Mandarin', flag: '🇨🇳', flagCountryCode: 'cn' },
  { code: 'ko', label: 'Korean', flag: '🇰🇷', flagCountryCode: 'kr' },
];

export const DEFAULT_LANGUAGE: Language = SUPPORTED_LANGUAGES[0];
