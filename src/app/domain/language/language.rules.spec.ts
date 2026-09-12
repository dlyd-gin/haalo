import { Language } from './language';
import { orderLanguagesBySelected } from './language.rules';

describe('language.rules', () => {
  const ja: Language = { code: 'ja', label: 'Japanese', flag: '🇯🇵', flagCountryCode: 'jp' };
  const zh: Language = { code: 'zh', label: 'Mandarin', flag: '🇨🇳', flagCountryCode: 'cn' };
  const es: Language = { code: 'es', label: 'Spanish', flag: '🇪🇸', flagCountryCode: 'es' };
  const ko: Language = { code: 'ko', label: 'Korean', flag: '🇰🇷', flagCountryCode: 'kr' };

  it('moves the selected language to the front, keeping the rest in order', () => {
    const result = orderLanguagesBySelected([ja, zh, es], 'es');

    expect(result).toEqual([es, ja, zh]);
  });

  it('leaves the order unchanged when the selected language is already first', () => {
    const result = orderLanguagesBySelected([ja, zh, es], 'ja');

    expect(result).toEqual([ja, zh, es]);
  });

  it('does not mutate the input array', () => {
    const languages = [ja, zh, es];

    orderLanguagesBySelected(languages, 'es');

    expect(languages).toEqual([ja, zh, es]);
  });

  it('returns a copy of the input order when the selected code is not found', () => {
    const result = orderLanguagesBySelected([ja, zh], 'fr');

    expect(result).toEqual([ja, zh]);
  });

  it('moves Korean to the front when selected', () => {
    const result = orderLanguagesBySelected([ja, zh, ko], 'ko');

    expect(result).toEqual([ko, ja, zh]);
  });
});
